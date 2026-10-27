from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date, timedelta
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


def nearest_date(dates: list[date], wanted: date, tolerance_days: int) -> date | None:
    """The closest of sorted `dates` to `wanted`, ties going to the earlier.

    None when nothing lies within `tolerance_days`.
    """
    i = bisect.bisect_left(dates, wanted)
    best: date | None = None
    best_delta: timedelta | None = None
    for j in (i - 1, i):
        if 0 <= j < len(dates):
            delta = abs(dates[j] - wanted)
            if best_delta is None or delta < best_delta:
                best, best_delta = dates[j], delta
    if best_delta is None or best_delta.days > tolerance_days:
        return None
    return best


_BILLBOARD_URL = "https://www.billboard.com/charts/{slug}/{date}/"


def _squash(text: str) -> str:
    return " ".join(text.split())


def parse_billboard(html: str) -> list[Song]:
    """Pull rank, title and artist out of a billboard.com chart page.

    Reads only those three fields. billboard.py also parsed the last-week /
    peak / weeks columns, and broke the whole fetch when Billboard folded
    them into one cell (by Oct 2026) - we never used them, so don't read them.

    Understands the current layout and the two before it, which Wayback
    Machine copies of the site still use: `chart-list-item` (2019-2021) and
    `chart-row` (2018 and earlier).
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
    if songs:
        return songs
    for row in soup.select("div.chart-list-item[data-rank]"):
        songs.append(Song(
            int(row["data-rank"]),
            _squash(row.get("data-title", "")),
            _squash(row.get("data-artist", "")),
        ))
    if songs:
        return songs
    for row in soup.select("article.chart-row"):
        rank_el = row.select_one(".chart-row__current-week")
        title_el = row.select_one(".chart-row__song")
        artist_el = row.select_one(".chart-row__artist")
        if rank_el is None or title_el is None:
            continue
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
            # On 2026-10-26 billboard.com served chart pages with empty chart
            # sections for hours, so no rows means the site, not the chart.
            raise ChartFetchError(
                f"billboard.com page for {chart.slug} {chart_date.isoformat()} "
                "has no chart rows - the site is down or its layout changed"
            )
        return ChartFetch(songs=songs, chart_date=chart_date)


_WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
_WAYBACK_PAGE = "https://web.archive.org/web/{ts}id_/{url}"
# Copies saved from 2026-10-26 on may be of billboard.com's empty outage
# pages, so only earlier ones are read.
WAYBACK_BEFORE = "20261025"


class WaybackSource:
    """Reads a billboard.com chart page from the Wayback Machine.

    Tries the newest few copies saved before WAYBACK_BEFORE, newest first.
    """

    def __init__(self, session=None, attempts: int = 3):
        self._session = session or requests.Session()
        self._attempts = attempts

    def fetch(self, chart: ChartDef, chart_date: date) -> ChartFetch:
        url = _BILLBOARD_URL.format(slug=chart.slug, date=chart_date.isoformat())
        try:
            resp = self._session.get(_WAYBACK_CDX, timeout=60, params={
                "url": url, "output": "json", "fl": "timestamp",
                "filter": "statuscode:200", "to": WAYBACK_BEFORE,
            })
            resp.raise_for_status()
            stamps = [row[0] for row in resp.json()[1:]]
        except Exception as exc:
            raise ChartFetchError(f"wayback lookup failed for {url}: {exc}") from exc
        for ts in sorted(stamps, reverse=True)[:self._attempts]:
            try:
                page = self._session.get(_WAYBACK_PAGE.format(ts=ts, url=url), timeout=60)
                page.raise_for_status()
            except Exception:
                continue
            songs = parse_billboard(page.text)
            if songs:
                return ChartFetch(songs=songs, chart_date=chart_date)
        raise ChartFetchError(f"no readable wayback copy of {url}")


class FallbackSource:
    """Tries each source in turn and returns the first chart found."""

    def __init__(self, sources: list[ChartSource]):
        self._sources = sources

    def fetch(self, chart: ChartDef, chart_date: date) -> ChartFetch:
        errors = []
        for source in self._sources:
            try:
                return source.fetch(chart, chart_date)
            except ChartFetchError as exc:
                errors.append(str(exc))
        raise ChartFetchError("; ".join(errors))


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
    """The router the CLI injects: every backend the app ships with.

    Billboard charts come from the in-package archive first; only a week
    missing from it is read from billboard.com, then the Wayback Machine.
    """
    from .billboard_archive import BillboardArchiveSource
    from .oricon import OriconSource

    session = requests.Session()
    return RoutingSource({
        "billboard": FallbackSource([
            BillboardArchiveSource(),
            BillboardSource(session),
            WaybackSource(session),
        ]),
        "oricon": OriconSource(),
    })
