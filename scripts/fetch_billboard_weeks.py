"""Fetch the Billboard chart weeks the archive is missing from billboard.com.

For every Billboard chart in charts.toml, walks each Saturday from the
schedule's start (or the chart's first week) to its last week, and fetches
the weeks with no chart in src/fiftyfm/data/billboard_archive.csv.gz. Each
week becomes one JSON line in --out:

    {"chart": slug, "date": "1977-02-12", "status": "ok", "songs": [[1, title, artist], ...]}

status is "ok", "empty" (the page had no chart rows) or "error". Rerunning
skips the weeks already "ok" and retries the rest, so it is safe to stop
with Ctrl-C and start again. Feed the file to build_billboard_archive.py
with --fetched.

    .venv/bin/python scripts/fetch_billboard_weeks.py --out billboard_fetched.jsonl
    .venv/bin/python scripts/fetch_billboard_weeks.py --dry-run   # count only
    .venv/bin/python scripts/fetch_billboard_weeks.py --wayback   # retry the rest

--wayback reads the weeks still not "ok" from the Wayback Machine's copies
of billboard.com instead, for whatever the site itself could not serve.

Requests are spaced --delay seconds apart (2 by default): ~13,000 weeks is
about seven hours.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import io
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

from fiftyfm.chart_source import (
    _BILLBOARD_URL,
    ChartFetchError,
    WaybackSource,
    parse_billboard,
)
from fiftyfm.config import ChartDef, TOP_N, load_config
from fiftyfm.schedule import snap_to_saturday

ARCHIVE = Path(__file__).resolve().parent.parent / "src/fiftyfm/data/billboard_archive.csv.gz"
# Archive weeks within this many days count as the same chart week - the
# soul archive dates its 1970s charts on Monday.
SAME_WEEK_DAYS = 3
USER_AGENT = "fiftyfm-archive/1.0 (personal chart playlist project)"


def archive_dates() -> dict[str, list[date]]:
    dates: dict[str, set[date]] = {}
    text = gzip.decompress(ARCHIVE.read_bytes()).decode("utf-8")
    for row in csv.DictReader(io.StringIO(text)):
        dates.setdefault(row["chart"], set()).add(date.fromisoformat(row["chart_date"]))
    return {slug: sorted(ds) for slug, ds in dates.items()}


def _covered(dates: list[date], week: date) -> bool:
    i = bisect.bisect_left(dates, week - timedelta(days=SAME_WEEK_DAYS))
    return i < len(dates) and dates[i] <= week + timedelta(days=SAME_WEEK_DAYS)


def missing_weeks(today: date) -> list[tuple[str, date]]:
    """(slug, Saturday) for every Billboard chart week the archive lacks."""
    config = load_config()
    have = archive_dates()
    last_saturday = snap_to_saturday(today) - timedelta(weeks=1)
    out = []
    for chart in config.charts.values():
        if chart.publisher != "Billboard":
            continue
        week = snap_to_saturday(max(config.start_date, chart.available_from))
        end = min(chart.available_until or last_saturday, last_saturday)
        dates = have.get(chart.slug, [])
        while week <= end:
            if not _covered(dates, week):
                out.append((chart.slug, week))
            week += timedelta(weeks=1)
    return out


def already_ok(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    done = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["status"] == "ok":
                done.add((rec["chart"], rec["date"]))
    return done


def fetch_week(session: requests.Session, slug: str, week: date) -> dict:
    rec = {"chart": slug, "date": week.isoformat()}
    url = _BILLBOARD_URL.format(slug=slug, date=week.isoformat())
    for attempt in range(3):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 429 or resp.status_code >= 500:
                # Back off hard rather than keep pressing a struggling site.
                time.sleep(60 * (attempt + 1))
                continue
            resp.raise_for_status()
        except requests.RequestException as exc:
            rec.update(status="error", error=str(exc))
            time.sleep(10)
            continue
        songs = parse_billboard(resp.text)[:TOP_N]
        if not songs:
            return {**rec, "status": "empty"}
        return {**rec, "status": "ok",
                "songs": [[s.rank, s.title, s.artist] for s in songs]}
    return {"status": "error", "error": "gave up after 3 attempts", **rec}


def fetch_wayback(source: WaybackSource, slug: str, week: date) -> dict:
    rec = {"chart": slug, "date": week.isoformat(), "via": "wayback"}
    chart = ChartDef(id=slug, slug=slug, display_name=slug, available_from=week)
    try:
        songs = source.fetch(chart, week).songs[:TOP_N]
    except ChartFetchError as exc:
        return {**rec, "status": "empty", "error": str(exc)}
    return {**rec, "status": "ok",
            "songs": [[s.rank, s.title, s.artist] for s in songs]}


def tried(path: Path) -> dict[tuple[str, str], str]:
    """{(slug, date): last status} for every week attempted in `path`."""
    last: dict[tuple[str, str], str] = {}
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                key = (rec["chart"], rec["date"])
                if last.get(key) != "ok":
                    last[key] = rec["status"]
    return last


def _runs(weeks: list[date]) -> list[str]:
    """Consecutive weeks collapsed into 'first..last (n)' ranges."""
    out, start = [], 0
    for i in range(1, len(weeks) + 1):
        if i == len(weeks) or weeks[i] - weeks[i - 1] != timedelta(weeks=1):
            first, last = weeks[start], weeks[i - 1]
            out.append(first.isoformat() if first == last
                       else f"{first.isoformat()}..{last.isoformat()} ({i - start})")
            start = i
    return out


def report(todo: list[tuple[str, date]], attempts: dict[tuple[str, str], str]) -> None:
    """Print each chart's missing weeks, split into failed and not yet tried."""
    by_chart: dict[str, dict[str, list[date]]] = {}
    for slug, week in todo:
        status = attempts.get((slug, week.isoformat()), "not tried")
        by_chart.setdefault(slug, {}).setdefault(status, []).append(week)
    for slug in sorted(by_chart):
        print(f"\n{slug}")
        for status, weeks in sorted(by_chart[slug].items()):
            print(f"  {status} ({len(weeks)}): {', '.join(_runs(weeks))}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("billboard_fetched.jsonl"))
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--chart", action="append", help="only this slug (repeatable)")
    ap.add_argument("--limit", type=int, help="stop after this many fetches")
    ap.add_argument("--dry-run", action="store_true", help="count the weeks, fetch nothing")
    ap.add_argument("--wayback", action="store_true",
                    help="read the weeks from the Wayback Machine instead")
    ap.add_argument("--report", action="store_true",
                    help="list every week still missing, by chart; fetch nothing")
    args = ap.parse_args()

    done = already_ok(args.out)
    todo = [
        (slug, week) for slug, week in missing_weeks(date.today())
        if (slug, week.isoformat()) not in done
        and (not args.chart or slug in args.chart)
    ]
    by_chart: dict[str, int] = {}
    for slug, _ in todo:
        by_chart[slug] = by_chart.get(slug, 0) + 1
    print(f"{len(todo)} weeks to fetch ({len(done)} already done)")
    for slug, n in sorted(by_chart.items()):
        print(f"  {slug}: {n}")
    if args.report:
        report(todo, tried(args.out))
        return
    if args.dry_run:
        return
    if args.limit is not None:
        todo = todo[:args.limit]

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    wayback = WaybackSource(session)
    counts = {"ok": 0, "empty": 0, "error": 0}
    started = time.monotonic()
    with open(args.out, "a", encoding="utf-8") as out:
        for i, (slug, week) in enumerate(todo, start=1):
            if args.wayback:
                rec = fetch_wayback(wayback, slug, week)
            else:
                rec = fetch_week(session, slug, week)
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            counts[rec["status"]] += 1
            if i % 25 == 0 or i == len(todo):
                left = (time.monotonic() - started) / i * (len(todo) - i)
                print(f"{i}/{len(todo)} {counts} - about {left / 3600:.1f}h left",
                      flush=True)
            time.sleep(args.delay)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("stopped - rerun the same command to resume")
