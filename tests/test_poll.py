from datetime import date

from fakes import FakeSource, FakeSpotify

from fiftyfm.chart_source import Song
from fiftyfm.config import load_config
from fiftyfm.pipeline import run as pipeline_run
from fiftyfm.pipeline import skip as pipeline_skip
from fiftyfm.poll import (
    MAX_ANSWER_CHARS,
    OTHER_ANSWER,
    answer_text,
    build_recap,
    poll_answers,
    recap_text,
    run_poll,
)
from fiftyfm.state import load_state, run_key, save_state

FORTY = [Song(i, f"Song {i}", f"Artist {i}") for i in range(1, 41)]

CFG = load_config()
ENV = {
    "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/tok",
    "LASTFM_API_KEY": "key123",
}
KEY = run_key("hot-100", date(1976, 1, 3))


def seed_state(tmp_path, *, thread_id="99887766", poll_posted=False):
    """A state file that looks like Monday's run already posted a thread."""
    path = tmp_path / "state.json"
    state = load_state(path, default_cursor=date(1976, 1, 3))
    record = {"playlist_url": "u", "matched": 40, "posted": True, "week": 1}
    if thread_id is not None:
        record["thread_id"] = thread_id
    if poll_posted:
        record["poll_posted"] = True
    state.completed[KEY] = record
    state.last_posted_key = KEY
    state.cursor = date(1976, 1, 24)  # already advanced 3 weeks
    save_state(path, state)
    return path


def test_answer_text_joins_title_and_artist():
    assert answer_text(Song(1, "Convoy", "C.W. McCall")) == "Convoy — C.W. McCall"


def test_answer_text_truncates_to_the_discord_limit():
    song = Song(1, "A Very Long Song Title That Simply Will Not Fit At All",
                "An Equally Long Artist Name Here")
    text = answer_text(song)
    assert len(text) == MAX_ANSWER_CHARS
    assert text.endswith("…")


def test_answer_text_leaves_short_titles_untouched():
    text = answer_text(Song(1, "Convoy", "C.W. McCall"))
    assert not text.endswith("…")


def test_poll_answers_takes_top_nine_by_playcount_plus_other():
    counts = {40: 900, 39: 800, 38: 700, 37: 600, 36: 500,
              35: 400, 34: 300, 33: 200, 32: 100}
    answers = poll_answers(FORTY, counts)
    assert len(answers) == 10
    assert answers[0] == "Song 40 — Artist 40"
    assert answers[8] == "Song 32 — Artist 32"
    assert answers[9] == OTHER_ANSWER


def test_poll_answers_falls_back_to_chart_order_without_counts():
    answers = poll_answers(FORTY, {})
    assert answers[:3] == [
        "Song 1 — Artist 1",
        "Song 2 — Artist 2",
        "Song 3 — Artist 3",
    ]
    assert answers[-1] == OTHER_ANSWER


def test_poll_answers_never_exceeds_ten_entries():
    counts = {i: 1000 - i for i in range(1, 41)}
    assert len(poll_answers(FORTY, counts)) == 10


def test_poll_answers_handles_short_charts():
    # Early Disco charts run 30 positions; a hypothetical stub chart is shorter.
    answers = poll_answers(FORTY[:4], {})
    assert len(answers) == 5
    assert answers[-1] == OTHER_ANSWER


