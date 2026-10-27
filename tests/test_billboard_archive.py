from datetime import date, timedelta

import pytest

from fiftyfm.billboard_archive import BillboardArchiveSource, load_archive
from fiftyfm.chart_source import ChartFetchError, Song
from fiftyfm.config import ChartDef, load_config

SOUL = ChartDef(
    id="soul", slug="r-b-hip-hop-songs", display_name="Hot Soul Singles",
    available_from=date(1958, 10, 20), 
)

CSV = """chart,chart_date,rank,title,artist
r-b-hip-hop-songs,1977-02-14,2,Tear Drops,Booker T.
r-b-hip-hop-songs,1977-02-14,1,I Wish,Stevie Wonder
r-b-hip-hop-songs,1977-02-21,1,Don't Leave Me This Way,Thelma Houston
latin-songs,1986-09-20,1,Rayito De Luna,Chayanne
"""


def test_load_archive_groups_by_chart_and_date_in_rank_order():
    charts = load_archive(CSV)
    assert set(charts) == {"r-b-hip-hop-songs", "latin-songs"}
    assert [s.rank for s in charts["r-b-hip-hop-songs"][date(1977, 2, 14)]] == [1, 2]


def test_archive_resolves_a_saturday_to_the_monday_chart_and_shows_its_date():
    got = BillboardArchiveSource(load_archive(CSV)).fetch(SOUL, date(1977, 2, 12))
    assert got.chart_date == date(1977, 2, 14)
    assert got.songs[0] == Song(1, "I Wish", "Stevie Wonder")


def test_packaged_country_matches_billboards_1977_number_ones():
    # Spot-check against Billboard's Hot Country Singles #1s, which the
    # American Country Countdown wiki was transcribed from.
    source = BillboardArchiveSource()
    country = load_config().charts["country"]
    for d, title in [
        (date(1977, 2, 12), "Near You"),
        (date(1977, 2, 19), "Moody Blue"),
        (date(1977, 3, 19), "Southern Nights"),
    ]:
        assert source.fetch(country, d).songs[0].title == title


def test_packaged_country_fills_a_year_end_special_week():
    # 1977-12-31 aired the Top 100 of 1977, not a weekly chart, so that
    # week comes from billboard.com rather than the wiki.
    got = BillboardArchiveSource().fetch(
        load_config().charts["country"], date(1977, 12, 31)
    )
    assert got.chart_date == date(1977, 12, 31)
    assert len(got.songs) == 40


def test_archive_outside_tolerance_raises():
    source = BillboardArchiveSource(load_archive(CSV))
    with pytest.raises(ChartFetchError, match="within 3 days"):
        source.fetch(SOUL, date(1977, 3, 5))


def test_archive_unknown_chart_raises():
    pop = ChartDef(
        id="pop", slug="pop-songs", display_name="Mainstream Top 40",
        available_from=date(1992, 10, 3), source="billboard-archive",
    )
    with pytest.raises(ChartFetchError, match="pop-songs"):
        BillboardArchiveSource(load_archive(CSV)).fetch(pop, date(1992, 10, 3))


# Weeks neither billboard.com nor the Wayback Machine could serve when the
# archive was filled on 2026-10-26; the app falls back to both live.
KNOWN_GAPS = [
    ("rap", "2026-04-04"),
    ("hot-rock", "2019-01-05"),
    ("hot-rock", "2019-07-06"),
    ("hot-rock", "2019-07-13"),
    ("hot-rock", "2020-07-18"),
    ("hot-rock", "2020-07-25"),
    ("hot-rock", "2020-08-01"),
    ("hot-rock", "2023-11-04"),
    ("hot-rock", "2026-03-21"),
    ("adult-top-40", "2026-10-24"),
]


def test_packaged_archive_covers_every_week_the_schedule_can_reach():
    """Every Saturday a Billboard chart is available from the schedule's
    start to the archive's last fill resolves in the archive itself, so
    the app rarely needs billboard.com for a week in that range."""
    config = load_config()
    source = BillboardArchiveSource()
    last = date(2026, 10, 24)  # the week the archive was last filled to
    missing = []
    for chart in config.charts.values():
        if chart.publisher != "Billboard":
            continue
        cursor = max(config.start_date, chart.available_from)
        cursor += timedelta(days=(5 - cursor.weekday()) % 7)
        end = min(chart.available_until or last, last)
        while cursor <= end:
            try:
                source.fetch(chart, cursor)
            except ChartFetchError:
                missing.append((chart.id, cursor.isoformat()))
            cursor += timedelta(weeks=1)
    assert sorted(missing) == sorted(KNOWN_GAPS)
