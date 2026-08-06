from datetime import date

from fakes import FakeSource, FakeSpotify

from fiftyfm.chart_source import ChartFetchError, Song
from fiftyfm.config import load_config
from fiftyfm.pipeline import run, skip
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
    assert posts[0]["chart_name"] == "Easy Listening"
    assert posts[0]["chart_date"] == FEB14
    st = load_state(path, default_cursor=CFG.start_date)
    assert st.cursor == MAR6                      # unchanged
    assert st.last_posted_key == run_key("easy-listening", FEB14)
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
    # Pre-disco the pool is [easy-listening] alone; with both it and country
    # already posted at Feb 14 there is no alternate at that date.
    path = seed(tmp_path, chart_id="easy-listening", week=4, wildcard_index=0)
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
    assert "Easy Listening" in capsys.readouterr().out


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
