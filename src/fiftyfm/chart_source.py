from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import billboard


class ChartFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Song:
    rank: int
    title: str
    artist: str


class ChartSource(Protocol):
    def fetch(self, slug: str, chart_date: date) -> list[Song]: ...


class BillboardSource:
    def fetch(self, slug: str, chart_date: date) -> list[Song]:
        try:
            chart = billboard.ChartData(
                slug, date=chart_date.isoformat(), timeout=30
            )
        except Exception as exc:
            raise ChartFetchError(
                f"failed to fetch {slug} for {chart_date.isoformat()}: {exc}"
            ) from exc
        songs = [Song(e.rank, e.title, e.artist) for e in chart]
        if not songs:
            raise ChartFetchError(
                f"chart {slug} for {chart_date.isoformat()} came back empty"
            )
        return songs
