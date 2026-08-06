from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import billboard

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


class BillboardSource:
    def fetch(self, chart: ChartDef, chart_date: date) -> ChartFetch:
        try:
            data = billboard.ChartData(
                chart.slug, date=chart_date.isoformat(), timeout=30
            )
        except Exception as exc:
            raise ChartFetchError(
                f"failed to fetch {chart.slug} for {chart_date.isoformat()}: {exc}"
            ) from exc
        songs = [Song(e.rank, e.title, e.artist) for e in data]
        if not songs:
            raise ChartFetchError(
                f"chart {chart.slug} for {chart_date.isoformat()} came back empty"
            )
        return ChartFetch(songs=songs, chart_date=chart_date)
