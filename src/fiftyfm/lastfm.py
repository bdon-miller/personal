from __future__ import annotations

import sys

import requests

from .chart_source import Song

LASTFM_API = "https://ws.audioscrobbler.com/2.0/"


def playcounts(
    api_key: str | None,
    songs: list[Song],
    session: requests.Session | None = None,
) -> dict[int, int]:
    """Map each song's chart rank to its global Last.fm playcount.

    Lookups that fail for any reason are omitted rather than raised: the
    ballot must still go out when Last.fm is unhelpful.
    """
    if not api_key:
        return {}
    session = session or requests.Session()
    counts: dict[int, int] = {}
    for song in songs:
        try:
            resp = session.get(
                LASTFM_API,
                params={
                    "method": "track.getinfo",
                    "api_key": api_key,
                    "artist": song.artist,
                    "track": song.title,
                    "autocorrect": 1,
                    "format": "json",
                },
                timeout=30,
            )
            if resp.status_code != 200:
                print(
                    f"last.fm miss ({resp.status_code}): "
                    f"{song.title} — {song.artist}",
                    file=sys.stderr,
                )
                continue
            counts[song.rank] = int(resp.json()["track"]["playcount"])
        except Exception as exc:  # noqa: BLE001 - never fatal
            print(
                f"last.fm lookup failed for {song.title} — {song.artist}: {exc}",
                file=sys.stderr,
            )
    return counts


def rank_by_playcount(songs: list[Song], counts: dict[int, int]) -> list[Song]:
    """Songs by descending playcount, ties broken by ascending chart rank.

    An empty `counts` therefore yields plain chart order, which is the
    intended fallback when Last.fm is unavailable.
    """
    return sorted(songs, key=lambda s: (-counts.get(s.rank, 0), s.rank))


def rank_by_least_played(songs: list[Song], counts: dict[int, int]) -> list[Song]:
    """Songs by ascending playcount, ties broken by ascending chart rank.

    A song Last.fm knows nothing about counts as zero plays and so sorts
    first, which matches the intent: an untraceable track is an obscure
    one. An empty `counts` therefore yields plain chart order, the same
    fallback as `rank_by_playcount`.
    """
    return sorted(songs, key=lambda s: (counts.get(s.rank, 0), s.rank))
