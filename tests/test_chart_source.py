from datetime import date

import pytest

import fiftyfm.chart_source as cs
from fiftyfm.config import ChartDef

HOT100 = ChartDef(
    id="hot-100", slug="hot-100", display_name="Hot 100",
    available_from=date(1958, 8, 4),
)


class FakeEntry:
    def __init__(self, rank, title, artist):
        self.rank, self.title, self.artist = rank, title, artist


def test_fetch_maps_entries(monkeypatch):
    def fake_chart_data(slug, date=None, timeout=None):
        assert slug == "hot-100"
        assert date == "1976-03-06"
        return [FakeEntry(1, "December, 1963 (Oh, What A Night)", "Four Seasons"),
                FakeEntry(2, "All By Myself", "Eric Carmen")]

    monkeypatch.setattr(cs.billboard, "ChartData", fake_chart_data)
    got = cs.BillboardSource().fetch(HOT100, date(1976, 3, 6))
    assert got.songs[0] == cs.Song(1, "December, 1963 (Oh, What A Night)", "Four Seasons")
    assert len(got.songs) == 2


def test_fetch_echoes_requested_date(monkeypatch):
    monkeypatch.setattr(
        cs.billboard, "ChartData",
        lambda *a, **k: [FakeEntry(1, "T", "A")],
    )
    got = cs.BillboardSource().fetch(HOT100, date(1976, 3, 6))
    assert got.chart_date == date(1976, 3, 6)


def test_fetch_empty_chart_raises(monkeypatch):
    monkeypatch.setattr(cs.billboard, "ChartData", lambda *a, **k: [])
    with pytest.raises(cs.ChartFetchError):
        cs.BillboardSource().fetch(HOT100, date(1976, 3, 6))


def test_fetch_wraps_exceptions(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("billboard.com unreachable")

    monkeypatch.setattr(cs.billboard, "ChartData", boom)
    with pytest.raises(cs.ChartFetchError):
        cs.BillboardSource().fetch(HOT100, date(1976, 3, 6))
