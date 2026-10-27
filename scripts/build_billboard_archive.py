"""Build src/fiftyfm/data/billboard_archive.csv.gz, the app's chart archive.

The archive is the first place the app looks for a Billboard chart; only a
week missing from it is read from billboard.com, then the Wayback Machine.
It is assembled from:

- Hot 100: mhollingshead/billboard-hot-100's all.json.
- Soul, Latin, Pop, Hot Rock, Dance/Electronic through 2018: the
  pdp2600/chartscraper CSVs named in FILES.
- Hot Country Singles 1973-2008: the American Country Countdown wiki
  (CC-BY-SA), pulled through its MediaWiki API. The show counted down
  Billboard's country chart until 2009, then switched to Mediabase.
- Everything else: JSONL written by scripts/fetch_billboard_weeks.py.

    python -I scripts/build_billboard_archive.py \
        --chartscraper DIR --hot100 all.json --acc acc.json [--fetched F.jsonl ...]

--acc caches the wiki pull: it is read if it exists and written otherwise.
Only the top TOP_N of each week is kept - the app never posts more.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

TOP_N = 40
OUT = Path(__file__).resolve().parent.parent / "src/fiftyfm/data/billboard_archive.csv.gz"

# chartscraper file -> the chart's slug in charts.toml
FILES = {
    "All_Hip_Hop_Songs_from_1958-10-20_to_2018-12-31.csv": "r-b-hip-hop-songs",
    "All_Latin_Songs_from_1986-09-20_to_2018-12-31.csv": "latin-songs",
    "All_Pop_Songs_from_1992-10-03_to_2018-12-31.csv": "pop-songs",
    "All_Rock_Songs_from_2009-06-20_to_2018-12-31.csv": "hot-rock-songs",
    "All_Dance_Electronic_Songs_from_2013-01-26_to_2018-12-31.csv": "dance-electronic-songs",
}

ACC_API = "https://american-country-countdown.fandom.com/api.php"
COUNTRY_SLUG = "country-songs"
COUNTRY_UNTIL = date(2008, 12, 31)
# Artist - Title (change); the title may itself hold parentheses.
_ACC_LINE = re.compile(r"^(?P<artist>.+?) - (?P<title>.+) \([^()]*\)$")
_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")


def _acc_get(params: dict) -> dict:
    req = urllib.request.Request(
        ACC_API,
        data=urllib.parse.urlencode({**params, "format": "json"}).encode(),
        headers={"User-Agent": "fiftyfm chart archive builder"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch_acc_pages() -> dict[str, str]:
    """{page title: wikitext} for every page on the wiki, 50 per request."""
    titles, cont = [], {}
    while True:
        d = _acc_get({"action": "query", "list": "allpages", "aplimit": "500", **cont})
        titles += [p["title"] for p in d["query"]["allpages"]]
        if "continue" not in d:
            break
        cont = {"apcontinue": d["continue"]["apcontinue"]}
    pages = {}
    for i in range(0, len(titles), 50):
        d = _acc_get({
            "action": "query", "prop": "revisions", "rvprop": "content",
            "rvslots": "main", "formatversion": "2",
            "titles": "|".join(titles[i:i + 50]),
        })
        for p in d["query"]["pages"]:
            if "revisions" in p:
                pages[p["title"]] = p["revisions"][0]["slots"]["main"]["content"]
        time.sleep(1.5)  # be gentle with a volunteer wiki
    return pages


def parse_acc_week(text: str) -> list[tuple[str, str]] | None:
    """[(title, artist), ...] in rank order, or None for a non-chart page.

    Chart lines are numbered wikitext list items holding a bold
    "Artist - Title (change)", wiki links optional. Every weekly countdown
    is a top 40; redirects and the year-end specials (a top 50 or top 100
    of the year, aired in place of that week's chart) are not.
    """
    songs = []
    for line in text.splitlines():
        if not line.startswith("#") or line.upper().startswith("#REDIRECT"):
            continue  # the "Songs falling off" footer is not numbered
        body = _LINK.sub(r"\1", line[1:]).strip().strip("'").strip().rstrip("*").strip()
        if not body:
            continue  # blank padding rows
        m = _ACC_LINE.match(body)
        if m is None:
            raise ValueError(f"unparseable ACC line: {line!r}")
        songs.append((m["title"].strip(), m["artist"].strip()))
    return songs if len(songs) == TOP_N else None


def country_rows(pages: dict[str, str]) -> set[tuple]:
    rows = set()
    for page_title, text in pages.items():
        try:
            d = datetime.strptime(page_title, "%B %d, %Y").date()
        except ValueError:
            continue  # artist and song pages
        if d > COUNTRY_UNTIL:
            continue
        songs = parse_acc_week(text)
        if songs is None:
            continue
        for rank, (title, artist) in enumerate(songs, start=1):
            rows.add((COUNTRY_SLUG, d.isoformat(), rank, title, artist))
    return rows


def acc_pages(cache: Path | None) -> dict[str, str]:
    if cache is not None and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    pages = fetch_acc_pages()
    if cache is not None:
        cache.write_text(json.dumps(pages), encoding="utf-8")
    return pages


def hot100_rows(path: Path) -> set[tuple]:
    rows = set()
    for week in json.loads(path.read_text(encoding="utf-8")):
        for e in week["data"]:
            if e["this_week"] <= TOP_N:
                rows.add(("hot-100", week["date"], e["this_week"],
                          e["song"].strip(), e["artist"].strip()))
    return rows


def chartscraper_rows(src: Path) -> set[tuple]:
    rows = set()
    for name, slug in FILES.items():
        with open(src / name, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                rank = int(r["ranking"])
                if rank > TOP_N:
                    continue
                # The scrape repeats some rows verbatim; a set drops those
                # while keeping genuine ties (two titles at one rank).
                rows.add((slug, r["chart_date"], rank,
                          r["title"].strip(), r["artist"].strip()))
    return rows


# billboard.com lists only the #1 for Hot Latin Songs' first two weeks
# (1986-09-06 and -13); a playlist that short isn't worth posting.
MIN_FETCHED_SONGS = 10


def fetched_rows(path: Path) -> set[tuple]:
    """Rows from fetch_billboard_weeks.py output; failed weeks have none."""
    rows = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            songs = rec.get("songs", [])
            if len(songs) < MIN_FETCHED_SONGS:
                continue
            for rank, title, artist in songs:
                rows.add((rec["chart"], rec["date"], rank, title, artist))
    return rows


def write_archive(rows: set[tuple]) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["chart", "chart_date", "rank", "title", "artist"])
    w.writerows(sorted(rows))
    # mtime=0 keeps the output byte-identical across rebuilds.
    OUT.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))
    print(f"wrote {len(rows)} rows to {OUT}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chartscraper", type=Path, required=True)
    ap.add_argument("--hot100", type=Path, required=True)
    ap.add_argument("--acc", type=Path)
    ap.add_argument("--fetched", type=Path, nargs="*", default=[])
    args = ap.parse_args()
    rows = hot100_rows(args.hot100)
    rows |= chartscraper_rows(args.chartscraper)
    rows |= country_rows(acc_pages(args.acc))
    for path in args.fetched:
        rows |= fetched_rows(path)
    write_archive(rows)


if __name__ == "__main__":
    main()
