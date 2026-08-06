from __future__ import annotations

import re

import requests

from .chart_source import Song

TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"

_PAREN = re.compile(r"\s*\([^)]*\)")
# Bare `with` was removed from this alternation: it is part of the title
# far more often than it credits a feature ("Dancing With Myself",
# "真夜中のドア～stay with me"), and _PAREN already handles "(feat. X)".
#
# normalize() is also applied to song.artist, not just the title, and this
# regex used to strip bare `with` there too. That was doing real work on
# Billboard credit strings like "Elton John Duet With Kiki Dee" (now left
# intact and passed into the strict query in full). Accepted: dropping
# bare `with` widens artist credits and makes a strict-query miss more
# likely, but the loose fallback still runs for Billboard, and a miss is
# preferable to the title corruption the old regex caused.
_FEAT = re.compile(r"\s+(feat\.?|featuring)\s+.*$", re.IGNORECASE)
_SPACES = re.compile(r"\s+")
# Spotify stores the full-width wave dash as an ASCII tilde
# ("Mayonaka no Door~stay with me"), so align the query to that. The
# katakana middle dot ・ is deliberately absent: a live probe matched
# プラスティック・ラブ strictly, so Spotify keeps it and rewriting it would
# break a working case.
_JP_PUNCT = str.maketrans({"　": " ", "～": "~"})

# Karaoke and cover pressings crowd out the real recording in Japanese
# search results. `原曲歌手` means "original artist" and marks a karaoke
# cover; a result carrying any of these is never the track we want.
BLOCKED_MARKERS = (
    "原曲歌手", "カラオケ", "ガイド無し", "インスト",
    "instrumental", "karaoke", "tribute to", "made popular by",
)


class SpotifyError(RuntimeError):
    pass


def normalize(text: str) -> str:
    text = text.replace('"', "")
    text = text.translate(_JP_PUNCT)
    text = _PAREN.sub("", text)
    text = _FEAT.sub("", text)
    return _SPACES.sub(" ", text).strip().lower()


def is_blocked(name: str) -> bool:
    """True when a search result is a karaoke, instrumental, or cover pressing."""
    lowered = name.lower()
    return any(m.lower() in lowered for m in BLOCKED_MARKERS)


class SpotifyClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        session: requests.Session | None = None,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._session = session or requests.Session()
        self._access_token: str | None = None

    def _token(self) -> str:
        if self._access_token is None:
            resp = self._session.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
                auth=(self._client_id, self._client_secret),
                timeout=30,
            )
            if resp.status_code != 200:
                raise SpotifyError(f"token refresh failed: {resp.text}")
            self._access_token = resp.json()["access_token"]
        return self._access_token

    def _call(self, method: str, url: str, **kwargs):
        headers = {"Authorization": f"Bearer {self._token()}"}
        resp = self._session.request(
            method, url, headers=headers, timeout=30, **kwargs
        )
        if resp.status_code >= 400:
            raise SpotifyError(f"{method} {url} -> {resp.status_code}: {resp.text}")
        return resp.json()

    def find_track(self, song: Song, strict_only: bool = False) -> str | None:
        """The best match for `song`, or None.

        `strict_only` gates two behaviors together, both scoped to Oricon:
        it drops the loose-query fallback (the loose query reliably returns
        a wrong-but-plausible track for Japanese titles, and a wrong track
        nobody notices is worse than a missing one), and it turns on
        scanning every result and skipping karaoke/instrumental/cover
        pressings via `is_blocked()` — position 0 is often a karaoke
        pressing for Japanese queries while the real recording sits lower
        in the same response.

        When `strict_only` is False (Billboard), neither behavior applies:
        the function returns the first result exactly as it did before
        Oricon support existed. This matters because a Billboard
        instrumental chart entry's correct top result can legitimately
        contain "(Instrumental)" or "- Instrumental" in its own title —
        applying `is_blocked()` there would reject the right track and
        silently return a cover or re-record instead.
        """
        title = normalize(song.title)
        artist = normalize(song.artist)
        queries = [f'track:"{title}" artist:"{artist}"']
        if not strict_only:
            queries.append(f"{title} {artist}")
        for q in queries:
            data = self._call(
                "GET",
                f"{API}/search",
                params={"q": q, "type": "track", "limit": 5},
            )
            items = data.get("tracks", {}).get("items", [])
            if not strict_only:
                if items:
                    return items[0]["uri"]
                continue
            for item in items:
                if not is_blocked(item.get("name", "")):
                    return item["uri"]
        return None

    def create_playlist(self, name: str, description: str, uris: list[str]) -> str:
        playlist = self._call(
            "POST",
            f"{API}/me/playlists",
            json={"name": name, "description": description, "public": True},
        )
        if uris:
            self._call(
                "POST",
                f"{API}/playlists/{playlist['id']}/items",
                json={"uris": uris},
            )
        return playlist["external_urls"]["spotify"]
