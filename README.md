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

## Weekly polls

Every Saturday at 08:00, a second timer posts a favorite and a
least-favorite poll into that week's thread. Choices are the nine
most-played songs from the week's chart by Last.fm playcount, plus
`Other — reply in thread`; both polls allow multiple selections. The polls
close Monday at 08:00 — an hour before Monday's new thread opens with the
results.

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

3. **Last.fm** (optional, but recommended): create an API key at
   https://www.last.fm/api/account/create (free, no OAuth) and put it in
   `LASTFM_API_KEY`. Without it, the weekly poll's ballot falls back to
   plain Billboard chart-rank order instead of Last.fm play counts - the
   polls still go out either way.

Verify, then run for real:

    /opt/fiftyfm/.venv/bin/fiftyfm run --dry-run
    /opt/fiftyfm/.venv/bin/fiftyfm poll --dry-run
    sudo systemctl start fiftyfm.service
    journalctl -u fiftyfm.service

`--dry-run` skips Discord and Spotify writes, but it still performs a real
Billboard fetch and, for `poll --dry-run`, up to 40 Last.fm lookups - it is
not side-effect-free against those upstream APIs.

Upgrading an existing install skips exactly one poll week: the first
Saturday after upgrade has no `thread_id` recorded for the prior week's
thread, so that week's `poll` run is a no-op. It self-heals the following
week once a new thread has been posted with the upgraded code.

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