def test_run_poll_posts_two_polls_into_the_thread(tmp_path):
    path = seed_state(tmp_path)
    source = FakeSource(FORTY)
    posted = []
    code = run_poll(
        CFG, path, ENV, source,
        playcounts_fn=lambda api_key, songs: {1: 500, 2: 400},
        post=lambda url, **k: (posted.append(k), f"msg{len(posted)}")[1],
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    assert source.fetched[0].slug == "hot-100"
    assert source.fetched[1] == date(1976, 1, 3)
    assert len(posted) == 2
    assert posted[0]["thread_id"] == "99887766"
    assert posted[0]["question"] == "Favorite song of the week?"
    assert posted[1]["question"] == "Least favorite song of the week?"
    assert posted[0]["answers"] == posted[1]["answers"]
    assert posted[0]["answers"][0] == "Song 1 — Artist 1"
    assert posted[0]["answers"][-1] == OTHER_ANSWER
    st = load_state(path, default_cursor=date(1976, 1, 3))
    assert st.completed[KEY]["poll_posted"] is True
    assert st.completed[KEY]["poll_message_ids"] == {
        "favorite": "msg1",
        "least_favorite": "msg2",
    }


def test_run_poll_is_idempotent(tmp_path):
    path = seed_state(tmp_path, poll_posted=True)
    code = run_poll(
        CFG, path, ENV, FakeSource(FORTY),
        playcounts_fn=lambda api_key, songs: {},
        post=lambda url, **k: (_ for _ in ()).throw(
            AssertionError("must not double-post")
        ),
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0


def test_run_poll_skips_threads_without_an_id(tmp_path, capsys):
    path = seed_state(tmp_path, thread_id=None)
    code = run_poll(
        CFG, path, ENV, FakeSource(FORTY),
        playcounts_fn=lambda api_key, songs: {},
        post=lambda url, **k: (_ for _ in ()).throw(
            AssertionError("no thread to post into")
        ),
        notify_failure=lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("not a failure")
        ),
    )
    assert code == 0
    assert "thread_id" in capsys.readouterr().out


def test_run_poll_noop_without_last_posted_key(tmp_path, capsys):
    path = tmp_path / "state.json"
    code = run_poll(
        CFG, path, ENV, FakeSource(FORTY),
        playcounts_fn=lambda api_key, songs: {},
        post=lambda url, **k: (_ for _ in ()).throw(AssertionError("nothing to poll")),
        notify_failure=lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("not a failure")
        ),
    )
    assert code == 0
    assert "no posted thread" in capsys.readouterr().out


def test_run_poll_reports_fetch_failure(tmp_path):
    from fiftyfm.chart_source import ChartFetchError

    path = seed_state(tmp_path)
    failures = []
    code = run_poll(
        CFG, path, ENV, FakeSource(exc=ChartFetchError("nope")),
        playcounts_fn=lambda api_key, songs: {},
        post=lambda url, **k: "msg",
        notify_failure=lambda url, msg, **k: failures.append(msg),
    )
    assert code == 1
    assert "nope" in failures[0]


def test_run_poll_dry_run_posts_nothing(tmp_path, capsys):
    path = seed_state(tmp_path)
    code = run_poll(
        CFG, path, ENV, FakeSource(FORTY), dry_run=True,
        playcounts_fn=lambda api_key, songs: {},
        post=lambda url, **k: (_ for _ in ()).throw(AssertionError("no post")),
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "Song 1 — Artist 1" in out
    assert OTHER_ANSWER in out
    st = load_state(path, default_cursor=date(1976, 1, 3))
    assert "poll_posted" not in st.completed[KEY]


def test_run_poll_skips_an_empty_chart(tmp_path, capsys):
    # poll_answers([], {}) would otherwise return a single-option poll
    # whose only answer is the "Other" escape hatch.
    path = seed_state(tmp_path)
    code = run_poll(
        CFG, path, ENV, FakeSource(songs=[]),
        playcounts_fn=lambda api_key, songs: {},
        post=lambda url, **k: (_ for _ in ()).throw(
            AssertionError("must not post a one-answer poll")
        ),
        notify_failure=lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("not a failure")
        ),
    )
    assert code == 0
    assert "empty" in capsys.readouterr().out
    st = load_state(path, default_cursor=date(1976, 1, 3))
    assert "poll_posted" not in st.completed[KEY]


def test_run_poll_slices_to_top_40(tmp_path):
    # The source returns 100 rows; only the 40 that were posted may be polled.
    long_chart = [Song(i, f"Song {i}", f"Artist {i}") for i in range(1, 101)]
    path = seed_state(tmp_path)
    posted = []
    run_poll(
        CFG, path, ENV, FakeSource(songs=long_chart),
        playcounts_fn=lambda api_key, songs: {s.rank: s.rank for s in songs},
        post=lambda url, **k: (posted.append(k), "msg")[1],
        notify_failure=lambda *a, **k: None,
    )
    # Highest playcount among ranks 1-40 is rank 40, not rank 100.
    assert posted[0]["answers"][0] == "Song 40 — Artist 40"


def test_recap_text_names_both_winners():
    text = recap_text(
        {"Convoy — C.W. McCall": 4, "Love Hangover — Diana Ross": 11},
        {"Convoy — C.W. McCall": 9, "Love Hangover — Diana Ross": 1},
    )
    assert "Love Hangover — Diana Ross (11 votes)" in text
    assert "Convoy — C.W. McCall (9 votes)" in text
    assert "Favorite" in text and "Least favorite" in text


