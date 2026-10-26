"""Regattabar and Groton Hill, both read from Jazz Near You."""

from datetime import datetime
from pathlib import Path

from jazzcal import jazznearyou
from jazzcal.event import BOSTON
from jazzcal.scrapers import grotonhill, regattabar

FIXTURES = Path(__file__).parent / "fixtures"
REGATTABAR_HTML = (FIXTURES / "jazznearyou_regattabar.html").read_text()
REGATTABAR_SHOW_HTML = (FIXTURES / "jazznearyou_regattabar_show.html").read_text()
GROTON_HTML = (FIXTURES / "jazznearyou_grotonhill.html").read_text()
GROTON_SHOW_HTML = (FIXTURES / "jazznearyou_grotonhill_show.html").read_text()


def test_venue_page_lists_shows():
    shows = jazznearyou.parse_venue_page(REGATTABAR_HTML)
    assert len(shows) == 8
    assert shows[0] == jazznearyou.Show(
        show_id="1135811",
        title="Gillian Margot & Geoffrey Keezer",
        url="https://www.jazznearyou.com/boston/events/gillian-margot-and-geoffrey-keezer-at-regattabar-on-october-29",
        ticket_url="https://www.ticketweb.com/event/gillian-margot-geoffrey-keezer-regattabar-tickets/14069224",
    )
    assert [s.title for s in jazznearyou.parse_venue_page(GROTON_HTML)][:2] == [
        "Walter Smith III Twio", "Susan Werner"]


def test_show_page_details():
    details = jazznearyou.parse_show_page(GROTON_SHOW_HTML)
    assert details["day"] == datetime(2026, 11, 8).date()
    assert details["start"].hour == 20
    assert details["musicians"][:3] == [
        "Walter Smith III (saxophone, tenor)", "Ben Street (bass)", "Billy Hart (drums)"]
    assert details["ticket_url"] == "https://grotonhill.org/concerts/walter-smith-iii-twio/"


def test_notes_format():
    show = jazznearyou.parse_venue_page(REGATTABAR_HTML)[0]
    details = jazznearyou.parse_show_page(REGATTABAR_SHOW_HTML)
    event = jazznearyou.to_event(show, details, regattabar.VENUE, regattabar.ADDRESS, "regattabar")
    assert event.uid == "regattabar-1135811@boston-jazz-calendar"
    assert event.start == datetime(2026, 10, 29, 19, tzinfo=BOSTON)
    assert event.description.split("\n") == [
        "Gillian Margot & Geoffrey Keezer: Gillian Margot (vocals)",
        "Starts at 7pm",
        "Regattabar is proud to welcome acclaimed vocalist Gillian Margot and piano virtuoso Geoffrey Keezer!",
        "Show page: " + show.url,
        "Tickets: " + show.ticket_url,
    ]


def test_unreadable_time_is_flagged():
    show = jazznearyou.parse_venue_page(REGATTABAR_HTML)[0]
    details = jazznearyou.parse_show_page(REGATTABAR_SHOW_HTML.replace("7:00 pm", "TBA"))
    event = jazznearyou.to_event(show, details, regattabar.VENUE, regattabar.ADDRESS, "regattabar")
    assert event.start == datetime(2026, 10, 29).date()
    assert event.flag and "Couldn't read the show time" in event.flag
    assert "Show time not listed" in event.description


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeSession:
    """Stands in for the website so tests never touch the network."""

    def __init__(self, venue_html, show_html):
        self.headers = {}
        self.venue_html, self.show_html = venue_html, show_html
        self.requested = []

    def get(self, url, timeout=None):
        self.requested.append(url)
        return FakeResponse(self.show_html if "/events/" in url else self.venue_html)


def test_groton_hill_scrape_reads_each_show_page():
    session = FakeSession(GROTON_HTML, GROTON_SHOW_HTML)
    events = grotonhill.scrape(session, delay=0)
    assert session.requested[0] == grotonhill.VENUE_URL
    assert len(session.requested) == 1 + 5  # venue page, then one page per show
    assert all(e.venue == "Groton Hill Music Center" for e in events)
    assert "boston-jazz-calendar" in session.headers["User-Agent"]


def test_regattabar_scrape():
    session = FakeSession(REGATTABAR_HTML, REGATTABAR_SHOW_HTML)
    events = regattabar.scrape(session, delay=0)
    assert len(events) == 8
    assert len({e.uid for e in events}) == 8
