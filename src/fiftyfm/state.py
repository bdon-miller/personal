from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class State:
    cursor: date
    wildcard_index: int = 0
    completed: dict[str, dict] = field(default_factory=dict)
    last_posted_key: str | None = None


def run_key(chart_id: str, chart_date: date) -> str:
    return f"{chart_id}@{chart_date.isoformat()}"


def load_state(path: Path, default_cursor: date) -> State:
    if not path.exists():
        return State(cursor=default_cursor)
    data = json.loads(path.read_text())
    return State(
        cursor=date.fromisoformat(data["cursor"]),
        wildcard_index=data.get("wildcard_index", 0),
        completed=data.get("completed", {}),
        last_posted_key=data.get("last_posted_key"),
    )


def save_state(path: Path, state: State) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "cursor": state.cursor.isoformat(),
            "wildcard_index": state.wildcard_index,
            "completed": state.completed,
            "last_posted_key": state.last_posted_key,
        },
        indent=2,
    )
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(payload)
    os.replace(tmp, path)
