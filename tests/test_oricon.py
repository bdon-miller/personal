from datetime import date

import pytest

from fiftyfm.chart_source import ChartFetchError, Song
from fiftyfm.config import ChartDef
from fiftyfm.oricon import OriconSource, load_oricon

SHOWA = ChartDef(
    id="oricon-showa", slug="oricon-showa",
    display_name="Oricon Weekly Singles (Shōwa)",
    available_from=date(1976, 1, 12), available_until=date(1989, 1, 2),
    source="oricon", publisher="Oricon", strict_match=True,
)

CSV = """chart_date,chart_year,rank,title,artist
1976-01-12,1976,1,およげ！たいやきくん,子門真人
1976-01-12,1976,2,あの日にかえりたい,荒井由実
1976-01-19,1976,1,およげ！たいやきくん,子門真人
"""


def test_load_orders_by_rank():
    charts = load_oricon(CSV)
    assert list(charts) == [date(1976, 1, 12), date(1976, 1, 19)]
    assert charts[date(1976, 1, 12)] == [
        Song(1, "およげ！たいやきくん", "子門真人"),
        Song(2, "あの日にかえりたい", "荒井由実"),
    ]


def test_load_drops_blank_artist():
    charts = load_oricon(
        "chart_date,chart_year,rank,title,artist\n"
        "2000-08-28,2000,9,あ～よかった（setagaya mix）,\n"
        "2000-08-28,2000,10,Real,DA PUMP\n"
    )
    assert [s.rank for s in charts[date(2000, 8, 28)]] == [10]


def test_load_dedupes_colliding_ranks():
    # 1980-08-18 in the real data holds two merged chart weeks.
    charts = load_oricon(
        "chart_date,chart_year,rank,title,artist\n"
        "1980-08-18,1980,1,異邦人,久保田早紀\n"
        "1980-08-18,1980,1,順子,長渕剛\n"
    )
    assert charts[date(1980, 8, 18)] == [Song(1, "異邦人", "久保田早紀")]


def test_fetch_exact_date():
    src = OriconSource(load_oricon(CSV))
    got = src.fetch(SHOWA, date(1976, 1, 12))
    assert got.chart_date == date(1976, 1, 12)
    assert got.songs[0].title == "およげ！たいやきくん"


def test_fetch_maps_saturday_to_nearest_monday():
    src = OriconSource(load_oricon(CSV))
    # 1976-01-17 is a Saturday: 5 days after the 12th, 2 before the 19th.
    assert src.fetch(SHOWA, date(1976, 1, 17)).chart_date == date(1976, 1, 19)


def test_fetch_ties_break_earlier():
    charts = load_oricon(
        "chart_date,chart_year,rank,title,artist\n"
        "1976-01-12,1976,1,A,X\n"
        "1976-01-26,1976,1,B,Y\n"
    )
    # 1976-01-19 sits exactly 7 days from both.
    assert OriconSource(charts).fetch(SHOWA, date(1976, 1, 19)).chart_date == date(1976, 1, 12)


def test_fetch_crosses_new_year_gap():
    charts = load_oricon(
        "chart_date,chart_year,rank,title,artist\n"
        "1979-12-31,1979,1,A,X\n"
        "1980-01-21,1980,1,B,Y\n"
    )
    # The app's start_date maps 9 days out; tolerance must allow it.
    got = OriconSource(charts).fetch(SHOWA, date(1980, 1, 12))
    assert got.chart_date == date(1980, 1, 21)


def test_fetch_outside_tolerance_raises():
    src = OriconSource(load_oricon(CSV))
    with pytest.raises(ChartFetchError):
        src.fetch(SHOWA, date(1990, 6, 2))


def test_packaged_csv_loads():
    src = OriconSource()
    got = src.fetch(SHOWA, date(1976, 1, 3))
    # start_date is 9 days before coverage opens on the 12th.
    assert got.chart_date == date(1976, 1, 12)
    assert len(got.songs) == 20
    assert got.songs[0] == Song(1, "およげ！たいやきくん", "子門真人")


def test_packaged_csv_heisei_depth():
    src = OriconSource()
    got = src.fetch(SHOWA, date(1995, 6, 3))
    assert len(got.songs) == 30