def test_recap_text_uses_singular_vote():
    text = recap_text({"Convoy — C.W. McCall": 1}, {})
    assert "(1 vote)" in text
    assert "votes" not in text


def test_recap_text_none_when_nobody_voted():
    assert recap_text({"Convoy — C.W. McCall": 0}, {}) is None
    assert recap_text({}, {}) is None


def test_recap_text_breaks_ties_by_answer_order():
    # Dict order follows the poll's answer order, so the higher-placed
    # answer wins a tie.
    text = recap_text({"First — A": 3, "Second — B": 3}, {})
    assert "First — A (3 votes)" in text
    assert "Second — B" not in text


def test_build_recap_reads_both_polls(tmp_path):
    path = seed_state(tmp_path, poll_posted=True)
    state = load_state(path, default_cursor=date(1976, 1, 3))
    state.completed[KEY]["poll_message_ids"] = {
        "favorite": "m1", "least_favorite": "m2",
    }
    fetched = []

    def fake_fetch(url, *, thread_id, message_id):
        fetched.append((thread_id, message_id))
        if message_id == "m1":
            return {"Song 1 — Artist 1": 12}, True
        return {"Song 2 — Artist 2": 9}, True

    text = build_recap(state, "https://discord.com/api/webhooks/1/tok",
                       fetch_results=fake_fetch)
    assert "Song 1 — Artist 1 (12 votes)" in text
    assert "Song 2 — Artist 2 (9 votes)" in text
    assert fetched == [("99887766", "m1"), ("99887766", "m2")]


def test_build_recap_none_when_not_finalized(tmp_path):
    path = seed_state(tmp_path, poll_posted=True)
    state = load_state(path, default_cursor=date(1976, 1, 3))
    state.completed[KEY]["poll_message_ids"] = {
        "favorite": "m1", "least_favorite": "m2",
    }
    assert build_recap(
        state, "https://discord.com/api/webhooks/1/tok",
        fetch_results=lambda url, **k: ({"Song 1 — Artist 1": 3}, False),
    ) is None


def test_build_recap_none_when_fetch_fails(tmp_path):
    path = seed_state(tmp_path, poll_posted=True)
    state = load_state(path, default_cursor=date(1976, 1, 3))
    state.completed[KEY]["poll_message_ids"] = {
        "favorite": "m1", "least_favorite": "m2",
    }

    def boom(url, **k):
        raise RuntimeError("discord is down")

    assert build_recap(
        state, "https://discord.com/api/webhooks/1/tok", fetch_results=boom
    ) is None


def test_build_recap_none_without_poll_message_ids(tmp_path):
    path = seed_state(tmp_path)
    state = load_state(path, default_cursor=date(1976, 1, 3))
    assert build_recap(
        state, "https://discord.com/api/webhooks/1/tok",
        fetch_results=lambda url, **k: (_ for _ in ()).throw(
            AssertionError("nothing to fetch")
        ),
    ) is None


