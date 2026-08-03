# fiftyfm

Every week, a systemd timer fetches a historical Billboard chart (starting
January 1976, advancing 3 chart-weeks per run by default), builds a public
Spotify playlist of its Top 40, and posts it as a new thread in a Discord
forum channel. Each post also attaches the chart as a CSV
(`Track name,Artist name`) that anyone can upload to
[TuneMyMusic](https://www.tunemymusic.com/transfer) to build the playlist
on their own service (Deezer, Qobuz, YouTube Music, ...).

## Weekly rotation

Chart slots resolve against the app's **time cursor** (the historical chart
date) using `src/fiftyfm/charts.toml`:

- Week 1: Hot 100
- Week 2: Top Tracks (rock) once the cursor reaches Mar 1981; Hot Soul
  Singles before that
- Week 3: Hot Rap Songs once the cursor reaches Mar 1989; falls back to
  Soul, then Country
- Week 4 (and any 5th week): rotates through every other chart the cursor
  era offers (Easy Listening, Disco, Country, Latin, ...)

## Install on a Linux server

    git clone <this repo> && cd <repo>
    sudo ./install.sh

Then fill in `/etc/fiftyfm/env`:

1. **Spotify**: create an app at https://developer.spotify.com/dashboard
   (redirect URI `http://127.0.0.1:8888/callback`). Put the client ID and
   secret in the env file. Mint the refresh token from any machine:

       SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=... fiftyfm auth

2. **Discord**: in a **forum channel**'s settings, create a webhook and
   paste its URL.

Verify without side effects, then for real:

    /opt/fiftyfm/.venv/bin/fiftyfm run --dry-run
    sudo systemctl start fiftyfm.service
    journalctl -u fiftyfm.service

## Operations

The systemd service runs as root with `StateDirectory=fiftyfm`, so its state
lives at `/var/lib/fiftyfm/state.json` (set via `FIFTYFM_STATE_PATH` in
`deploy/fiftyfm.service`). Operator commands must point at that same file —
run as root with the same override, otherwise they read/write an unrelated,
empty state file under your own user's home directory:

    sudo FIFTYFM_STATE_PATH=/var/lib/fiftyfm/state.json /opt/fiftyfm/.venv/bin/fiftyfm status
    sudo FIFTYFM_STATE_PATH=/var/lib/fiftyfm/state.json /opt/fiftyfm/.venv/bin/fiftyfm set-cursor 1981-03-20   # jump through time (snaps to Saturday)

The cursor only advances after a successful run, and completed chart-dates
are never re-posted. Pace is `weeks_per_run` in `charts.toml` (3 = one
historical quarter per real month; 1 = real time). Since the install is
non-editable, changing pace or schedule after install requires copying the
file out first, e.g.:

    sudo mkdir -p /etc/fiftyfm
    sudo cp /opt/fiftyfm/src/fiftyfm/charts.toml /etc/fiftyfm/charts.toml
    sudo $EDITOR /etc/fiftyfm/charts.toml

then add `FIFTYFM_CHARTS_PATH=/etc/fiftyfm/charts.toml` to `/etc/fiftyfm/env`.