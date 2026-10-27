"""Billboard charts from the archive shipped in-package.

The archive is the app's first source for every Billboard chart: Hot 100
from mhollingshead/billboard-hot-100, the genre charts from
pdp2600/chartscraper and the American Country Countdown wiki, and the rest
fetched from billboard.com. Rebuild it with scripts/build_billboard_archive.py.
"""
from __future__ import annotations

import csv
import gzip
import io
from datetime import date
from importlib import resources

from .chart_source import ChartFetch, ChartFetchError, Song, nearest_date
from .config import ChartDef

# The archive dates soul charts on Monday until 1978-11-06 and on Saturday
# after, while the cursor is always a Saturday: a Monday chart sits 2 days
# after its cursor week. Three leaves one day of margin.
TOLERANCE_DAYS = 3

_DATA = "data/billboard_archive.csv.gz"


def load_archive(text: str) -> dict[str, dict[date, list[Song]]]:
    """Parse archive CSV text into {slug: {chart_date: [Song, ...]}} by rank."""
    charts: dict[str, dict[date, list[Song]]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        weeks = charts.setdefault(row["chart"], {})
        weeks.setdefault(date.fromisoformat(row["chart_date"]), []).append(
            Song(int(row["rank"]), row["title"], row["artist"])
        )
    for weeks in charts.values():
        for songs in weeks.values():
            songs.sort(key=lambda s: s.rank)
    return charts


def _packaged_text() -> str:
    raw = (resources.files("fiftyfm") / _DATA).read_bytes()
    return gzip.decompress(raw).decode("utf-8")


class BillboardArchiveSource:
    """Serves Billboard charts from the archive shipped in-package.

    A requested date resolves to the nearest chart date in the archive, and
    the post shows that real date, as with Oricon.
    """

    def __init__(self, charts: dict[str, dict[date, list[Song]]] | None = None):
        self._charts = charts
        self._dates: dict[str, list[date]] = {}

    def _data(self) -> dict[str, dict[date, list[Song]]]:
        if self._charts is None:
            self._charts = load_archive(_packaged_text())
        return self._charts

    def fetch(self, chart: ChartDef, chart_date: date) -> ChartFetch:
        weeks = self._data().get(chart.slug)
        if weeks is None:
            raise ChartFetchError(f"billboard archive has no chart {chart.slug!r}")
        if chart.slug not in self._dates:
            self._dates[chart.slug] = sorted(weeks)
        actual = nearest_date(self._dates[chart.slug], chart_date, TOLERANCE_DAYS)
        if actual is None:
            raise ChartFetchError(
                f"no {chart.slug} chart in the billboard archive within "
                f"{TOLERANCE_DAYS} days of {chart_date.isoformat()}"
            )
        return ChartFetch(songs=weeks[actual], chart_date=actual)
