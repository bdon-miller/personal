from __future__ import annotations

from datetime import date, timedelta

from .config import ChartDef, Config

SATURDAY = 5  # date.weekday(): Monday=0


def snap_to_saturday(d: date) -> date:
    return d + timedelta(days=(SATURDAY - d.weekday()) % 7)


def week_of_month(d: date) -> int:
    return (d.day - 1) // 7 + 1


def advance(cursor: date, weeks: int) -> date:
    return cursor + timedelta(weeks=weeks)


def is_available(chart: ChartDef, cursor: date) -> bool:
    if cursor < chart.available_from:
        return False
    if chart.available_until is not None and cursor > chart.available_until:
        return False
    return True


def select_chart(
    config: Config, cursor: date, week: int, wildcard_index: int
) -> ChartDef:
    available = [c for c in config.charts.values() if is_available(c, cursor)]
    if not available:
        raise ValueError(f"no charts available at cursor {cursor.isoformat()}")
    available_ids = {c.id for c in available}

    taken: list[str] = []
    for slot_num, priority in enumerate(config.slots, start=1):
        pick = next(
            (cid for cid in priority
             if cid in available_ids and cid not in taken),
            None,
        )
        if pick is not None:
            taken.append(pick)
        if slot_num == week:
            if pick is None:
                raise ValueError(
                    f"no chart available for slot {week} at {cursor.isoformat()}"
                )
            return config.charts[pick]

    pool = [c for c in available if c.id not in taken]
    if not pool:
        raise ValueError(f"wildcard pool empty at cursor {cursor.isoformat()}")
    return pool[wildcard_index % len(pool)]
