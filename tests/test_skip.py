from datetime import date, timedelta

from fakes import FakeSource, FakeSpotify

from fiftyfm.chart_source import ChartFetchError, Song
from fiftyfm.config import load_config
from fiftyfm.pipeline import MAX_JUMPS, run, skip
from fiftyfm.state import load_state, run_key, save_state

CFG = load_config()
ENV = {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/tok"}
SONGS = [Song(i, f"Song {i}", f"Artist {i}") for i in range(1, 101)]
FEB14 = date(1976, 2, 14)
MAR6 = date(1976, 3, 6)


def source():
    return FakeSource(songs=SONGS)


def seed(tmp_path, *, chart_id="country", week=3, wildcard_index=0, **extra):
    """State as it looks right after a Monday run posted `chart_id`."""
    path = tmp_path / "state.json"
    st = load_state(path, default_cursor=CFG.start_date)
    key = run_key(chart_id, FEB14)
    st.completed[key] = {
        "playlist_url": "u", "matched": 40, "posted": True,
        "week": week, "thread_id": "tid-old", **extra,
    }
    st.last_posted_key = key
    st.wildcard_index = wildcard_index
    st.cursor = MAR6          # Monday's run already advanced 3 weeks
    save_state(path, st)
    return path


def test_skip_posts_an_alternate_and_leaves_the_cursor_alone(tmp_path):
    path = seed(tmp_path)
    posts = []
    code = skip(
        CFG, path, ENV, source(), FakeSpotify(), today=date(2026, 8, 17),
        notify=lambda *a, **k: (posts.append(k), "tid-new")[1],
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    assert posts[0]["chart_name"] == "Oricon Weekly Singles (Shōwa)"
    assert posts[0]["chart_date"] == FEB14
    st = load_state(path, default_cursor=CFG.start_date)
    assert st.cursor == MAR6                      # unchanged
    assert st.last_posted_key == run_key("oricon-showa", FEB14)
    assert st.completed[st.last_posted_key]["thread_id"] == "tid-new"
    assert st.completed[run_key("country", FEB14)]["posted"] is True
    assert st.wildcard_index == 1                 # pool pick bumps it


def test_skip_from_a_fixed_slot_does_not_bump_wildcard_index(tmp_path):
    path = seed(tmp_path, chart_id="hot-100", week=1)
    posts = []
    skip(
        CFG, path, ENV, source(), FakeSpotify(), today=date(2026, 8, 3),
        notify=lambda *a, **k: (posts.append(k), "tid-new")[1],
        notify_failure=lambda *a, **k: None,
    )
    assert posts[0]["chart_name"] == "Hot Soul Singles"
    st = load_state(path, default_cursor=CFG.start_date)
    assert st.wildcard_index == 0


def test_skip_time_jumps_when_the_sequence_is_exhausted(tmp_path):
    # Pre-disco the pool is [oricon-showa] alone; with both it and country
    # already posted at Feb 14 there is no alternate at that date.
    path = seed(tmp_path, chart_id="oricon-showa", week=4, wildcard_index=0)
    st = load_state(path, default_cursor=CFG.start_date)
    st.completed[run_key("country", FEB14)] = {"posted": True, "week": 3}
    save_state(path, st)
    posts = []
    code = skip(
        CFG, path, ENV, source(), FakeSpotify(), today=date(2026, 8, 17),
        notify=lambda *a, **k: (posts.append(k), "tid-new")[1],
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    assert posts[0]["chart_date"] == MAR6          # jumped one period forward
    st = load_state(path, default_cursor=CFG.start_date)
    assert st.cursor == date(1976, 3, 27)          # MAR6 + 3 weeks
    assert st.last_posted_key.endswith("@1976-03-06")


def test_skip_noop_without_a_last_posted_key(tmp_path, capsys):
    code = skip(
        CFG, tmp_path / "state.json", ENV, source(), None,
        today=date(2026, 8, 17),
        notify=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no post")),
        notify_failure=lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("not a failure")
        ),
    )
    assert code == 0
    assert "nothing posted yet" in capsys.readouterr().out


def test_skip_dry_run_writes_nothing_and_posts_nothing(tmp_path, capsys):
    path = seed(tmp_path)
    before = path.read_text()
    code = skip(
        CFG, path, ENV, source(), None, today=date(2026, 8, 17), dry_run=True,
        notify=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no post")),
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    assert path.read_text() == before
    assert "Oricon Weekly Singles (Shōwa)" in capsys.readouterr().out


def test_skip_warns_when_superseding_a_thread_that_already_has_polls(tmp_path, capsys):
    path = seed(tmp_path, poll_posted=True)
    skip(
        CFG, path, ENV, source(), FakeSpotify(), today=date(2026, 8, 17),
        notify=lambda *a, **k: "tid-new", notify_failure=lambda *a, **k: None,
    )
    assert "never be recapped" in capsys.readouterr().err


def test_skip_reports_a_fetch_failure(tmp_path):
    path = seed(tmp_path)
    failures = []
    code = skip(
        CFG, path, ENV, FakeSource(exc=ChartFetchError("nope")), FakeSpotify(),
        today=date(2026, 8, 17), notify=lambda *a, **k: "tid-new",
        notify_failure=lambda url, msg, **k: failures.append(msg),
    )
    assert code == 1
    assert "nope" in failures[0]


def test_failed_skip_can_retry_and_reuses_its_own_playlist(tmp_path):
    # Fix 1: exclude must only count *posted* records at that date. If a
    # skip creates a playlist, then fails at Discord, retrying must land on
    # the same candidate and reuse the orphaned playlist - not treat the
    # failed attempt's own record as "already tried" and move on.
    path = seed(tmp_path)  # country posted at FEB14, cursor already at MAR6
    oricon_key = run_key("oricon-showa", FEB14)

    class DiscordError(Exception):
        pass

    def failing_notify(*a, **k):
        raise DiscordError("discord is down")

    code = skip(
        CFG, path, ENV, source(), FakeSpotify(), today=date(2026, 8, 17),
        notify=failing_notify, notify_failure=lambda *a, **k: None,
    )
    assert code == 1
    st = load_state(path, default_cursor=CFG.start_date)
    assert st.completed[oricon_key]["posted"] is False
    playlist_url = st.completed[oricon_key]["playlist_url"]
    assert playlist_url

    posts = []
    spotify_second = FakeSpotify()
    code = skip(
        CFG, path, ENV, source(), spotify_second, today=date(2026, 8, 17),
        notify=lambda *a, **k: (posts.append(k), "tid-new")[1],
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    # same candidate, retried
    assert posts[0]["chart_name"] == "Oricon Weekly Singles (Shōwa)"
    assert spotify_second.created is None  # playlist NOT recreated
    st = load_state(path, default_cursor=CFG.start_date)
    assert st.completed[oricon_key]["posted"] is True
    assert st.completed[oricon_key]["playlist_url"] == playlist_url
    assert st.cursor == MAR6  # still no time-jump


def test_skip_hops_forward_past_an_already_completed_jump_target(tmp_path):
    # A week-5 skip pre-disco finds oricon-showa as the pool's only member
    # at every date. When the first jump target is already posted, keep
    # advancing a period at a time rather than reporting nothing to do -
    # re-posting over it would overwrite thread_id and rewind
    # last_posted_key, and stopping leaves the operator's skip unhonoured.
    path = seed(tmp_path, chart_id="oricon-showa", week=4, wildcard_index=0)
    st = load_state(path, default_cursor=CFG.start_date)
    jump_key = run_key("oricon-showa", MAR6)
    st.completed[jump_key] = {
        "posted": True, "week": 5, "thread_id": "tid-real", "playlist_url": "u2",
    }
    save_state(path, st)

    posts = []
    code = skip(
        CFG, path, ENV, source(), FakeSpotify(), today=date(2026, 8, 29),
        notify=lambda *a, **k: (posts.append(k), "tid-new")[1],
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    assert posts[0]["chart_date"] == date(1976, 3, 27)  # MAR6 was taken
    st = load_state(path, default_cursor=CFG.start_date)
    assert st.completed[jump_key]["thread_id"] == "tid-real"  # not overwritten
    assert st.last_posted_key == run_key("oricon-showa", date(1976, 3, 27))
    assert st.cursor == date(1976, 4, 17)  # landing date + 3 weeks


def test_skip_fails_loudly_when_every_week_within_the_hop_cap_is_taken(tmp_path):
    # A badly rewound cursor must surface as a failure, not spin through
    # decades of already-posted weeks looking for a gap.
    path = seed(tmp_path, chart_id="oricon-showa", week=4, wildcard_index=0)
    st = load_state(path, default_cursor=CFG.start_date)
    for hop in range(MAX_JUMPS):
        taken = MAR6 + timedelta(weeks=CFG.weeks_per_run * hop)
        st.completed[run_key("oricon-showa", taken)] = {"posted": True, "week": 5}
    save_state(path, st)

    failures = []
    code = skip(
        CFG, path, ENV, source(), FakeSpotify(), today=date(2026, 8, 29),
        notify=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no post")),
        notify_failure=lambda url, msg, **k: failures.append(msg),
    )
    assert code == 1
    assert "1976-07-31" in failures[0]  # the last date it tried
    st = load_state(path, default_cursor=CFG.start_date)
    assert st.cursor == MAR6  # untouched
    assert st.last_posted_key == run_key("oricon-showa", FEB14)


def test_skip_warns_when_time_jump_reserves_the_same_chart(tmp_path, capsys):
    # Fix 3: pre-disco the wildcard pool has exactly one member, so a
    # time-jump on a wildcard week always re-serves the chart just
    # superseded. The operator must be told, since the skip otherwise looks
    # like a no-op that quietly burns a historical week.
    path = seed(tmp_path, chart_id="oricon-showa", week=4, wildcard_index=0)
    code = skip(
        CFG, path, ENV, source(), FakeSpotify(), today=date(2026, 8, 24),
        notify=lambda *a, **k: "tid-new", notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    err = capsys.readouterr().err
    assert "no alternate chart exists" in err
    assert "Oricon Weekly Singles (Shōwa)" in err


def test_normal_skip_records_slot_consumed(tmp_path):
    path = seed(tmp_path)  # country posted at week 3
    skip(
        CFG, path, ENV, source(), FakeSpotify(), today=date(2026, 8, 17),
        notify=lambda *a, **k: "tid-new", notify_failure=lambda *a, **k: None,
    )
    st = load_state(path, default_cursor=CFG.start_date)
    assert st.slot_consumed == 4  # oricon-showa picked at week 4


def test_time_jump_skip_does_not_record_slot_consumed(tmp_path):
    path = seed(tmp_path, chart_id="oricon-showa", week=4, wildcard_index=0)
    st = load_state(path, default_cursor=CFG.start_date)
    st.completed[run_key("country", FEB14)] = {"posted": True, "week": 3}
    save_state(path, st)

    code = skip(
        CFG, path, ENV, source(), FakeSpotify(), today=date(2026, 8, 17),
        notify=lambda *a, **k: "tid-new", notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    st = load_state(path, default_cursor=CFG.start_date)
    assert st.slot_consumed is None


def test_normal_skip_makes_next_run_advance_past_the_consumed_slot(tmp_path):
    # Fix 4: without slot_consumed, week_of_month and the forward-only slot
    # walk advance in lockstep, so the next Monday's fresh selection repeats
    # the replacement genre skip just posted. Demonstrated upstream: skip
    # posted Hot Soul Singles at week 2; without the fix the next run would
    # post Hot Soul Singles again (week 2, by calendar) rather than
    # advancing to week 3 (Hot Country Singles).
    path = tmp_path / "state.json"
    posts = []
    note = lambda tid: (lambda *a, **k: (posts.append(k), tid)[1])  # noqa: E731

    run(CFG, path, ENV, source(), FakeSpotify(), today=date(2026, 8, 3),
        notify=note("tid-1"), notify_failure=lambda *a, **k: None)
    assert posts[0]["chart_name"] == "Hot 100"

    skip(CFG, path, ENV, source(), FakeSpotify(), today=date(2026, 8, 3),
         notify=note("tid-2"), notify_failure=lambda *a, **k: None)
    assert posts[1]["chart_name"] == "Hot Soul Singles"
    st = load_state(path, default_cursor=CFG.start_date)
    assert st.slot_consumed == 2

    run(CFG, path, ENV, source(), FakeSpotify(), today=date(2026, 8, 10),
        notify=note("tid-3"), notify_failure=lambda *a, **k: None)
    assert posts[2]["chart_name"] == "Hot Country Singles"  # not a repeat
    st = load_state(path, default_cursor=CFG.start_date)
    assert st.slot_consumed is None  # cleared by the fresh selection that used it


def test_run_then_skip_then_run_composes_through_one_state_file(tmp_path):
    path = tmp_path / "state.json"
    posts = []
    note = lambda tid: (lambda *a, **k: (posts.append(k), tid)[1])  # noqa: E731

    run(CFG, path, ENV, source(), FakeSpotify(), today=date(2026, 8, 3),
        notify=note("tid-1"), notify_failure=lambda *a, **k: None)
    st = load_state(path, default_cursor=CFG.start_date)
    assert st.cursor == date(1976, 1, 24)
    assert posts[0]["chart_name"] == "Hot 100"

    skip(CFG, path, ENV, source(), FakeSpotify(), today=date(2026, 8, 3),
         notify=note("tid-2"), notify_failure=lambda *a, **k: None)
    st = load_state(path, default_cursor=CFG.start_date)
    assert st.cursor == date(1976, 1, 24)               # skip did not advance
    assert posts[1]["chart_date"] == date(1976, 1, 3)   # same historical week
    assert posts[1]["chart_name"] != posts[0]["chart_name"]

    run(CFG, path, ENV, source(), FakeSpotify(), today=date(2026, 8, 10),
        notify=note("tid-3"), notify_failure=lambda *a, **k: None)
    st = load_state(path, default_cursor=CFG.start_date)
    assert posts[2]["chart_date"] == date(1976, 1, 24)  # next week, as normal
    assert st.cursor == date(1976, 2, 14)
