from fiftyfm.chart_source import Song
from fiftyfm.lastfm import LASTFM_API, playcounts, rank_by_playcount


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, by_track=None, exc=None):
        self.by_track = by_track or {}
        self.exc = exc
        self.calls = []

    def get(self, url, **kwargs):
        if self.exc:
            raise self.exc
        self.calls.append((url, kwargs))
        track = kwargs["params"]["track"]
        if track not in self.by_track:
            return FakeResponse(404, {"error": 6, "message": "Track not found"})
        return FakeResponse(200, {"track": {"playcount": self.by_track[track]}})


SONGS = [
    Song(1, "Convoy", "C.W. McCall"),
    Song(2, "Love Hangover", "Diana Ross"),
    Song(3, "Obscure B-Side", "Nobody"),
]


def test_playcounts_maps_rank_to_int_count():
    session = FakeSession({"Convoy": "1200", "Love Hangover": "34000"})
    counts = playcounts("key123", SONGS, session=session)
    assert counts == {1: 1200, 2: 34000}  # rank 3 missing: not found


def test_playcounts_sends_api_key_and_autocorrect():
    session = FakeSession({"Convoy": "5"})
    playcounts("key123", [SONGS[0]], session=session)
    url, kwargs = session.calls[0]
    assert url == LASTFM_API
    params = kwargs["params"]
    assert params["method"] == "track.getinfo"
    assert params["api_key"] == "key123"
    assert params["artist"] == "C.W. McCall"
    assert params["track"] == "Convoy"
    assert params["autocorrect"] == 1
    assert params["format"] == "json"


def test_playcounts_empty_without_api_key():
    session = FakeSession({"Convoy": "5"})
    assert playcounts("", SONGS, session=session) == {}
    assert session.calls == []


def test_playcounts_survives_transport_errors():
    session = FakeSession(exc=ConnectionError("last.fm is down"))
    assert playcounts("key123", SONGS, session=session) == {}


def test_rank_by_playcount_orders_descending():
    ordered = rank_by_playcount(SONGS, {1: 1200, 2: 34000, 3: 7})
    assert [s.rank for s in ordered] == [2, 1, 3]


def test_rank_by_playcount_puts_unknown_songs_last():
    ordered = rank_by_playcount(SONGS, {3: 50})
    assert [s.rank for s in ordered] == [3, 1, 2]  # 1 and 2 tie at 0, chart order


def test_rank_by_playcount_falls_back_to_chart_rank_when_counts_empty():
    # Total Last.fm failure must still yield a usable ballot.
    ordered = rank_by_playcount(SONGS, {})
    assert [s.rank for s in ordered] == [1, 2, 3]
