from datetime import date

import pytest

from fiftyfm.config import load_config
from fiftyfm.schedule import (
    advance,
    is_available,
    next_chart,
    select_chart,
    snap_to_saturday,
    week_of_month,
)

CFG = load_config()


def test_snap_to_saturday():
    assert snap_to_saturday(date(1976, 1, 3)) == date(1976, 1, 3)   # already Sat
    assert snap_to_saturday(date(1976, 1, 4)) == date(1976, 1, 10)  # Sun -> next Sat
    assert snap_to_saturday(date(1976, 1, 9)) == date(1976, 1, 10)  # Fri -> next Sat


def test_week_of_month():
    assert week_of_month(date(2026, 8, 3)) == 1
    assert week_of_month(date(2026, 8, 10)) == 2
    assert week_of_month(date(2026, 8, 24)) == 4
    assert week_of_month(date(2026, 8, 31)) == 5


def test_advance():
    assert advance(date(1976, 1, 3), 3) == date(1976, 1, 24)


def test_is_available_window():
    disco = CFG.charts["disco"]
    assert not is_available(disco, date(1976, 8, 21))
    assert is_available(disco, date(1976, 8, 28))
    assert not is_available(disco, date(2020, 4, 4))  # past available_until


def test_era1_slots_1976():
    cursor = date(1976, 3, 6)
    assert select_chart(CFG, cursor, 1, 0).id == "hot-100"
    assert select_chart(CFG, cursor, 2, 0).id == "soul"      # rock not yet available
    assert select_chart(CFG, cursor, 3, 0).id == "country"   # rap no, soul taken
    # wildcard pool pre-disco: easy-listening only
    assert select_chart(CFG, cursor, 4, 0).id == "easy-listening"
    assert select_chart(CFG, cursor, 4, 1).id == "easy-listening"  # pool of 1 cycles


def test_era1_wildcard_gains_disco():
    cursor = date(1976, 9, 4)
    assert select_chart(CFG, cursor, 4, 0).id == "easy-listening"
    assert select_chart(CFG, cursor, 4, 1).id == "disco"


def test_era2_rock_takes_slot2():
    cursor = date(1981, 4, 4)
    assert select_chart(CFG, cursor, 2, 0).id == "mainstream-rock"
    assert select_chart(CFG, cursor, 3, 0).id == "soul"
    # country falls to the wildcard pool
    pool_ids = {select_chart(CFG, cursor, 4, i).id for i in range(4)}
    assert pool_ids == {"country", "easy-listening", "disco"}


def test_era3_rap_takes_slot3():
    cursor = date(1989, 4, 1)
    assert select_chart(CFG, cursor, 2, 0).id == "mainstream-rock"
    assert select_chart(CFG, cursor, 3, 0).id == "rap"


def test_select_chart_no_charts_available():
    cursor = date(1950, 1, 7)
    with pytest.raises(ValueError):
        select_chart(CFG, cursor, 1, 0)


def test_next_chart_forward_from_slot_1():
    chart, week, wi = next_chart(CFG, date(1976, 3, 6), 1, 0, {"hot-100"})
    assert (chart.id, week, wi) == ("soul", 2, 0)


def test_next_chart_skips_an_excluded_slot():
    chart, week, wi = next_chart(CFG, date(1976, 3, 6), 1, 0, {"hot-100", "soul"})
    assert (chart.id, week, wi) == ("country", 3, 0)


def test_next_chart_from_last_slot_falls_to_the_wildcard_pool():
    chart, week, wi = next_chart(CFG, date(1976, 3, 6), 3, 0, {"country"})
    assert (chart.id, week, wi) == ("easy-listening", 4, 0)


def test_next_chart_walks_the_wildcard_pool():
    # Sep 1976: pool is [easy-listening, disco]. Skipping a wildcard week
    # must advance the index, since week+1 alone would return the same chart.
    chart, week, wi = next_chart(CFG, date(1976, 9, 4), 4, 0, {"easy-listening"})
    assert (chart.id, week, wi) == ("disco", 4, 1)


def test_next_chart_returns_none_when_the_pool_of_one_is_exhausted():
    # Pre-disco the pool is [easy-listening] alone, so a wildcard week has
    # no alternate at all. None is the signal to time-jump.
    assert next_chart(CFG, date(1976, 3, 6), 4, 0, {"easy-listening"}) is None


def test_next_chart_returns_none_when_everything_is_excluded():
    excluded = {"hot-100", "soul", "country", "easy-listening"}
    assert next_chart(CFG, date(1976, 3, 6), 1, 0, excluded) is None


def test_next_chart_availability_uses_chart_date_not_a_later_cursor():
    # Disco is unavailable until 1976-08-28. It must not be offered for a
    # March chart date even though the caller's cursor is weeks ahead.
    assert next_chart(
        CFG, date(1976, 3, 6), 3, 1, {"country", "easy-listening"}
    ) is None


def test_next_chart_returns_none_when_no_chart_is_available_at_all():
    # Before 1958-08-04 (hot-100's own available_from) nothing in the config
    # is available yet, so select_chart raises ValueError on the very first
    # wildcard-pool probe. next_chart must turn that into None, not a raise -
    # exhaustion is the signal to time-jump, same as a plain excluded pool.
    assert next_chart(CFG, date(1958, 1, 1), 4, 0, set()) is None


def test_next_chart_is_forward_only():
    # Slot 1 and 2 charts must NOT be offered when skipping slot 3, even
    # though they are available and unexcluded at this date.
    chart, week, _wi = next_chart(CFG, date(1976, 3, 6), 3, 0, {"country"})
    assert chart.id not in ("hot-100", "soul")
    assert week == 4
