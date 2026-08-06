from __future__ import annotations

import bisect
import csv
import io
import sys
from datetime import date, timedelta
from importlib import resources

from .chart_source import ChartFetch, ChartFetchError, Song
from .config import ChartDef

# The widest gap between a cursor Saturday and a real Oricon Monday across
# the whole dataset is 9 days, at 1980-01-12 (a 21-day New Year gap) and at
# 1976-01-03 (the app's own start_date, since coverage opens on the 12th).
# Ten leaves one day of margin. Re-measure before changing it.
TOLERANCE_DAYS = 10

_DATA = "data/oricon_singles.csv"


def load_oricon(text: str) -> dict[date, list[Song]]:
    """Parse Oricon CSV text into {chart_date: [Song, ...]} ordered by rank.

    Rows with a blank title or artist are dropped - they can only produce a
    Spotify miss or a wrong match. Where two rows claim the same rank on the
    same date the first wins, which happens once in the shipped data at
    1980-08-18, where two chart weeks were merged into one date.
    """
    charts: dict[date, dict[int, Song]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        title = (row["title"] or "").strip()
        artist = (row["artist"] or "").strip()
        if not title or not artist:
            continue
        d = date.fromisoformat(row["chart_date"])
        rank = int(row["rank"])
        ranks = charts.setdefault(d, {})
        if rank in ranks:
            print(
                f"oricon: duplicate rank {rank} on {d.isoformat()}; "
                f"keeping {ranks[rank].title!r}, dropping {title!r}",
                file=sys.stderr,
            )
            continue
        ranks[rank] = Song(rank, title, artist)
    return {
        d: [ranks[r] for r in sorted(ranks)]
        for d, ranks in sorted(charts.items())
    }


def _packaged_text() -> str:
    return (resources.files("fiftyfm") / _DATA).read_text(encoding="utf-8")


class OriconSource:
    """Serves Oricon weekly singles from the CSV shipped in-package.

    Oricon charts are dated Monday while the app's cursor is a Saturday, so
    a requested date resolves to the nearest Monday present in the data.
    """

    def __init__(self, charts: dict[date, list[Song]] | None = None):
        self._charts = charts
        self._dates: list[date] | None = None

    def _data(self) -> dict[date, list[Song]]:
        if self._charts is None:
            self._charts = load_oricon(_packaged_text())
        return self._charts

    def _keys(self) -> list[date]:
        if self._dates is None:
            self._dates = sorted(self._data())
        return self._dates

    def _nearest(self, wanted: date) -> date | None:
        """The closest chart date to `wanted`, ties going to the earlier."""
        dates = self._keys()
        if not dates:
            return None
        i = bisect.bisect_left(dates, wanted)
        best: date | None = None
        best_delta: timedelta | None = None
        for j in (i - 1, i):
            if 0 <= j < len(dates):
                delta = abs(dates[j] - wanted)
                if best_delta is None or delta < best_delta:
                    best, best_delta = dates[j], delta
        if best_delta is None or best_delta.days > TOLERANCE_DAYS:
            return None
        return best

    def fetch(self, chart: ChartDef, chart_date: date) -> ChartFetch:
        actual = self._nearest(chart_date)
        if actual is None:
            raise ChartFetchError(
                f"no oricon chart within {TOLERANCE_DAYS} days of "
                f"{chart_date.isoformat()}"
            )
        songs = self._data()[actual]
        if not songs:
            raise ChartFetchError(
                f"oricon chart {actual.isoformat()} came back empty"
            )
        return ChartFetch(songs=songs, chart_date=actual)
