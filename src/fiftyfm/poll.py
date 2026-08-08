from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Mapping

from .chart_source import ChartSource, Song
from .config import TOP_N, Config
from .discord import delete_message, get_poll_results, post_failure, post_poll
from .lastfm import playcounts, rank_by_least_played, rank_by_playcount
from .state import load_state, save_state

OTHER_ANSWER = "Other — reply in thread"
MAX_ANSWER_CHARS = 55
SONG_CHOICES = 9
FAVORITE_QUESTION = "Favorite song of the week?"
LEAST_FAVORITE_QUESTION = "Least favorite song of the week?"
CLOSE_WEEKDAY = 0  # Monday, per date.weekday()
CLOSE_HOUR = 8  # an hour before the Monday run reads the results


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


def least_favorite_answers(songs: list[Song], counts: dict[int, int]) -> list[str]:
    """The nine least-played songs, least played first, then the write-in.

    The least-favorite ballot deliberately draws from the other end of the
    chart's playcount spread, so it asks about the week's obscurities
    rather than re-running the favorite poll's shortlist.
    """
    ordered = rank_by_least_played(songs, counts)[:SONG_CHOICES]
    return [answer_text(s) for s in ordered] + [OTHER_ANSWER]


def hours_until_close(now: datetime) -> int:
    """Whole hours from `now` to the next Monday 08:00, at least one.

    Discord takes a poll's lifetime in whole hours, so this floors: a
    replacement poll closes a little early rather than a little late, and
    the Monday 09:00 recap only reports polls Discord has finalized.
    """
    close = (now + timedelta(days=(CLOSE_WEEKDAY - now.weekday()) % 7)).replace(
        hour=CLOSE_HOUR, minute=0, second=0, microsecond=0
    )
    if close <= now:
        close += timedelta(days=7)
    return max(1, int((close - now).total_seconds() // 3600))


def _chart_songs(
    config: Config, source: ChartSource, key: str
) -> list[Song] | None:
    """The top-40 behind a run key, or None after printing why not."""
    chart_id, _, iso_date = key.partition("@")
    chart = config.charts.get(chart_id)
    if chart is None:
        print(f"{key} chart is no longer configured; nothing to poll")
        return None
    songs = source.fetch(chart, date.fromisoformat(iso_date)).songs[:TOP_N]
    if not songs:
        print(f"{key} chart came back empty; nothing to poll")
        return None
    return songs


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

        songs = _chart_songs(config, source, key)
        if songs is None:
            return 0
        counts = playcounts_fn(env.get("LASTFM_API_KEY", ""), songs)
        answers = poll_answers(songs, counts)
        least_answers = least_favorite_answers(songs, counts)

        if dry_run:
            print(f"[dry-run] polls for {key} in thread {thread_id}")
            for question, options in (
                (FAVORITE_QUESTION, answers),
                (LEAST_FAVORITE_QUESTION, least_answers),
            ):
                print(f"  {question}")
                for a in options:
                    print(f"    {a}")
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
                answers=least_answers,
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


def repoll_least_favorite(
    config: Config,
    state_path: Path,
    env: Mapping[str, str],
    source: ChartSource,
    now: datetime,
    dry_run: bool = False,
    playcounts_fn=playcounts,
    post=post_poll,
    delete=delete_message,
    notify_failure=post_failure,
) -> int:
    """Replace this week's least-favorite poll with a freshly built ballot.

    Discord cannot edit a poll, so this posts a replacement and deletes the
    original - votes already cast on it are lost. The new poll is recorded
    in state before the delete is attempted, so a failure there leaves a
    stale poll to remove by hand rather than a recap pointing at nothing.
    """
    webhook = env.get("DISCORD_WEBHOOK_URL", "")
    try:
        state = load_state(state_path, default_cursor=config.start_date)
        key = state.last_posted_key
        if key is None:
            print("no posted thread yet; nothing to repoll")
            return 0
        record = state.completed.get(key, {})
        if not record.get("poll_posted"):
            print(f"{key} has no polls yet; run `fiftyfm poll` instead")
            return 0
        thread_id = record.get("thread_id")
        ids = dict(record.get("poll_message_ids") or {})
        old_id = ids.get("least_favorite")
        if not thread_id or not old_id:
            print(f"{key} has no least-favorite poll to replace; skipping")
            return 0

        songs = _chart_songs(config, source, key)
        if songs is None:
            return 0
        counts = playcounts_fn(env.get("LASTFM_API_KEY", ""), songs)
        answers = least_favorite_answers(songs, counts)
        duration = hours_until_close(now)

        if dry_run:
            print(
                f"[dry-run] replace poll {old_id} in thread {thread_id}, "
                f"closing in {duration}h"
            )
            print(f"  {LEAST_FAVORITE_QUESTION}")
            for a in answers:
                print(f"    {a}")
            return 0

        ids["least_favorite"] = post(
            webhook,
            thread_id=thread_id,
            question=LEAST_FAVORITE_QUESTION,
            answers=answers,
            duration=duration,
        )
        record["poll_message_ids"] = ids
        state.completed[key] = record
        save_state(state_path, state)
        try:
            delete(webhook, thread_id=thread_id, message_id=old_id)
        except Exception as exc:  # noqa: BLE001 - the replacement is already live
            print(
                f"replacement posted, but poll {old_id} could not be deleted: "
                f"{exc}; remove it by hand",
                file=sys.stderr,
            )
        print(
            f"least-favorite poll replaced for {key} in thread {thread_id} "
            f"(closes in {duration}h)"
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level run boundary
        print(f"repoll run failed: {exc}", file=sys.stderr)
        if webhook:
            notify_failure(webhook, f"fiftyfm repoll run failed: {exc}")
        return 1


def _top(counts: dict[str, int]) -> tuple[str, int] | None:
    """The most-picked answer, or None if nothing was picked.

    `max` returns the first maximum, and dict order follows the poll's
    answer order, so ties resolve to the higher-placed answer.
    """
    if not counts or max(counts.values()) == 0:
        return None
    return max(counts.items(), key=lambda kv: kv[1])


def recap_text(
    favorite: dict[str, int], least: dict[str, int]
) -> str | None:
    """One line summarising last week's two polls, or None if unreportable."""
    parts = []
    for label, counts in (
        ("Favorite", favorite),
        ("Least favorite", least),
    ):
        top = _top(counts)
        if top is not None:
            answer, n = top
            plural = "vote" if n == 1 else "votes"
            parts.append(f"**{label}:** {answer} ({n} {plural})")
    if not parts:
        return None
    return "**Last week's results** — " + " · ".join(parts)


def build_recap(
    state,
    webhook_url: str,
    fetch_results=get_poll_results,
) -> str | None:
    """Summarise the previous week's polls; None if not safely reportable.

    Counts are only trusted once Discord marks the poll finalized, so a
    poll still open reports nothing rather than half the votes.
    """
    key = state.last_posted_key
    if key is None:
        return None
    record = state.completed.get(key, {})
    thread_id = record.get("thread_id")
    ids = record.get("poll_message_ids") or {}
    if not thread_id or not ids.get("favorite") or not ids.get("least_favorite"):
        print(f"{key} has no thread_id or poll_message_ids; skipping recap",
              file=sys.stderr)
        return None
    try:
        favorite, fav_done = fetch_results(
            webhook_url, thread_id=thread_id, message_id=ids["favorite"]
        )
        least, least_done = fetch_results(
            webhook_url, thread_id=thread_id, message_id=ids["least_favorite"]
        )
    except Exception as exc:  # noqa: BLE001 - a recap is never worth failing over
        print(f"could not read last week's polls: {exc}", file=sys.stderr)
        return None
    if not (fav_done and least_done):
        print(f"polls for {key} are not finalized yet; skipping recap")
        return None
    return recap_text(favorite, least)
