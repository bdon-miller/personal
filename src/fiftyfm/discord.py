from __future__ import annotations

import csv
import io
import json
from datetime import date

import requests

from .chart_source import Song

TUNEMYMUSIC_URL = "https://www.tunemymusic.com/transfer"


class DiscordError(RuntimeError):
    pass


def human_date(d: date) -> str:
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def songs_csv(songs: list[Song]) -> str:
    """TuneMyMusic-importable CSV of the chart's songs."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["Track name", "Artist name"])
    for s in songs:
        writer.writerow([s.title, s.artist])
    return buf.getvalue()


def post_playlist(
    webhook_url: str,
    *,
    thread_title: str,
    chart_name: str,
    chart_date: date,
    songs: list[Song],
    matched: int,
    playlist_url: str,
    csv_filename: str | None = None,
    csv_data: bytes | None = None,
    session=None,
) -> str | None:
    session = session or requests.Session()
    teaser = "\n".join(
        f"**{s.rank}.** {s.title} — {s.artist}" for s in songs[:5]
    )
    convert_hint = (
        "paste the Spotify link — or upload the attached CSV — into"
        if csv_data is not None
        else "paste the Spotify link into"
    )
    description = (
        f"The **{chart_name}** chart for the week of "
        f"**{human_date(chart_date)}**.\n\n"
        f"{teaser}\n…and {max(len(songs) - 5, 0)} more.\n\n"
        f"🎵 [Open in Spotify]({playlist_url}) "
        f"({matched}/{len(songs)} songs found)\n"
        f"🔀 Convert for Deezer/Qobuz/YouTube Music: {convert_hint} "
        f"[TuneMyMusic]({TUNEMYMUSIC_URL})"
    )
    payload = {
        "thread_name": thread_title,
        "embeds": [
            {
                "title": thread_title,
                "description": description,
                "color": 0xE9A03F,
            }
        ],
    }
    sep = "&" if "?" in webhook_url else "?"
    url = f"{webhook_url}{sep}wait=true"
    if csv_data is not None:
        resp = session.post(
            url,
            data={"payload_json": json.dumps(payload)},
            files={"files[0]": (csv_filename, csv_data, "text/csv")},
            timeout=30,
        )
    else:
        resp = session.post(url, json=payload, timeout=30)
    if resp.status_code >= 300:
        raise DiscordError(f"webhook returned {resp.status_code}: {resp.text}")
    try:
        return resp.json().get("channel_id")
    except Exception:  # noqa: BLE001 - a missing body must not fail the post
        return None


def post_failure(webhook_url: str, message: str, session=None) -> None:
    session = session or requests.Session()
    sep = "&" if "?" in webhook_url else "?"
    try:
        session.post(
            f"{webhook_url}{sep}wait=true",
            json={
                "thread_name": "fiftyfm run failed",
                "content": f"⚠️ {message}",
            },
            timeout=30,
        )
    except Exception:
        pass
