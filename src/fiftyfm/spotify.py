from __future__ import annotations

import re

import requests

from .chart_source import Song

TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"

_PAREN = re.compile(r"\s*\([^)]*\)")
_FEAT = re.compile(r"\s+(feat\.?|featuring|with)\s+.*$", re.IGNORECASE)
_SPACES = re.compile(r"\s+")


class SpotifyError(RuntimeError):
    pass


def normalize(text: str) -> str:
    text = text.replace('"', "")
    text = _PAREN.sub("", text)
    text = _FEAT.sub("", text)
    return _SPACES.sub(" ", text).strip().lower()


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

    def find_track(self, song: Song) -> str | None:
        title = normalize(song.title)
        artist = normalize(song.artist)
        queries = [
            f'track:"{title}" artist:"{artist}"',
            f"{title} {artist}",
        ]
        for q in queries:
            data = self._call(
                "GET",
                f"{API}/search",
                params={"q": q, "type": "track", "limit": 5},
            )
            items = data.get("tracks", {}).get("items", [])
            if items:
                return items[0]["uri"]
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
                f"{API}/playlists/{playlist['id']}/tracks",
                json={"uris": uris},
            )
        return playlist["external_urls"]["spotify"]
