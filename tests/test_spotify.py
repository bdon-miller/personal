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


def test_normalize_keeps_with_in_title():
    # `with` is part of the title far more often than it introduces a
    # feature credit; stripping it broke both Billboard and J-pop titles.
    assert normalize("Dancing With Myself") == "dancing with myself"
    assert normalize("Live With Me") == "live with me"
    assert normalize("真夜中のドア～stay with me") == "真夜中のドア~stay with me"


def test_normalize_still_strips_feat():
    assert normalize("Boogie Fever feat. Someone") == "boogie fever"
    assert normalize("Boogie Fever featuring Someone") == "boogie fever"


def test_normalize_japanese_punctuation():
    # Spotify returned "Mayonaka no Door~stay with me" with an ASCII tilde,
    # so align the full-width form to it.
    assert normalize("真夜中のドア～stay") == "真夜中のドア~stay"
    assert normalize("東京　ららばい") == "東京 ららばい"


def test_normalize_keeps_katakana_middle_dot():
    # Deliberately NOT normalized: a live probe matched
    # プラスティック・ラブ strictly, so Spotify stores the ・ as-is and
    # rewriting it to a space would break a case that currently works.
    assert normalize("プラスティック・ラブ") == "プラスティック・ラブ"


def test_is_blocked_rejects_karaoke_and_covers():
    from fiftyfm.spotify import is_blocked
    assert is_blocked("リンダ リンダ(原曲歌手:THE BLUE HEARTS)")
    assert is_blocked("世界に一つだけの花[ガイド無しカラオケ]")
    assert is_blocked("Lemon (Instrumental)")
    assert not is_blocked("リンダ リンダ")
    assert not is_blocked("Plastic Love")


def test_find_track_skips_blocked_results_when_strict_only():
    # is_blocked() filtering is gated on strict_only (Oricon); see
    # test_find_track_returns_first_result_even_if_blocked_looking below
    # for proof that Billboard's default behavior is unaffected.
    session = FakeSession()
    client = make_client(session)
    session.handlers[("GET", "https://api.spotify.com/v1/search")] = (
        lambda kw: FakeResponse(200, {"tracks": {"items": [
            {"uri": "spotify:track:karaoke",
             "name": "リンダ リンダ(原曲歌手:THE BLUE HEARTS)",
             "artists": [{"name": "歌っちゃ王"}]},
            {"uri": "spotify:track:real", "name": "リンダ リンダ",
             "artists": [{"name": "THE BLUE HEARTS"}]},
        ]}})
    )
    uri = client.find_track(
        Song(1, "リンダリンダ", "THE BLUE HEARTS"), strict_only=True
    )
    assert uri == "spotify:track:real"


def test_find_track_returns_first_result_even_if_blocked_looking():
    # strict_only=False is Billboard's default. A Billboard instrumental
    # chart entry's own correct top result can legitimately contain
    # "(Instrumental)" — is_blocked() must not apply here, or the right
    # track gets rejected in favor of a cover/re-record. This proves
    # Billboard behavior is unchanged by Oricon's strict_only gating.
    session = FakeSession()
    client = make_client(session)
    session.handlers[("GET", "https://api.spotify.com/v1/search")] = (
        lambda kw: FakeResponse(200, {"tracks": {"items": [
            {"uri": "spotify:track:instrumental-but-correct",
             "name": "Song Title (Instrumental)",
             "artists": [{"name": "Some Artist"}]},
            {"uri": "spotify:track:wrong-cover", "name": "Song Title",
             "artists": [{"name": "Cover Band"}]},
        ]}})
    )
    uri = client.find_track(Song(1, "Song Title", "Some Artist"))
    assert uri == "spotify:track:instrumental-but-correct"


def test_find_track_strict_only_skips_loose_query():
    session = FakeSession()
    client = make_client(session)
    seen = []

    def handler(kw):
        seen.append(kw["params"]["q"])
        return FakeResponse(200, {"tracks": {"items": []}})

    session.handlers[("GET", "https://api.spotify.com/v1/search")] = handler
    assert client.find_track(Song(1, "テルーの唄", "手嶌葵"), strict_only=True) is None
    assert all(q.startswith("track:") for q in seen), seen


def test_find_track_strict_only_returns_none_when_all_blocked():
    session = FakeSession()
    client = make_client(session)
    session.handlers[("GET", "https://api.spotify.com/v1/search")] = (
        lambda kw: FakeResponse(200, {"tracks": {"items": [
            {"uri": "spotify:track:k", "name": "テルーの唄 (原曲歌手:手嶌葵)",
             "artists": [{"name": "歌っちゃ王"}]},
        ]}})
    )
    assert client.find_track(Song(1, "テルーの唄", "手嶌葵"), strict_only=True) is None
