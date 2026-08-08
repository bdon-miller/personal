# fiftyfm

Every week, a systemd timer fetches a historical chart (Billboard, or
Oricon for Japanese weeks) (starting January 1976, advancing 3 chart-weeks
per run by default), builds a public Spotify playlist of its Top 40, and
posts it as a new thread in a Discord forum channel. Each post also attaches
the chart as a CSV (`Track name,Artist name`) that anyone can upload to
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
  era offers (Disco, Country, Latin, Oricon Weekly Singles, ...)

## Japanese charts

Two of the wildcard charts are Oricon Weekly Singles, served from a CSV
shipped inside the package rather than from an API: **Shōwa**
(1976-01-12 to 1989-01-02, top 20) and **Heisei** (1989-01-16 to
2008-12-29, top 30). Oricon dates its charts on Monday while the app's
cursor is a Saturday, so a run resolves to the nearest Oricon Monday
within 10 days and the post shows that real chart date, not the cursor's.

Expect a lower Spotify match rate on these weeks. Some artists are absent
from Spotify entirely — SMAP most notably — and those tracks are skipped
rather than replaced. Japanese searches use strict matching only: the
loose fallback reliably returns karaoke pressings, and a wrong track
nobody notices is worse than a missing one.

## Weekly polls

Every Saturday at 08:00, a second timer posts a favorite and a
least-favorite poll into that week's thread. The favorite poll's choices
are the nine most-played songs from the week's chart by Last.fm
playcount; the least-favorite poll's are the nine least-played, least
played first. Both add `Other — reply in thread` and allow multiple
selections. The polls
close Monday at 08:00 — an hour before Monday's new thread opens with the
results.

To rebuild the least-favorite ballot after the polls have gone out, run
`fiftyfm repoll-least-favorite`. Discord cannot edit a live poll, so this
posts a replacement and deletes the original — **any votes already cast on
the least-favorite poll are lost.** The replacement is sized to close at
the same Monday 08:00 as the poll it replaces, so the recap still finds it
finalized. Use `--dry-run` to see the new ballot first. The favorite poll
is left untouched.

## Skipping a chart

If you post a chart on Monday but decide you don't want it, run `fiftyfm skip`
after the post. It creates a replacement chart for the same historical week and
leaves the time cursor unchanged, so the following Monday proceeds normally. The
superseded Discord thread and Spotify playlist are not deleted — remove those by
hand. Note that the replacement thread carries no "last week's results" recap,
so deleting the old thread loses that line.

The replacement will usually appear again the following Monday under a
different historical date — the rotation is forward-only, so a skip just
moves the repeat rather than removing it. `skip` records which slot it
consumed so the next Monday's run advances past it, which avoids the repeat
for a week-1 or week-2 skip. It cannot avoid it for a skip that lands on a
single-member wildcard pool — every wildcard week until Disco unlocks on
1976-08-28 — since there is only one chart in the pool to draw from either way.

When every available chart has already been posted for that week, `skip`
instead jumps forward by `weeks_per_run` and posts the next period's chart,
advancing the cursor. On a wildcard week before 1976-08-28 there is no
alternate chart at all, so this is exactly what happens: `skip` jumps forward
and posts the **same** chart again at a later date. Run `fiftyfm skip
--dry-run` first to check — it shows the chart it would post and a
`[time-jump]` marker when this is about to happen.

If the week it jumps to has already been posted — which normally only
happens after a backwards `fiftyfm set-cursor` — it keeps stepping forward
a period at a time until it finds a free week, then leaves the cursor past
wherever it landed. After eight such steps it gives up and fails rather
than walking through years of history; move the cursor by hand at that
point.

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
chart fetch and, for `poll --dry-run`, up to 40 Last.fm lookups - it is
not side-effect-free against those upstream APIs. Oricon weeks read from
the packaged CSV, so those fetches touch no network at all. `skip
--dry-run` now fetches too, which is what lets it show the real chart
date and track count before you commit to posting.

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