from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import requests
from bs4 import BeautifulSoup

from .config import ChartDef


class ChartFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Song:
    rank: int
    title: str
    artist: str


@dataclass(frozen=True)
class ChartFetch:
    """A chart's songs plus the date the data actually came from.

    For Billboard that echoes the requested date. For Oricon it is the
    nearest real chart Monday, which is what the post should display -
    publishing a date the chart never had would be wrong.
    """
    songs: list[Song]
    chart_date: date


class ChartSource(Protocol):
    def fetch(self, chart: ChartDef, chart_date: date) -> ChartFetch: ...


_BILLBOARD_URL = "https://www.billboard.com/charts/{slug}/{date}/"


def _squash(text: str) -> str:
    return " ".join(text.split())


def parse_billboard(html: str) -> list[Song]:
    """Pull rank, title and artist out of a billboard.com chart page.

    Reads only those three fields. billboard.py also parsed the last-week /
    peak / weeks columns, and broke the whole fetch when Billboard folded
    them into one cell (by Oct 2026) - we never used them, so don't read them.
    """
    soup = BeautifulSoup(html, "html.parser")
    songs = []
    for row in soup.select("ul.o-chart-results-list-row"):
        rank_el = row.select_one("li span.c-label")
        title_el = row.select_one("#title-of-a-story")
        if rank_el is None or title_el is None:
            continue
        artist_el = title_el.find_next_sibling("span", class_="c-label")
        songs.append(Song(
            int(rank_el.get_text(strip=True)),
            _squash(title_el.get_text()),
            _squash(artist_el.get_text()) if artist_el else "",
        ))
    return songs


class BillboardSource:
    def __init__(self, session=None):
        self._session = session or requests.Session()

    def fetch(self, chart: ChartDef, chart_date: date) -> ChartFetch:
        url = _BILLBOARD_URL.format(slug=chart.slug, date=chart_date.isoformat())
        try:
            resp = self._session.get(url, timeout=30)
            resp.raise_for_status()
            songs = parse_billboard(resp.text)
        except Exception as exc:
            raise ChartFetchError(
                f"failed to fetch {chart.slug} for {chart_date.isoformat()}: {exc}"
            ) from exc
        if not songs:
            raise ChartFetchError(
                f"chart {chart.slug} for {chart_date.isoformat()} came back empty"
            )
        return ChartFetch(songs=songs, chart_date=chart_date)


class RoutingSource:
    """Dispatches each chart to the backend named by `ChartDef.source`."""

    def __init__(self, sources: dict[str, ChartSource]):
        self._sources = sources

    def fetch(self, chart: ChartDef, chart_date: date) -> ChartFetch:
        source = self._sources.get(chart.source)
        if source is None:
            raise ChartFetchError(
                f"chart {chart.id!r} names unknown source {chart.source!r}"
            )
        return source.fetch(chart, chart_date)


def default_source() -> RoutingSource:
    """The router the CLI injects: every backend the app ships with."""
    from .oricon import OriconSource

    return RoutingSource(
        {"billboard": BillboardSource(), "oricon": OriconSource()}
    )
