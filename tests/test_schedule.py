from datetime import date

import pytest

from fiftyfm.config import load_config
from fiftyfm.schedule import (
    advance,
    is_available,
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
