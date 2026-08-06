from __future__ import annotations

from .chart_source import Song
from .lastfm import rank_by_playcount

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
