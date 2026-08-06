from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Mapping

from .chart_source import ChartSource, Song
from .config import TOP_N, ChartDef, Config
from .discord import (
    get_poll_results,
    human_date,
    post_failure,
    post_playlist,
    songs_csv,
)
from .poll import build_recap
from .schedule import (
    advance,
    next_chart,
    select_chart,
    snap_to_saturday,
    week_of_month,
)
from .spotify import SpotifyClient, SpotifyError
from .state import State, load_state, run_key, save_state

# How many periods a skip's time-jump may walk forward looking for a week it
# has not already posted. A rewound cursor should fail loudly, not spin
# through decades of history.
MAX_JUMPS = 8


def playlist_name(display_name: str, chart_date: date) -> str:
    return f"Billboard {display_name} Top {TOP_N} — {human_date(chart_date)}"


def post_chart(
    state: State,
    state_path: Path,
    env: Mapping[str, str],
    spotify: SpotifyClient,
    *,
    chart: ChartDef,
    chart_date: date,
    week: int,
    songs: list[Song],
    recap: str | None = None,
    notify=post_playlist,
) -> str:
    """Create the playlist, post the thread, and record it in `state`.

    Saves once before posting so a Discord failure leaves a reusable
    playlist behind. Deliberately does not touch `state.cursor` and does not
    save afterwards: `run` advances the cursor and `skip` usually does not,
    so the caller owns that decision and the final write. Returns the
    playlist URL so the caller can print its success line after its own
    final save.
    """
    webhook = env.get("DISCORD_WEBHOOK_URL", "")
    key = run_key(chart.id, chart_date)
    name = playlist_name(chart.display_name, chart_date)
    record = state.completed.get(key, {})
    playlist_url = record.get("playlist_url")
    matched = 0
    if playlist_url is None:
        uris = []
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
    if week >= 4:
        state.wildcard_index += 1
    return playlist_url


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
            if state.slot_consumed is not None and week <= state.slot_consumed:
                week = state.slot_consumed + 1
            chart = select_chart(config, chart_date, week, state.wildcard_index)
        key = run_key(chart.id, chart_date)
        name = playlist_name(chart.display_name, chart_date)

        record = state.completed.get(key, {})
        if record.get("posted"):
            print(f"{key} already completed; nothing to do")
            return 0

        fetched = source.fetch(chart, chart_date)
        songs = fetched.songs[:TOP_N]

        if dry_run:
            print(f"[dry-run] {name} (slot week {week})")
            for s in songs:
                print(f"  {s.rank:>2}. {s.title} — {s.artist}")
            return 0

        assert spotify is not None
        playlist_url = post_chart(
            state,
            state_path,
            env,
            spotify,
            chart=chart,
            chart_date=chart_date,
            week=week,
            songs=songs,
            recap=recap,
            notify=notify,
        )
        state.cursor = advance(state.cursor, config.weeks_per_run)
        if resume_key is None:
            state.slot_consumed = None
        save_state(state_path, state)
        print(f"done: {name} -> {playlist_url}")
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level run boundary
        print(f"run failed: {exc}", file=sys.stderr)
        if webhook:
            notify_failure(webhook, f"fiftyfm weekly run failed: {exc}")
        return 1


def skip(
    config: Config,
    state_path: Path,
    env: Mapping[str, str],
    source: ChartSource,
    spotify: SpotifyClient | None,
    today: date,
    dry_run: bool = False,
    notify=post_playlist,
    notify_failure=post_failure,
) -> int:
    """Post a replacement for the chart the last run posted.

    Runs after a Monday post, so the cursor has already advanced. A
    replacement found at the same historical date leaves the cursor alone;
    when no candidate remains, jump forward and post what a future Monday
    would have, stepping over any target week already posted (up to
    `MAX_JUMPS` periods) and leaving the cursor beyond wherever it landed.
    """
    webhook = env.get("DISCORD_WEBHOOK_URL", "")
    try:
        state = load_state(state_path, default_cursor=config.start_date)
        key = state.last_posted_key
        if key is None:
            print("nothing posted yet; nothing to skip")
            return 0
        old = state.completed.get(key, {})
        if old.get("poll_posted"):
            print(
                f"warning: {key} already has polls; they will never be recapped",
                file=sys.stderr,
            )

        old_id, _, iso = key.partition("@")
        chart_date = date.fromisoformat(iso)
        posted_week = old.get("week", week_of_month(today))
        exclude = {
            k.partition("@")[0]
            for k, rec in state.completed.items()
            if k.endswith(f"@{iso}") and isinstance(rec, dict) and rec.get("posted")
        }

        found = next_chart(
            config, chart_date, posted_week, state.wildcard_index, exclude
        )
        jumped = found is None
        if found is None:
            chart_date = state.cursor
            week = week_of_month(today)
            for hop in range(MAX_JUMPS):
                if hop:
                    chart_date = advance(chart_date, config.weeks_per_run)
                chart = select_chart(config, chart_date, week, state.wildcard_index)
                rec = state.completed.get(run_key(chart.id, chart_date))
                if not (isinstance(rec, dict) and rec.get("posted")):
                    break
            else:
                raise ValueError(
                    f"every week from {state.cursor.isoformat()} through "
                    f"{chart_date.isoformat()} is already posted; "
                    "move the cursor with `fiftyfm set-cursor`"
                )
        else:
            chart, week, state.wildcard_index = found

        name = playlist_name(chart.display_name, chart_date)
        if dry_run:
            suffix = " [time-jump]" if jumped else ""
            print(f"[dry-run] skip -> {name} (slot week {week}){suffix}")
            return 0

        if jumped and chart.id == old_id:
            print(
                f"warning: no alternate chart exists at {iso}; posting "
                f"{chart.display_name} again for {chart_date.isoformat()}",
                file=sys.stderr,
            )

        fetched = source.fetch(chart, chart_date)
        songs = fetched.songs[:TOP_N]
        assert spotify is not None
        playlist_url = post_chart(
            state,
            state_path,
            env,
            spotify,
            chart=chart,
            chart_date=chart_date,
            week=week,
            songs=songs,
            notify=notify,
        )
        if jumped:
            state.cursor = advance(chart_date, config.weeks_per_run)
        else:
            state.slot_consumed = week
        save_state(state_path, state)
        print(f"done: {name} -> {playlist_url}")
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level run boundary
        print(f"skip failed: {exc}", file=sys.stderr)
        if webhook:
            notify_failure(webhook, f"fiftyfm skip failed: {exc}")
        return 1
