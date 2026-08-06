import json
from datetime import date

from fakes import FakeSource, FakeSpotify

from fiftyfm.chart_source import ChartFetchError, Song
from fiftyfm.config import load_config
from fiftyfm.pipeline import playlist_name, run
from fiftyfm.state import State, load_state, run_key, save_state

CFG = load_config()
ENV = {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/tok"}
SONGS = [Song(i, f"Song {i}", f"Artist {i}") for i in range(1, 101)]


def test_playlist_name():
    assert (
        playlist_name("Billboard", "Hot 100", date(1976, 3, 6), 40)
        == "Billboard Hot 100 Top 40 — March 6, 1976"
    )


def test_playlist_name_uses_publisher_and_actual_count():
    assert (
        playlist_name(
            "Oricon", "Oricon Weekly Singles (Shōwa)", date(1976, 1, 12), 20
        )
        == "Oricon Oricon Weekly Singles (Shōwa) Top 20 — January 12, 1976"
    )


def test_notify_receives_csv_attachment(tmp_path):
    posts = []
    code = run(
        CFG, tmp_path / "state.json", ENV, FakeSource(SONGS), FakeSpotify(),
        today=date(2026, 8, 3),  # week 1 -> hot-100
        notify=lambda *a, **k: posts.append(k),
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    kwargs = posts[0]
    assert kwargs["csv_filename"] == "hot-100-1976-01-03.csv"
    lines = kwargs["csv_data"].decode().splitlines()
    assert lines[0] == "Track name,Artist name"
    assert lines[1] == "Song 1,Artist 1"
    assert len(lines) == 41  # header + top 40


def test_happy_path_advances_cursor(tmp_path, capsys):
    state_path = tmp_path / "state.json"
    source, spotify = FakeSource(SONGS), FakeSpotify(miss_titles=("Song 7",))
    posts = []
    code = run(
        CFG, state_path, ENV, source, spotify,
        today=date(2026, 8, 3),  # week 1 -> hot-100
        notify=lambda *a, **k: posts.append(k),
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    assert source.fetched[0].slug == "hot-100"
    assert source.fetched[1] == date(1976, 1, 3)
    name, _desc, uris = spotify.created
    assert name == "Billboard Hot 100 Top 40 — January 3, 1976"
    assert len(uris) == 39  # one miss out of top 40
    assert posts[0]["matched"] == 39
    st = load_state(state_path, default_cursor=date(1976, 1, 3))
    assert st.cursor == date(1976, 1, 24)  # advanced 3 weeks
    assert st.completed[run_key("hot-100", date(1976, 1, 3))]["posted"] is True


def test_wildcard_week_increments_index(tmp_path):
    state_path = tmp_path / "state.json"
    # Seed the cursor past 1976-01-12 (oricon-showa's available_from) so the
    # wildcard pool at this chart_date isn't empty - the raw start_date
    # (1976-01-03) predates it by 9 days and has no wildcard chart at all.
    save_state(state_path, State(cursor=date(1976, 1, 24)))
    code = run(
        CFG, state_path, ENV, FakeSource(SONGS), FakeSpotify(),
        today=date(2026, 8, 24),  # week 4 -> wildcard
        notify=lambda *a, **k: None,
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    st = load_state(state_path, default_cursor=date(1976, 1, 3))
    assert st.wildcard_index == 1


def test_replay_of_posted_run_is_noop(tmp_path):
    state_path = tmp_path / "state.json"
    args = dict(
        today=date(2026, 8, 3),
        notify=lambda *a, **k: None,
        notify_failure=lambda *a, **k: None,
    )
    run(CFG, state_path, ENV, FakeSource(SONGS), FakeSpotify(), **args)
    st1 = json.loads(state_path.read_text())
    # simulate operator resetting cursor to replay the same chart-date
    st1["cursor"] = "1976-01-03"
    state_path.write_text(json.dumps(st1))
    spotify = FakeSpotify()
    code = run(CFG, state_path, ENV, FakeSource(SONGS), spotify, **args)
    assert code == 0
    assert spotify.created is None  # nothing re-created


def test_per_song_spotify_error_is_a_miss_not_fatal(tmp_path, capsys):
    state_path = tmp_path / "state.json"
    source = FakeSource(SONGS)
    spotify = FakeSpotify(error_titles=("Song 3",))
    posts = []
    code = run(
        CFG, state_path, ENV, source, spotify,
        today=date(2026, 8, 3),
        notify=lambda *a, **k: posts.append(k),
        notify_failure=lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("run must not be treated as failed")
        ),
    )
    assert code == 0
    assert posts[0]["matched"] == 39  # one miss due to the per-song error
    err = capsys.readouterr().err
    assert "Song 3" in err


def test_fetch_failure_reports_and_returns_1(tmp_path):
    state_path = tmp_path / "state.json"
    failures = []
    code = run(
        CFG, state_path, ENV,
        FakeSource(exc=ChartFetchError("nope")), FakeSpotify(),
        today=date(2026, 8, 3),
        notify=lambda *a, **k: None,
        notify_failure=lambda url, msg, **k: failures.append(msg),
    )
    assert code == 1
    assert "nope" in failures[0]
    assert not state_path.exists()  # cursor untouched


def test_dry_run_writes_nothing(tmp_path, capsys):
    state_path = tmp_path / "state.json"
    code = run(
        CFG, state_path, ENV, FakeSource(SONGS), None,
        today=date(2026, 8, 3), dry_run=True,
        notify=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no post")),
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    assert not state_path.exists()
    out = capsys.readouterr().out
    assert "Billboard Hot 100 Top 40 — January 3, 1976" in out
    assert "Song 1" in out


def test_discord_failure_then_retry_reuses_playlist(tmp_path):
    state_path = tmp_path / "state.json"
    source = FakeSource(SONGS)
    spotify_first = FakeSpotify(miss_titles=("Song 7",))

    # First run: playlist created successfully, but Discord post fails
    class DiscordError(Exception):
        pass

    def failing_notify(*a, **k):
        raise DiscordError("discord is down")

    code = run(
        CFG, state_path, ENV, source, spotify_first,
        today=date(2026, 8, 3),
        notify=failing_notify,
        notify_failure=lambda url, msg, **k: None,
    )
    assert code == 1  # failure returns 1

    # State file should exist with playlist_url, matched count, and posted=False
    st = json.loads(state_path.read_text())
    key = run_key("hot-100", date(1976, 1, 3))
    assert (
        st["completed"][key]["playlist_url"]
        == "https://open.spotify.com/playlist/pl1"
    )
    assert st["completed"][key]["matched"] == 39  # original match count preserved
    assert st["completed"][key]["posted"] is False
    assert st["cursor"] == "1976-01-03"  # cursor NOT advanced

    # Second run: retry with working Discord
    posts = []
    spotify_second = FakeSpotify()  # fresh instance, no misses
    code = run(
        CFG, state_path, ENV, source, spotify_second,
        today=date(2026, 8, 3),
        notify=lambda *a, **k: posts.append(k),
        notify_failure=lambda url, msg, **k: None,
    )
    assert code == 0
    assert spotify_second.created is None  # playlist NOT recreated
    assert posts[0]["matched"] == 39  # original matched count reported
    st = load_state(state_path, default_cursor=date(1976, 1, 3))
    assert st.completed[key]["posted"] is True
    assert st.cursor == date(1976, 1, 24)  # cursor NOW advanced


def test_cross_week_retry_resumes_same_chart_not_a_new_one(tmp_path):
    state_path = tmp_path / "state.json"
    source = FakeSource(SONGS)
    spotify_first = FakeSpotify()

    class DiscordError(Exception):
        pass

    def failing_notify(*a, **k):
        raise DiscordError("discord is down")

    # Seed the cursor past 1976-01-12 (oricon-showa's available_from) so the
    # wildcard pool at this chart_date isn't empty - the raw start_date
    # (1976-01-03) predates it by 9 days and has no wildcard chart at all.
    save_state(state_path, State(cursor=date(1976, 1, 24)))

    # First run: week 4 -> wildcard chart (oricon-showa at this cursor).
    # Playlist gets created but the Discord post fails.
    code = run(
        CFG, state_path, ENV, source, spotify_first,
        today=date(2026, 8, 24),  # week 4
        notify=failing_notify,
        notify_failure=lambda url, msg, **k: None,
    )
    assert code == 1

    wildcard_key = run_key("oricon-showa", date(1976, 1, 24))
    st = json.loads(state_path.read_text())
    assert wildcard_key in st["completed"]
    assert st["completed"][wildcard_key]["posted"] is False
    assert st["cursor"] == "1976-01-24"  # cursor NOT advanced

    # Second run: the timer next fires in week 1 of the following month.
    # Without the fix this would select hot-100 for the same chart_date,
    # creating a second public playlist and orphaning the wildcard record.
    posts = []
    spotify_second = FakeSpotify()
    code = run(
        CFG, state_path, ENV, source, spotify_second,
        today=date(2026, 9, 7),  # week 1
        notify=lambda *a, **k: posts.append(k),
        notify_failure=lambda url, msg, **k: None,
    )
    assert code == 0
    assert spotify_second.created is None  # no new playlist created

    st = load_state(state_path, default_cursor=date(1976, 1, 3))
    hot100_key = run_key("hot-100", date(1976, 1, 24))
    assert hot100_key not in st.completed  # no duplicate playlist/record
    assert st.completed[wildcard_key]["posted"] is True  # original record resumed
    assert posts[0]["chart_name"] == "Oricon Weekly Singles (Shōwa)"
    assert st.cursor == date(1976, 2, 14)  # cursor advanced after resume


def test_thread_id_and_last_posted_key_are_recorded(tmp_path):
    state_path = tmp_path / "state.json"
    code = run(
        CFG, state_path, ENV, FakeSource(SONGS), FakeSpotify(),
        today=date(2026, 8, 3),  # week 1 -> hot-100
        notify=lambda *a, **k: "99887766",
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    st = load_state(state_path, default_cursor=date(1976, 1, 3))
    key = run_key("hot-100", date(1976, 1, 3))
    assert st.completed[key]["thread_id"] == "99887766"
    assert st.last_posted_key == key


def test_missing_thread_id_is_not_fatal(tmp_path):
    # An older webhook response, or one without a body, still posts fine.
    state_path = tmp_path / "state.json"
    code = run(
        CFG, state_path, ENV, FakeSource(SONGS), FakeSpotify(),
        today=date(2026, 8, 3),
        notify=lambda *a, **k: None,
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    st = load_state(state_path, default_cursor=date(1976, 1, 3))
    key = run_key("hot-100", date(1976, 1, 3))
    assert "thread_id" not in st.completed[key]
    assert st.last_posted_key == key


def test_recap_is_passed_to_the_new_thread(tmp_path):
    state_path = tmp_path / "state.json"
    posts = []
    # First week: post a thread and record a poll against it.
    run(
        CFG, state_path, ENV, FakeSource(SONGS), FakeSpotify(),
        today=date(2026, 8, 3),
        notify=lambda *a, **k: "99887766",
        notify_failure=lambda *a, **k: None,
    )
    st = load_state(state_path, default_cursor=date(1976, 1, 3))
    key = run_key("hot-100", date(1976, 1, 3))
    st.completed[key]["poll_message_ids"] = {
        "favorite": "m1", "least_favorite": "m2",
    }
    save_state(state_path, st)

    # Second week: the recap must reach post_playlist.
    run(
        CFG, state_path, ENV, FakeSource(SONGS), FakeSpotify(),
        today=date(2026, 8, 10),  # week 2
        notify=lambda *a, **k: posts.append(k) or "111",
        notify_failure=lambda *a, **k: None,
        fetch_results=lambda url, **k: (
            ({"Song 1 — Artist 1": 12}, True)
            if k["message_id"] == "m1"
            else ({"Song 2 — Artist 2": 9}, True)
        ),
    )
    assert "Song 1 — Artist 1 (12 votes)" in posts[0]["recap"]


def test_recap_failure_outside_build_recaps_own_try_does_not_fail_the_run(
    tmp_path,
):
    # A recap must never fail the Monday run (design invariant). build_recap
    # only guards its own fetch_results calls internally; a state record
    # that doesn't deserialize as a dict raises AttributeError further down
    # (poll.py's `record.get(...)` / `ids.get(...)` chain), outside that
    # inner try. The call site in pipeline.run must catch that too.
    state_path = tmp_path / "state.json"
    key = run_key("hot-100", date(1976, 1, 3))
    state_path.write_text(
        json.dumps(
            {
                "cursor": "1976-01-24",
                "wildcard_index": 0,
                "completed": {key: "corrupt"},
                "last_posted_key": key,
            }
        )
    )
    posts = []
    code = run(
        CFG, state_path, ENV, FakeSource(SONGS), FakeSpotify(),
        today=date(2026, 8, 10),  # week 2
        notify=lambda *a, **k: posts.append(k) or "111",
        notify_failure=lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("a recap problem must not be treated as a run failure")
        ),
    )
    assert code == 0
    assert posts[0]["recap"] is None
    # The chart post itself must still have gone through despite the corrupt
    # prior record - it is untouched, but the new week's run must proceed.
    st = load_state(state_path, default_cursor=date(1976, 1, 3))
    assert st.completed[key] == "corrupt"  # untouched, not overwritten
    # Week 2 at this cursor resolves to "soul" (mainstream-rock isn't
    # available until 1981), per charts.toml's slot priority list.
    new_key = run_key("soul", date(1976, 1, 24))
    assert st.completed[new_key]["posted"] is True


def test_run_resume_path_ignores_slot_consumed(tmp_path):
    # Fix 4: slot_consumed only governs a *fresh* chart selection. A resume
    # is finishing an in-flight chart from a previous failed post and must
    # keep using its recorded week regardless of any leftover slot_consumed
    # - and must leave that leftover untouched, since it still belongs to
    # whatever future fresh selection has not happened yet.
    state_path = tmp_path / "state.json"
    state = load_state(state_path, default_cursor=date(1976, 1, 3))
    key = run_key("hot-100", date(1976, 1, 3))
    state.completed[key] = {
        "playlist_url": "u", "matched": 40, "posted": False, "week": 1,
    }
    state.slot_consumed = 3
    save_state(state_path, state)

    posts = []
    code = run(
        CFG, state_path, ENV, FakeSource(SONGS), FakeSpotify(),
        today=date(2026, 8, 3),
        notify=lambda *a, **k: posts.append(k) or "tid",
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    assert posts[0]["chart_name"] == "Hot 100"  # resumed at its recorded week
    st = load_state(state_path, default_cursor=date(1976, 1, 3))
    assert st.slot_consumed == 3  # untouched by the resume path


def test_no_recap_on_the_first_ever_run(tmp_path):
    state_path = tmp_path / "state.json"
    posts = []
    code = run(
        CFG, state_path, ENV, FakeSource(SONGS), FakeSpotify(),
        today=date(2026, 8, 3),
        notify=lambda *a, **k: posts.append(k) or "111",
        notify_failure=lambda *a, **k: None,
        fetch_results=lambda url, **k: (_ for _ in ()).throw(
            AssertionError("nothing to recap")
        ),
    )
    assert code == 0
    assert posts[0]["recap"] is None
