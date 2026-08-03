from datetime import date

import pytest

from fiftyfm.chart_source import Song
from fiftyfm.discord import DiscordError, post_failure, post_playlist, songs_csv


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = ""


class FakeSession:
    def __init__(self, status_code=200, exc=None):
        self.status_code = status_code
        self.exc = exc
        self.calls = []

    def post(self, url, **kwargs):
        if self.exc:
            raise self.exc
        self.calls.append((url, kwargs))
        return FakeResponse(self.status_code)


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
