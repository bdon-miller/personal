from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from .chart_source import BillboardSource
from .config import load_config
from .pipeline import run as pipeline_run
from .poll import run_poll as poll_run
from .schedule import snap_to_saturday
from .spotify import TOKEN_URL, SpotifyClient
from .state import load_state, save_state

REQUIRED_ENV = (
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    "SPOTIFY_REFRESH_TOKEN",
    "DISCORD_WEBHOOK_URL",
)
POLL_REQUIRED_ENV = (
    "LASTFM_API_KEY",
    "DISCORD_WEBHOOK_URL",
)
AUTH_REDIRECT = "http://127.0.0.1:8888/callback"


def _state_path() -> Path:
    default = Path.home() / ".local" / "state" / "fiftyfm" / "state.json"
    return Path(os.environ.get("FIFTYFM_STATE_PATH", default))


def _charts_path(arg: str | None) -> Path | None:
    if arg:
        return Path(arg)
    env = os.environ.get("FIFTYFM_CHARTS_PATH")
    return Path(env) if env else None


def _cmd_run(args) -> int:
    config = load_config(_charts_path(args.charts))
    env = os.environ
    spotify = None
    if not args.dry_run:
        missing = [v for v in REQUIRED_ENV if not env.get(v)]
        if missing:
            print(f"missing env vars: {', '.join(missing)}", file=sys.stderr)
            return 2
        spotify = SpotifyClient(
            env["SPOTIFY_CLIENT_ID"],
            env["SPOTIFY_CLIENT_SECRET"],
            env["SPOTIFY_REFRESH_TOKEN"],
        )
    return pipeline_run(
        config,
        _state_path(),
        env,
        BillboardSource(),
        spotify,
        today=date.today(),
        dry_run=args.dry_run,
    )


def _cmd_poll(args) -> int:
    config = load_config(_charts_path(args.charts))
    env = os.environ
    if not args.dry_run:
        missing = [v for v in POLL_REQUIRED_ENV if not env.get(v)]
        if missing:
            print(f"missing env vars: {', '.join(missing)}", file=sys.stderr)
            return 2
    return poll_run(
        config,
        _state_path(),
        env,
        BillboardSource(),
        dry_run=args.dry_run,
    )


def _cmd_set_cursor(args) -> int:
    config = load_config(_charts_path(args.charts))
    path = _state_path()
    state = load_state(path, default_cursor=config.start_date)
    state.cursor = snap_to_saturday(date.fromisoformat(args.date))
    save_state(path, state)
    print(f"cursor set to {state.cursor.isoformat()}")
    return 0


def _cmd_status(args) -> int:
    config = load_config(_charts_path(args.charts))
    state = load_state(_state_path(), default_cursor=config.start_date)
    posted = sum(1 for r in state.completed.values() if r.get("posted"))
    print(f"cursor:         {state.cursor.isoformat()}")
    print(f"wildcard index: {state.wildcard_index}")
    print(f"completed runs: {posted}")
    return 0


def _cmd_auth(args) -> int:
    import urllib.parse

    import requests

    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET first",
              file=sys.stderr)
        return 2
    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": AUTH_REDIRECT,
            "scope": "playlist-modify-public",
        }
    )
    print("1. Open this URL in a browser and approve access:\n")
    print(f"   https://accounts.spotify.com/authorize?{params}\n")
    print("2. You'll be redirected to a URL that fails to load - that's fine.")
    pasted = input("3. Paste that full redirect URL here: ").strip()
    code = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)["code"][0]
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": AUTH_REDIRECT,
        },
        auth=(client_id, client_secret),
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"token exchange failed: {resp.text}", file=sys.stderr)
        return 1
    print(f"\nSPOTIFY_REFRESH_TOKEN={resp.json()['refresh_token']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fiftyfm")
    parser.add_argument("--charts", help="path to charts.toml override")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="execute one weekly run")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.set_defaults(func=_cmd_run)

    p_poll = sub.add_parser("poll", help="post this week's follow-up polls")
    p_poll.add_argument("--dry-run", action="store_true")
    p_poll.set_defaults(func=_cmd_poll)

    p_set = sub.add_parser("set-cursor", help="jump the time cursor")
    p_set.add_argument("date", help="YYYY-MM-DD (snapped to Saturday)")
    p_set.set_defaults(func=_cmd_set_cursor)

    sub.add_parser("status", help="show cursor and history").set_defaults(
        func=_cmd_status
    )
    sub.add_parser("auth", help="mint a Spotify refresh token").set_defaults(
        func=_cmd_auth
    )

    args = parser.parse_args(argv)
    return args.func(args)
