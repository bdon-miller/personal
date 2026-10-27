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


# Trimmed from Wayback Machine copies of billboard.com.
LIST_ITEM_PAGE = """
<div class="chart-list-item " data-rank="1" data-artist="Bee Gees"
     data-title="You Should Be Dancing" data-has-content="true">
  <div class="chart-list-item__title"><span>You Should Be Dancing</span></div>
</div>
<div class="chart-list-item " data-rank="2" data-artist="Donna Summer &amp; Co"
     data-title="Could It Be Magic"></div>
"""

CHART_ROW_PAGE = """
<article class="chart-row chart-row--1 js-chart-row">
  <div class="chart-row__rank">
    <span class="chart-row__current-week">1</span>
    <span class="chart-row__last-week">Last Week: 1</span>
  </div>
  <div class="chart-row__title">
    <h2 class="chart-row__song">Self Destruction</h2>
    <a class="chart-row__artist" href="#"> The Stop The Violence Movement </a>
  </div>
</article>
<article class="chart-row chart-row--2 js-chart-row">
  <span class="chart-row__current-week">2</span>
  <h2 class="chart-row__song">Wild Thing</h2>
  <span class="chart-row__artist">Tone Loc</span>
</article>
"""


def test_parse_billboard_reads_the_2019_2021_layout():
    assert cs.parse_billboard(LIST_ITEM_PAGE) == [
        cs.Song(1, "You Should Be Dancing", "Bee Gees"),
        cs.Song(2, "Could It Be Magic", "Donna Summer & Co"),
    ]


def test_parse_billboard_reads_the_pre_2019_layout():
    assert cs.parse_billboard(CHART_ROW_PAGE) == [
        cs.Song(1, "Self Destruction", "The Stop The Violence Movement"),
        cs.Song(2, "Wild Thing", "Tone Loc"),
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


def test_fetch_page_without_chart_rows_blames_the_site():
    # What billboard.com served during its 2026-10-26 outage: the chart
    # container is there, the rows are not.
    page = '<div class="pmc-paywall"><div class="chart-results-container"></div></div>'
    source = cs.BillboardSource(FakeSession(FakeResponse(page)))
    with pytest.raises(cs.ChartFetchError, match="site is down or its layout changed"):
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


class JsonResponse(FakeResponse):
    def __init__(self, payload, status=200):
        super().__init__("", status)
        self.payload = payload

    def json(self):
        return self.payload


class ScriptedSession:
    """Answers each get() with the next queued response."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, timeout=None, params=None):
        self.calls.append((url, params))
        return self.responses.pop(0)


def test_wayback_reads_the_newest_copy_from_before_the_outage():
    session = ScriptedSession(
        JsonResponse([["timestamp"], ["20230101000000"], ["20250101000000"]]),
        FakeResponse(PAGE),
    )
    got = cs.WaybackSource(session).fetch(HOT100, date(1976, 3, 6))
    lookup, page = session.calls
    assert lookup[1]["url"] == "https://www.billboard.com/charts/hot-100/1976-03-06/"
    assert lookup[1]["to"] == cs.WAYBACK_BEFORE
    assert page[0] == (
        "https://web.archive.org/web/20250101000000id_/"
        "https://www.billboard.com/charts/hot-100/1976-03-06/"
    )
    assert got.songs[0].title == "December, 1963 (Oh, What A Night)"


def test_wayback_skips_an_unreadable_copy():
    session = ScriptedSession(
        JsonResponse([["timestamp"], ["20230101000000"], ["20250101000000"]]),
        FakeResponse("<html></html>"),
        FakeResponse(CHART_ROW_PAGE),
    )
    got = cs.WaybackSource(session).fetch(HOT100, date(1976, 3, 6))
    assert session.calls[2][0].startswith("https://web.archive.org/web/20230101000000id_/")
    assert got.songs[0].title == "Self Destruction"


def test_wayback_with_no_copies_raises():
    session = ScriptedSession(JsonResponse([]))
    with pytest.raises(cs.ChartFetchError, match="no readable wayback copy"):
        cs.WaybackSource(session).fetch(HOT100, date(1976, 3, 6))


def test_fallback_returns_the_first_source_that_has_the_chart():
    class Fails:
        def fetch(self, chart, chart_date):
            raise cs.ChartFetchError("not here")

    class Has:
        def fetch(self, chart, chart_date):
            return cs.ChartFetch(songs=[cs.Song(1, "t", "a")], chart_date=chart_date)

    got = cs.FallbackSource([Fails(), Has()]).fetch(HOT100, date(1976, 3, 6))
    assert got.songs == [cs.Song(1, "t", "a")]


def test_fallback_reports_every_failure():
    class Fails:
        def __init__(self, why):
            self.why = why

        def fetch(self, chart, chart_date):
            raise cs.ChartFetchError(self.why)

    with pytest.raises(cs.ChartFetchError, match="archive miss; site down; no copy"):
        cs.FallbackSource([Fails("archive miss"), Fails("site down"), Fails("no copy")]).fetch(
            HOT100, date(1976, 3, 6)
        )
