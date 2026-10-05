from datetime import date

import pytest

import fiftyfm.chart_source as cs
from fiftyfm.config import ChartDef

HOT100 = ChartDef(
    id="hot-100", slug="hot-100", display_name="Hot 100",
    available_from=date(1958, 8, 4),
)


def _row(rank, title, artist):
    # Trimmed from the real billboard.com markup, including the merged
    # LW/PEAK/WEEKS cell that broke billboard.py.
    return f"""
<ul class="o-chart-results-list-row // lrv-a-unstyle-list">
  <li class="o-chart-results-list__item"><span class="c-label">\n\t{rank}\n</span></li>
  <li class="o-chart-results-list__item"></li>
  <li class="o-chart-results-list__item"></li>
  <li class="a-chart-result-item-container"><ul>
    <li class="o-chart-results-list__item">
      <h3 class="c-title" id="title-of-a-story">\n\t\t{title}\t\t\n</h3>
      <span class="c-label">\n<a href="#">{artist}</a> </span>
    </li>
    <li>LW\n\n\t1\n\tPEAK\n\t1\n\tWEEKS ON CHART\n\t11</li>
  </ul></li>
</ul>"""


PAGE = "<html><body>" + _row(
    1, "December, 1963 (Oh, What A Night)", "Four Seasons"
) + _row(2, "All By Myself", "Eric Carmen") + "</body></html>"


class FakeResponse:
    def __init__(self, text, status=200):
        self.text, self.status = text, status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")


class FakeSession:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.urls = response, exc, []

    def get(self, url, timeout=None):
        self.urls.append(url)
        if self.exc:
            raise self.exc
        return self.response


def test_parse_billboard_reads_rank_title_artist():
    assert cs.parse_billboard(PAGE) == [
        cs.Song(1, "December, 1963 (Oh, What A Night)", "Four Seasons"),
        cs.Song(2, "All By Myself", "Eric Carmen"),
    ]


def test_fetch_requests_dated_chart_url():
    session = FakeSession(FakeResponse(PAGE))
    got = cs.BillboardSource(session).fetch(HOT100, date(1976, 3, 6))
    assert session.urls == ["https://www.billboard.com/charts/hot-100/1976-03-06/"]
    assert len(got.songs) == 2


def test_fetch_echoes_requested_date():
    got = cs.BillboardSource(FakeSession(FakeResponse(PAGE))).fetch(
        HOT100, date(1976, 3, 6)
    )
    assert got.chart_date == date(1976, 3, 6)


def test_fetch_empty_chart_raises():
    source = cs.BillboardSource(FakeSession(FakeResponse("<html></html>")))
    with pytest.raises(cs.ChartFetchError, match="came back empty"):
        source.fetch(HOT100, date(1976, 3, 6))


def test_fetch_http_error_raises():
    source = cs.BillboardSource(FakeSession(FakeResponse("", status=404)))
    with pytest.raises(cs.ChartFetchError):
        source.fetch(HOT100, date(1976, 3, 6))


def test_fetch_wraps_exceptions():
    source = cs.BillboardSource(
        FakeSession(exc=ConnectionError("billboard.com unreachable"))
    )
    with pytest.raises(cs.ChartFetchError):
        source.fetch(HOT100, date(1976, 3, 6))


def test_routing_source_dispatches_on_chart_source():
    class Marker:
        def __init__(self, tag):
            self.tag = tag

        def fetch(self, chart, chart_date):
            return cs.ChartFetch(
                songs=[cs.Song(1, self.tag, "a")], chart_date=chart_date
            )

    router = cs.RoutingSource(
        {"billboard": Marker("bb"), "oricon": Marker("or")}
    )
    oricon = ChartDef(
        id="oricon-showa", slug="oricon-showa", display_name="Oricon",
        available_from=date(1976, 1, 12), source="oricon",
    )
    assert router.fetch(HOT100, date(1976, 3, 6)).songs[0].title == "bb"
    assert router.fetch(oricon, date(1976, 3, 6)).songs[0].title == "or"


def test_routing_source_unknown_source_raises():
    router = cs.RoutingSource({"billboard": cs.BillboardSource()})
    bogus = ChartDef(
        id="x", slug="x", display_name="X",
        available_from=date(1976, 1, 3), source="nope",
    )
    with pytest.raises(cs.ChartFetchError):
        router.fetch(bogus, date(1976, 3, 6))
