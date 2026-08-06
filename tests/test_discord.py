from datetime import date

import pytest

from fiftyfm.chart_source import Song
from fiftyfm.discord import (
    DiscordError,
    get_poll_results,
    post_failure,
    post_playlist,
    post_poll,
    songs_csv,
)


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, status_code=200, exc=None, payload=None):
        self.status_code = status_code
        self.exc = exc
        self.payload = payload if payload is not None else {"channel_id": "555"}
        self.calls = []

    def post(self, url, **kwargs):
        if self.exc:
            raise self.exc
        self.calls.append((url, kwargs))
        return FakeResponse(self.status_code, self.payload)

    def get(self, url, **kwargs):
        if self.exc:
            raise self.exc
        self.calls.append((url, kwargs))
        return FakeResponse(self.status_code, self.payload)


SONGS = [Song(i, f"Song {i}", f"Artist {i}") for i in range(1, 41)]


def test_post_playlist_builds_forum_post():
    session = FakeSession()
    post_playlist(
        "https://discord.com/api/webhooks/1/tok",
        thread_title="Billboard Hot 100 Top 40 — March 6, 1976",
        chart_name="Hot 100",
        chart_date=date(1976, 3, 6),
        songs=SONGS,
        matched=38,
        playlist_url="https://open.spotify.com/playlist/pl1",
        session=session,
    )
    url, kwargs = session.calls[0]
    assert url == "https://discord.com/api/webhooks/1/tok?wait=true"
    body = kwargs["json"]
    assert body["thread_name"] == "Billboard Hot 100 Top 40 — March 6, 1976"
    embed = body["embeds"][0]
    assert "Song 1" in embed["description"]          # top-5 teaser
    assert "Song 6" not in embed["description"]
    assert "38/40" in embed["description"]
    assert "open.spotify.com" in embed["description"]
    assert "tunemymusic.com" in embed["description"]


def test_post_playlist_raises_on_error():
    session = FakeSession(status_code=403)
    with pytest.raises(DiscordError):
        post_playlist(
            "https://discord.com/api/webhooks/1/tok",
            thread_title="t",
            chart_name="Hot 100",
            chart_date=date(1976, 3, 6),
            songs=SONGS,
            matched=40,
            playlist_url="u",
            session=session,
        )


def test_post_failure_swallows_exceptions():
    session = FakeSession(exc=ConnectionError("down"))
    post_failure("https://discord.com/api/webhooks/1/tok", "boom", session=session)


def test_songs_csv_format():
    csv_text = songs_csv([Song(1, 'Convoy', 'C.W. McCall'),
                          Song(2, 'Theme From "Mahogany"', "Diana Ross")])
    lines = csv_text.splitlines()
    assert lines[0] == "Track name,Artist name"
    assert lines[1] == "Convoy,C.W. McCall"
    assert lines[2] == '"Theme From ""Mahogany""",Diana Ross'


def test_post_playlist_attaches_csv_as_multipart():
    session = FakeSession()
    post_playlist(
        "https://discord.com/api/webhooks/1/tok",
        thread_title="Billboard Hot 100 Top 40 — March 6, 1976",
        chart_name="Hot 100",
        chart_date=date(1976, 3, 6),
        songs=SONGS,
        matched=38,
        playlist_url="https://open.spotify.com/playlist/pl1",
        csv_filename="hot-100-1976-03-06.csv",
        csv_data=b"Track name,Artist name\nSong 1,Artist 1\n",
        session=session,
    )
    url, kwargs = session.calls[0]
    assert url == "https://discord.com/api/webhooks/1/tok?wait=true"
    assert "json" not in kwargs
    import json as jsonlib

    body = jsonlib.loads(kwargs["data"]["payload_json"])
    assert body["thread_name"] == "Billboard Hot 100 Top 40 — March 6, 1976"
    assert "attached CSV" in body["embeds"][0]["description"]
    filename, data, mime = kwargs["files"]["files[0]"]
    assert filename == "hot-100-1976-03-06.csv"
    assert data.startswith(b"Track name")
    assert mime == "text/csv"


def test_post_playlist_appends_wait_param_when_query_string_present():
    session = FakeSession()
    post_playlist(
        "https://discord.com/api/webhooks/1/tok?thread_id=99",
        thread_title="t",
        chart_name="Hot 100",
        chart_date=date(1976, 3, 6),
        songs=SONGS,
        matched=40,
        playlist_url="u",
        session=session,
    )
    url, _kwargs = session.calls[0]
    assert url == "https://discord.com/api/webhooks/1/tok?thread_id=99&wait=true"


def test_post_failure_appends_wait_param_when_query_string_present():
    session = FakeSession()
    post_failure(
        "https://discord.com/api/webhooks/1/tok?thread_id=99", "boom", session=session
    )
    url, _kwargs = session.calls[0]
    assert url == "https://discord.com/api/webhooks/1/tok?thread_id=99&wait=true"


