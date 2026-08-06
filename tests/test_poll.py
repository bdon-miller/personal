from datetime import date

from fiftyfm.chart_source import Song
from fiftyfm.config import load_config
from fiftyfm.poll import (
    MAX_ANSWER_CHARS,
    OTHER_ANSWER,
    answer_text,
    poll_answers,
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


class FakeSource:
    def __init__(self, songs=None, exc=None):
        self.songs = songs if songs is not None else FORTY
        self.exc = exc
        self.fetched = None

    def fetch(self, slug, chart_date):
        if self.exc:
            raise self.exc
        self.fetched = (slug, chart_date)
        return self.songs


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
    source = FakeSource()
    posted = []
    code = run_poll(
        CFG, path, ENV, source,
        playcounts_fn=lambda api_key, songs: {1: 500, 2: 400},
        post=lambda url, **k: (posted.append(k), f"msg{len(posted)}")[1],
        notify_failure=lambda *a, **k: None,
    )
    assert code == 0
    assert source.fetched == ("hot-100", date(1976, 1, 3))
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
        CFG, path, ENV, FakeSource(),
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
        CFG, path, ENV, FakeSource(),
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
        CFG, path, ENV, FakeSource(),
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
        CFG, path, ENV, FakeSource(), dry_run=True,
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
