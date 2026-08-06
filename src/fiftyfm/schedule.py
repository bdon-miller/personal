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


def next_chart(
    config: Config,
    chart_date: date,
    posted_week: int,
    wildcard_index: int,
    exclude_ids: set[str],
) -> tuple[ChartDef, int, int] | None:
    """The next candidate after `posted_week`, forward-only.

    Walks the fixed slots after `posted_week`, then the wildcard pool from
    `wildcard_index` upward, and returns the first chart whose id is not in
    `exclude_ids` as (chart, week, wildcard_index). Returns None when the
    sequence is exhausted - the caller's signal to jump forward in time
    rather than an error.

    Availability is resolved at `chart_date`, so a chart that only becomes
    available later is never offered.
    """
    for week in range(posted_week + 1, len(config.slots) + 1):
        try:
            chart = select_chart(config, chart_date, week, wildcard_index)
        except ValueError:
            continue
        if chart.id not in exclude_ids:
            return chart, week, wildcard_index

    # The pool cycles modulo its own size, so len(config.charts) iterations
    # is guaranteed to visit every entry without recomputing the pool here.
    wildcard_week = len(config.slots) + 1
    for i in range(wildcard_index, wildcard_index + len(config.charts)):
        try:
            chart = select_chart(config, chart_date, wildcard_week, i)
        except ValueError:
            return None
        if chart.id not in exclude_ids:
            return chart, wildcard_week, i
    return None