def test_post_playlist_returns_thread_id():
    session = FakeSession(payload={"id": "1", "channel_id": "99887766"})
    thread_id = post_playlist(
        "https://discord.com/api/webhooks/1/tok",
        thread_title="t",
        chart_name="Hot 100",
        chart_date=date(1976, 3, 6),
        songs=SONGS,
        matched=40,
        playlist_url="u",
        session=session,
    )
    assert thread_id == "99887766"


def test_post_playlist_returns_none_without_channel_id():
    session = FakeSession(payload={"id": "1"})
    assert post_playlist(
        "https://discord.com/api/webhooks/1/tok",
        thread_title="t",
        chart_name="Hot 100",
        chart_date=date(1976, 3, 6),
        songs=SONGS,
        matched=40,
        playlist_url="u",
        session=session,
    ) is None


def test_post_poll_builds_poll_payload():
    session = FakeSession(payload={"id": "777", "channel_id": "99"})
    message_id = post_poll(
        "https://discord.com/api/webhooks/1/tok",
        thread_id="99887766",
        question="Favorite song of the week?",
        answers=["Convoy — C.W. McCall", "Other — reply in thread"],
        session=session,
    )
    assert message_id == "777"
    url, kwargs = session.calls[0]
    assert url == (
        "https://discord.com/api/webhooks/1/tok"
        "?thread_id=99887766&wait=true"
    )
    poll = kwargs["json"]["poll"]
    assert poll["question"] == {"text": "Favorite song of the week?"}
    assert poll["allow_multiselect"] is True
    assert poll["duration"] == 48
    assert poll["layout_type"] == 1
    assert poll["answers"] == [
        {"poll_media": {"text": "Convoy — C.W. McCall"}},
        {"poll_media": {"text": "Other — reply in thread"}},
    ]


def test_post_poll_sends_no_emoji_keys():
    session = FakeSession(payload={"id": "777"})
    post_poll(
        "https://discord.com/api/webhooks/1/tok",
        thread_id="99",
        question="Favorite song of the week?",
        answers=["Convoy — C.W. McCall"],
        session=session,
    )
    answer = session.calls[0][1]["json"]["poll"]["answers"][0]
    assert "emoji" not in answer["poll_media"]


def test_post_poll_replaces_existing_query_string():
    session = FakeSession(payload={"id": "777"})
    post_poll(
        "https://discord.com/api/webhooks/1/tok?thread_id=OLD",
        thread_id="NEW",
        question="q",
        answers=["a"],
        session=session,
    )
    url, _kwargs = session.calls[0]
    assert url == "https://discord.com/api/webhooks/1/tok?thread_id=NEW&wait=true"


def test_post_poll_raises_on_error():
    session = FakeSession(status_code=400, payload={"message": "bad poll"})
    with pytest.raises(DiscordError):
        post_poll(
            "https://discord.com/api/webhooks/1/tok",
            thread_id="99",
            question="q",
            answers=["a"],
            session=session,
        )


POLL_MESSAGE = {
    "id": "777",
    "poll": {
        "question": {"text": "Favorite song of the week?"},
        "answers": [
            {"answer_id": 1, "poll_media": {"text": "Convoy — C.W. McCall"}},
            {"answer_id": 2, "poll_media": {"text": "Love Hangover — Diana Ross"}},
            {"answer_id": 3, "poll_media": {"text": "Other — reply in thread"}},
        ],
        "results": {
            "is_finalized": True,
            "answer_counts": [
                {"id": 1, "count": 4, "me_voted": False},
                {"id": 2, "count": 11, "me_voted": False},
            ],
        },
    },
}


def test_get_poll_results_maps_counts_to_answer_text():
    session = FakeSession(payload=POLL_MESSAGE)
    counts, finalized = get_poll_results(
        "https://discord.com/api/webhooks/1/tok",
        thread_id="99887766",
        message_id="777",
        session=session,
    )
    assert finalized is True
    assert counts == {
        "Convoy — C.W. McCall": 4,
        "Love Hangover — Diana Ross": 11,
        "Other — reply in thread": 0,  # no count row means zero votes
    }


def test_get_poll_results_uses_messages_path_with_thread_id():
    session = FakeSession(payload=POLL_MESSAGE)
    get_poll_results(
        "https://discord.com/api/webhooks/1/tok?thread_id=OLD",
        thread_id="99887766",
        message_id="777",
        session=session,
    )
    url, _kwargs = session.calls[0]
    assert url == (
        "https://discord.com/api/webhooks/1/tok/messages/777"
        "?thread_id=99887766"
    )


def test_get_poll_results_reports_unfinalized():
    payload = {"poll": {"answers": [], "results": {"is_finalized": False,
                                                   "answer_counts": []}}}
    session = FakeSession(payload=payload)
    counts, finalized = get_poll_results(
        "https://discord.com/api/webhooks/1/tok",
        thread_id="99",
        message_id="777",
        session=session,
    )
    assert counts == {}
    assert finalized is False


def test_get_poll_results_raises_on_error():
    session = FakeSession(status_code=404, payload={"message": "Unknown Message"})
    with pytest.raises(DiscordError):
        get_poll_results(
            "https://discord.com/api/webhooks/1/tok",
            thread_id="99",
            message_id="777",
            session=session,
        )
