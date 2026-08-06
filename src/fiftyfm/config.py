from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date
from importlib import resources
from pathlib import Path

TOP_N = 40


@dataclass(frozen=True)
class ChartDef:
    id: str
    slug: str
    display_name: str
    available_from: date
    available_until: date | None = None


@dataclass(frozen=True)
class Config:
    charts: dict[str, ChartDef]
    slots: list[list[str]]
    start_date: date
    weeks_per_run: int


def load_config(path: Path | None = None) -> Config:
    if path is None:
        raw = (resources.files("fiftyfm") / "charts.toml").read_bytes()
    else:
        raw = Path(path).read_bytes()
    data = tomllib.loads(raw.decode())

    charts: dict[str, ChartDef] = {}
    for c in data["charts"]:
        charts[c["id"]] = ChartDef(
            id=c["id"],
            slug=c["slug"],
            display_name=c["display_name"],
            available_from=c["available_from"],
            available_until=c.get("available_until"),
        )
    sched = data["schedule"]
    for slot in sched["slots"]:
        for chart_id in slot:
            if chart_id not in charts:
                raise ValueError(f"slot references unknown chart id {chart_id!r}")
    return Config(
        charts=charts,
        slots=sched["slots"],
        start_date=sched["start_date"],
        weeks_per_run=sched["weeks_per_run"],
    )