def test_skip_then_run_poll_then_run_compose_through_one_state_file(tmp_path):
    """skip moves last_posted_key to the replacement thread specifically so
    Saturday's polls target it and the next Monday recaps it, not the
    superseded original. Task 3 only tested that the field moves; this
    drives run_poll and the next pipeline_run for real against one state
    file and checks what they actually did with it - poll.py and
    pipeline.py have no compile-time coupling, so a break here is silent.
    """
    state_path = tmp_path / "state.json"

    # Monday: the chart run posts a thread nobody wants.
    code = pipeline_run(
        CFG, state_path, ENV, FakeSource(FORTY), FakeSpotify(),
        today=date(2026, 8, 3),  # week 1 -> hot-100
        notify=lambda *a, **k: "tid-original",
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    original_key = run_key("hot-100", date(1976, 1, 3))

    # The operator skips it; last_posted_key moves to the replacement.
    code = pipeline_skip(
        CFG, state_path, ENV, FakeSource(FORTY), FakeSpotify(),
        today=date(2026, 8, 3),
        notify=lambda *a, **k: "tid-replacement",
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    st = load_state(state_path, default_cursor=date(1976, 1, 3))
    replacement_key = st.last_posted_key
    assert replacement_key != original_key
    assert st.completed[replacement_key]["thread_id"] == "tid-replacement"

    # Saturday: polls must land in the replacement's thread, not the
    # original's.
    posted = []
    code = run_poll(
        CFG, state_path, ENV, FakeSource(FORTY),
        playcounts_fn=lambda api_key, songs: {},
        post=lambda url, **k: (posted.append(k), f"msg{len(posted)}")[1],
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    assert posted[0]["thread_id"] == "tid-replacement"
    st = load_state(state_path, default_cursor=date(1976, 1, 3))
    ids = st.completed[replacement_key]["poll_message_ids"]
    assert ids == {"favorite": "msg1", "least_favorite": "msg2"}
    assert st.completed[original_key].get("poll_posted") is not True

    # Next Monday: the recap must derive from the replacement's poll
    # message ids and reach notify.
    week2_posts = []
    code = pipeline_run(
        CFG, state_path, ENV, FakeSource(FORTY), FakeSpotify(),
        today=date(2026, 8, 10),  # week 2
        notify=lambda *a, **k: week2_posts.append(k) or "tid-week2",
        notify_failure=lambda *a, **k: None,
        fetch_results=lambda url, **k: (
            ({"Song 1 — Artist 1": 12}, True)
            if k["message_id"] == ids["favorite"]
            else ({"Song 2 — Artist 2": 9}, True)
        ),
    )
    assert code == 0
    assert "Song 1 — Artist 1 (12 votes)" in week2_posts[0]["recap"]


def test_pipeline_and_run_poll_compose_through_one_state_file(tmp_path):
    """pipeline.run (Monday) and run_poll (Saturday) share one state.json
    in production. Nothing previously exercised them back-to-back against
    a single file - the gap that let two writers race on save_state's
    temp path through review. This drives both entry points for real,
    across two simulated weeks, and checks the state each actually wrote.
    """
    state_path = tmp_path / "state.json"

    # Week 1 Monday: the chart run posts a new thread.
    week1_posts = []
    code = pipeline_run(
        CFG, state_path, ENV, FakeSource(FORTY), FakeSpotify(),
        today=date(2026, 8, 3),  # week 1 -> hot-100
        notify=lambda *a, **k: week1_posts.append(k) or "99887766",
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    week1_key = run_key("hot-100", date(1976, 1, 3))
    st = load_state(state_path, default_cursor=date(1976, 1, 3))
    assert st.last_posted_key == week1_key
    assert st.completed[week1_key]["thread_id"] == "99887766"
    assert st.completed[week1_key]["posted"] is True
    cursor_after_week1 = st.cursor

    # Week 1 Saturday: the poll run posts into that thread and writes its
    # own record back via save_state - without clobbering what the chart
    # run just wrote (the lost-update failure mode Fix 1 addresses).
    posted = []
    code = run_poll(
        CFG, state_path, ENV, FakeSource(FORTY),
        playcounts_fn=lambda api_key, songs: {},
        post=lambda url, **k: (posted.append(k), f"msg{len(posted)}")[1],
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    st = load_state(state_path, default_cursor=date(1976, 1, 3))
    assert st.completed[week1_key]["poll_posted"] is True
    ids = st.completed[week1_key]["poll_message_ids"]
    assert ids == {"favorite": "msg1", "least_favorite": "msg2"}
    # Lost-update assertion: the poll run loaded state after the chart run
    # saved, so its own save must still carry the chart run's posted=True
    # and advanced cursor forward - not republish the pre-chart-run values.
    assert st.completed[week1_key]["posted"] is True
    assert st.cursor == cursor_after_week1

    # Week 2 Monday: the new chart run recaps week 1's now-finalized polls,
    # using the exact message ids run_poll actually wrote above.
    week2_posts = []
    code = pipeline_run(
        CFG, state_path, ENV, FakeSource(FORTY), FakeSpotify(),
        today=date(2026, 8, 10),  # week 2
        notify=lambda *a, **k: week2_posts.append(k) or "111",
        notify_failure=lambda *a, **k: None,
        fetch_results=lambda url, **k: (
            ({"Song 1 — Artist 1": 12}, True)
            if k["message_id"] == ids["favorite"]
            else ({"Song 2 — Artist 2": 9}, True)
        ),
    )
    assert code == 0
    assert "Song 1 — Artist 1 (12 votes)" in week2_posts[0]["recap"]
    st = load_state(state_path, default_cursor=date(1976, 1, 3))
    # Week 2 at this cursor resolves to "soul" (mainstream-rock isn't
    # available until 1981), per charts.toml's slot priority list.
    week2_key = run_key("soul", date(1976, 1, 24))
    assert st.last_posted_key == week2_key
