from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Mapping

from .chart_source import ChartSource
from .config import TOP_N, Config
from .discord import (
    get_poll_results,
    human_date,
    post_failure,
    post_playlist,
    songs_csv,
)
from .poll import build_recap
from .schedule import advance, select_chart, snap_to_saturday, week_of_month
from .spotify import SpotifyClient, SpotifyError
from .state import load_state, run_key, save_state


def playlist_name(display_name: str, chart_date: date) -> str:
    return f"Billboard {display_name} Top {TOP_N} — {human_date(chart_date)}"


def run(
    config: Config,
    state_path: Path,
    env: Mapping[str, str],
    source: ChartSource,
    spotify: SpotifyClient | None,
    today: date,
    dry_run: bool = False,
    notify=post_playlist,
    notify_failure=post_failure,
    fetch_results=get_poll_results,
) -> int:
    webhook = env.get("DISCORD_WEBHOOK_URL", "")
    try:
        state = load_state(state_path, default_cursor=config.start_date)
        recap = None
        if not dry_run:
            try:
                recap = build_recap(state, webhook, fetch_results)
            except Exception as exc:  # noqa: BLE001 - a recap never fails the run
                print(f"recap failed: {exc}", file=sys.stderr)
        chart_date = snap_to_saturday(state.cursor)

        resume_key = next(
            (
                k
                for k, rec in state.completed.items()
                if k.endswith(f"@{chart_date.isoformat()}") and not rec.get("posted")
            ),
            None,
        )
        if resume_key is not None:
            chart_id = resume_key.split("@", 1)[0]
            chart = config.charts[chart_id]
            week = state.completed[resume_key].get("week", week_of_month(today))
        else:
            week = week_of_month(today)
            chart = select_chart(config, chart_date, week, state.wildcard_index)
        key = run_key(chart.id, chart_date)
        name = playlist_name(chart.display_name, chart_date)

        record = state.completed.get(key, {})
        if record.get("posted"):
            print(f"{key} already completed; nothing to do")
            return 0

        songs = source.fetch(chart.slug, chart_date)[:TOP_N]

        if dry_run:
            print(f"[dry-run] {name} (slot week {week})")
            for s in songs:
                print(f"  {s.rank:>2}. {s.title} — {s.artist}")
            return 0

        assert spotify is not None
        playlist_url = record.get("playlist_url")
        uris, matched = [], 0
        if playlist_url is None:
            for song in songs:
                try:
                    uri = spotify.find_track(song)
                except SpotifyError as exc:
                    uri = None
                    print(
                        f"spotify lookup failed for {song.title} — {song.artist}: {exc}",
                        file=sys.stderr,
                    )
                if uri:
                    uris.append(uri)
                    matched += 1
                else:
                    print(f"no match: {song.title} — {song.artist}", file=sys.stderr)
            description = (
                f"The Billboard {chart.display_name} chart for the week of "
                f"{chart_date.isoformat()}, courtesy of fiftyfm."
            )
            playlist_url = spotify.create_playlist(name, description, uris)
            state.completed[key] = {
                "playlist_url": playlist_url,
                "matched": matched,
                "posted": False,
                "week": week,
            }
            save_state(state_path, state)
        else:
            matched = record.get("matched", len(songs))

        thread_id = notify(
            webhook,
            thread_title=name,
            chart_name=chart.display_name,
            chart_date=chart_date,
            songs=songs,
            matched=matched,
            playlist_url=playlist_url,
            csv_filename=f"{chart.id}-{chart_date.isoformat()}.csv",
            csv_data=songs_csv(songs).encode(),
            recap=recap,
        )
        state.completed[key]["posted"] = True
        if thread_id:
            state.completed[key]["thread_id"] = thread_id
        state.last_posted_key = key
        state.cursor = advance(state.cursor, config.weeks_per_run)
        if week >= 4:
            state.wildcard_index += 1
        save_state(state_path, state)
        print(f"done: {name} -> {playlist_url}")
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level run boundary
        print(f"run failed: {exc}", file=sys.stderr)
        if webhook:
            notify_failure(webhook, f"fiftyfm weekly run failed: {exc}")
        return 1
