import json
from datetime import datetime
from pathlib import Path

import pytest

from jazzcal.event import BOSTON
from jazzcal.scrapers import rockport

FIXTURES = Path(__file__).parent / "fixtures"
EVENTS_HTML = (FIXTURES / "rockport_events.html").read_text()
ALL = json.loads((FIXTURES / "rockport_all.json").read_text())
JAZZ = json.loads((FIXTURES / "rockport_jazz.json").read_text())


def _events():
    return rockport.select_events(ALL, JAZZ)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("<h4>Upstairs on Main</h4>\n\n<p>Little Miss and the Boom</p>\n",
         "Little Miss and the Boom (Upstairs on Main)"),
        ("<h4>An Evening with</h4>\n\n<p>Squirrel Nut Zippers</p>\n", "Squirrel Nut Zippers"),
        ("<p>Santiago Cañón-Valencia, <it>cello</it></p>\n", "Santiago Cañón-Valencia, cello"),
        ("<p>Liz Longley</p>\n\n<h4><strong>with Special Guests The Young Fables</strong></h4>\n",
         "Liz Longley with Special Guests The Young Fables"),
        ("Emma Smith", "Emma Smith"),
    ],
)
def test_clean_title(raw, expected):
    assert rockport.clean_title(raw) == expected


def test_jazz_filter_plus_jazz_words():
    titles = {e.title for e in _events()}
    assert "Ekep Nkwelle" in titles  # in the site's Jazz/R&B/Soul filter
    assert "JazzReach’s METTA QUINTET" in titles  # not in the filter, but says jazz
    assert "Squirrel Nut Zippers" in titles  # "vintage jazz, New Orleans swing"
    assert "Josh Ritter" not in titles
    assert not any("Hotel Transylvania" in t for t in titles)


def test_times_and_ids():
    sands = next(e for e in _events() if e.title == "Christian Sands")
    assert sands.start == datetime(2026, 11, 29, 17, tzinfo=BOSTON)
    assert sands.uid == "rockport-10726@boston-jazz-calendar"


def test_two_shows_on_one_day_are_labeled():
    titles = sorted(e.title for e in _events() if "Big Band" in e.title)
    assert titles == [
        "Cape Ann Big Band Holiday",  # Dec 4, the only show that day
        "Cape Ann Big Band Holiday (2pm show)",
        "Cape Ann Big Band Holiday (7pm show)",
    ]


def test_notes_format():
    metta = next(e for e in _events() if "METTA" in e.title)
    assert metta.description.split("\n") == [
        "JazzReach’s METTA QUINTET",
        "Starts at 7pm",
        "New York City’s acclaimed METTA QUINTET takes you on a powerful musical journey celebrating "
        "the centennials of two of the most influential figures in jazz history: the visionary "
        "saxophonist John Coltrane and the trailblazing trumpeter Miles Davis.",
        "Show page: https://rockportmusic.org/upcoming_shows/jazzreachs-metta-quintet/",
        "Tickets: https://tickets.rockportmusic.org/10934/10935",
    ]


def test_sold_out_is_noted():
    cape_ann = next(e for e in _events() if "Big Band" in e.title)
    assert cape_ann.description.split("\n")[1].endswith("(Sold Out)")


def test_unreadable_time_is_flagged():
    production = json.loads(json.dumps(next(p for p in JAZZ if "Ekep" in p["productionTitle"])))
    production["performances"][0]["performanceDate"] = "TBA"
    [event] = rockport.to_events(production)
    assert event.start == datetime(2026, 11, 21).date()
    assert event.flag and "Couldn't read the show time" in event.flag


def test_read_token():
    assert rockport.read_token(EVENTS_HTML).startswith("qPKi_GF0Tm")
    with pytest.raises(ValueError):
        rockport.read_token("<html></html>")


class FakeResponse:
    def __init__(self, text="", data=None):
        self.text = text
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class FakeSession:
    """Stands in for the website so tests never touch the network."""

    def __init__(self):
        self.headers = {}
        self.posts = []

    def get(self, url, timeout=None):
        return FakeResponse(text=EVENTS_HTML)

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append((json, headers))
        return FakeResponse(data=JAZZ if json["keywords"] else ALL)


def test_scrape_sends_security_code_and_date_window():
    session = FakeSession()
    events = rockport.scrape(session, delay=0)
    assert len(events) == 11
    assert [body["keywords"] for body, _ in session.posts] == [[], ["Jazz/R&B/Soul"]]
    body, headers = session.posts[0]
    assert headers["RequestVerificationToken"].startswith("qPKi_GF0Tm")
    assert body["startDate"] < body["endDate"]
    assert "boston-jazz-calendar" in session.headers["User-Agent"]
