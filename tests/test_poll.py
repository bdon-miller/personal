from fiftyfm.chart_source import Song
from fiftyfm.poll import (
    MAX_ANSWER_CHARS,
    OTHER_ANSWER,
    answer_text,
    poll_answers,
)

FORTY = [Song(i, f"Song {i}", f"Artist {i}") for i in range(1, 41)]


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
