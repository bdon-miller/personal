import pytest

from fiftyfm.chart_source import Song
from fiftyfm.spotify import SpotifyClient, SpotifyError, normalize


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []
        self.handlers = {}  # (method, url_prefix) -> callable(kwargs) -> FakeResponse

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for (m, prefix), handler in self.handlers.items():
            if m == method and url.startswith(prefix):
                return handler(kwargs)
        raise AssertionError(f"unexpected {method} {url}")

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)


def make_client(session):
    session.handlers[("POST", "https://accounts.spotify.com/api/token")] = (
        lambda kw: FakeResponse(200, {"access_token": "tok", "expires_in": 3600})
    )
    return SpotifyClient("cid", "csec", "rtok", session=session)


def test_normalize():
    assert normalize("December, 1963 (Oh, What A Night)") == "december, 1963"
    assert normalize("Boogie Fever feat. Someone") == "boogie fever"
    assert normalize("Love  Hurts") == "love hurts"


def test_normalize_strips_double_quotes():
    # Unescaped quotes would break the field-filtered search query
    # (e.g. track:"..."), so they must be stripped rather than passed through.
    assert normalize('The "Killer" Song') == "the killer song"
    assert '"' not in normalize('Rock "N" Roll')


def test_find_track_returns_uri():
    session = FakeSession()
    client = make_client(session)
    session.handlers[("GET", "https://api.spotify.com/v1/search")] = (
        lambda kw: FakeResponse(200, {"tracks": {"items": [
            {"uri": "spotify:track:abc123", "name": "All By Myself",
             "artists": [{"name": "Eric Carmen"}]},
        ]}})
    )
    uri = client.find_track(Song(2, "All By Myself", "Eric Carmen"))
    assert uri == "spotify:track:abc123"


def test_find_track_none_when_no_results():
    session = FakeSession()
    client = make_client(session)
    session.handlers[("GET", "https://api.spotify.com/v1/search")] = (
        lambda kw: FakeResponse(200, {"tracks": {"items": []}})
    )
    assert client.find_track(Song(1, "Obscure B-Side", "Nobody")) is None


def test_create_playlist_flow():
    session = FakeSession()
    client = make_client(session)
    session.handlers[("POST", "https://api.spotify.com/v1/me/playlists")] = (
        lambda kw: FakeResponse(201, {
            "id": "pl1",
            "external_urls": {"spotify": "https://open.spotify.com/playlist/pl1"},
        })
    )
    session.handlers[("POST", "https://api.spotify.com/v1/playlists/pl1/items")] = (
        lambda kw: FakeResponse(201, {"snapshot_id": "snap"})
    )
    url = client.create_playlist("Name", "Desc", ["spotify:track:a", "spotify:track:b"])
    assert url == "https://open.spotify.com/playlist/pl1"
    create_call = next(c for c in session.calls if "/me/playlists" in c[1])
    assert create_call[2]["json"]["public"] is True


def test_token_failure_raises():
    session = FakeSession()
    session.handlers[("POST", "https://accounts.spotify.com/api/token")] = (
        lambda kw: FakeResponse(400, {"error": "invalid_grant"})
    )
    client = SpotifyClient("cid", "csec", "bad", session=session)
    with pytest.raises(SpotifyError):
        client.find_track(Song(1, "x", "y"))
