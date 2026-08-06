"""Test doubles shared by the pipeline-level tests."""
from fiftyfm.chart_source import ChartFetch
from fiftyfm.spotify import SpotifyError


class FakeSource:
    def __init__(self, songs=None, exc=None, chart_date=None):
        self.songs = songs
        self.exc = exc
        self.chart_date = chart_date
        self.fetched = None

    def fetch(self, chart, chart_date):
        if self.exc:
            raise self.exc
        self.fetched = (chart, chart_date)
        return ChartFetch(
            songs=self.songs, chart_date=self.chart_date or chart_date
        )


class FakeSpotify:
    def __init__(self, miss_titles=(), error_titles=()):
        self.miss_titles = miss_titles
        self.error_titles = error_titles
        self.created = None

    def find_track(self, song):
        if song.title in self.error_titles:
            raise SpotifyError(f"boom on {song.title}")
        if song.title in self.miss_titles:
            return None
        return f"spotify:track:{song.rank}"

    def create_playlist(self, name, description, uris):
        self.created = (name, description, uris)
        return "https://open.spotify.com/playlist/pl1"
