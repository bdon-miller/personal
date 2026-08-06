from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Mapping

from .chart_source import ChartSource, Song
from .config import TOP_N, Config
from .discord import post_failure, post_poll
from .lastfm import playcounts, rank_by_playcount
from .state import load_state, save_state

OTHER_ANSWER = "Other — reply in thread"
MAX_ANSWER_CHARS = 55
SONG_CHOICES = 9
FAVORITE_QUESTION = "Favorite song of the week?"
LEAST_FAVORITE_QUESTION = "Least favorite song of the week?"


def answer_text(song: Song) -> str:
    """`Title — Artist`, trimmed to Discord's 55-character answer limit."""
    text = f"{song.title} — {song.artist}"
    if len(text) > MAX_ANSWER_CHARS:
        return text[: MAX_ANSWER_CHARS - 1] + "…"
    return text


def poll_answers(songs: list[Song], counts: dict[int, int]) -> list[str]:
    """The nine most-played songs, then the write-in escape hatch."""
    ordered = rank_by_playcount(songs, counts)[:SONG_CHOICES]
    return [answer_text(s) for s in ordered] + [OTHER_ANSWER]


def run_poll(
    config: Config,
    state_path: Path,
    env: Mapping[str, str],
    source: ChartSource,
    dry_run: bool = False,
    playcounts_fn=playcounts,
    post=post_poll,
    notify_failure=post_failure,
) -> int:
    """Post this week's two polls into the thread the chart was announced in."""
    webhook = env.get("DISCORD_WEBHOOK_URL", "")
    try:
        state = load_state(state_path, default_cursor=config.start_date)
        key = state.last_posted_key
        if key is None:
            print("no posted thread yet; nothing to poll")
            return 0
        record = state.completed.get(key, {})
        if record.get("poll_posted"):
            print(f"{key} already polled; nothing to do")
            return 0
        thread_id = record.get("thread_id")
        if not thread_id:
            print(f"{key} has no thread_id (posted before polls existed); skipping")
            return 0

        chart_id, _, iso_date = key.partition("@")
        chart = config.charts[chart_id]
        chart_date = date.fromisoformat(iso_date)
        songs = source.fetch(chart.slug, chart_date)[:TOP_N]
        counts = playcounts_fn(env.get("LASTFM_API_KEY", ""), songs)
        answers = poll_answers(songs, counts)

        if dry_run:
            print(f"[dry-run] polls for {key} in thread {thread_id}")
            for a in answers:
                print(f"  {a}")
            return 0

        message_ids = {
            "favorite": post(
                webhook,
                thread_id=thread_id,
                question=FAVORITE_QUESTION,
                answers=answers,
            ),
            "least_favorite": post(
                webhook,
                thread_id=thread_id,
                question=LEAST_FAVORITE_QUESTION,
                answers=answers,
            ),
        }
        record["poll_message_ids"] = message_ids
        record["poll_posted"] = True
        state.completed[key] = record
        save_state(state_path, state)
        print(f"polls posted for {key} in thread {thread_id}")
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level run boundary
        print(f"poll run failed: {exc}", file=sys.stderr)
        if webhook:
            notify_failure(webhook, f"fiftyfm poll run failed: {exc}")
        return 1
