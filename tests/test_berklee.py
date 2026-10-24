from datetime import datetime
from pathlib import Path

from jazzcal import build
from jazzcal.event import BOSTON
from jazzcal.scrapers import berklee

FIXTURES = Path(__file__).parent / "fixtures"
PAGE0_HTML = (FIXTURES / "berklee_events_page0.html").read_text()
PAGE10_HTML = (FIXTURES / "berklee_events_page10.html").read_text()
NO_CHOICES = (set(), set())


def _listing(title_part, html=PAGE0_HTML):
    return next(l for l in berklee.parse_listings(html) if title_part in l.title)


def test_parse_listing_fields():
    yoron = _listing("Yoron Israel")
    assert yoron.title == "Yoron Israel: Inspiration Live—New Album Release Celebration"
    assert yoron.start == datetime(2026, 10, 26, 19, 30, tzinfo=BOSTON)
    assert yoron.url == "https://college.berklee.edu/events/yoron-israel-inspiration-live-new-album-release-celebration"
    assert yoron.venue == "David Friend Recital Hall (DFRH), Berklee"
    assert yoron.address == "921 Boylston Street, Boston, MA 02115"
    assert yoron.admission == "Free"
    assert not yoron.canceled


def test_canceled_and_ticket_link():
    assert _listing("This Time It's Personal").canceled
    assert _listing("Guitar Night").ticket_url == "https://www.etix.com/ticket/p/39546275/"


def test_classify_saved_pages():
    decisions = {
        l.title: berklee.classify(l)[0]
        for html in (PAGE0_HTML, PAGE10_HTML)
        for l in berklee.parse_listings(html)
    }
    # Jazz by faculty or visiting artists: in the calendar.
    assert decisions["Yoron Israel: Inspiration Live—New Album Release Celebration"] == "include"
    assert decisions["Jimmy Haslip: Los Angeles, Yellowjackets, and Beyond"] == "include"
    # A person's own show with no faculty or visiting-artist sign: a student show.
    assert decisions["Keye Xin: All Seven"] == "skip"
    assert decisions["Henglin Liu: Escaping"] == "skip"
    assert decisions["Carina Deng"] == "skip"
    # Professor-led, only "Latin" as a jazz hint: held back.
    assert decisions["Autumn Flutes, Woodwinds, and Piano"] == "review"
    # Student shows, non-jazz, canceled and non-concerts: left out.
    assert decisions["Kaibing Liu's Recital"] == "skip"
    assert decisions["Rani Thuan's Senior Recital"] == "skip"
    assert decisions["Guitar Night: Rock and Pop"] == "skip"
    assert decisions["Penelope Jane"] == "skip"
    assert decisions["Allman Brothers Tribute Band: At Fillmore East"] == "skip"
    assert decisions["Berklee Original Open Mic"] == "skip"
    assert decisions["This Time It's Personal: Live at Colvin Hall"] == "skip"


def test_wide_net_for_jazz_styles():
    base = _listing("Penelope Jane")
    for words in ["a bossa nova night", "jazz fusion", "Latin jazz", "music of Coltrane", "big band"]:
        listing = berklee.Listing(**{**base.__dict__, "summary": f"Faculty member presents {words}."})
        assert berklee.classify(listing)[0] == "include", words


def test_faculty_beats_student_words():
    base = _listing("Penelope Jane")
    listing = berklee.Listing(**{**base.__dict__, "summary": "Faculty and students perform jazz standards."})
    assert berklee.classify(listing)[0] == "include"


def test_notes_format():
    events = berklee.select_events(berklee.parse_listings(PAGE0_HTML), NO_CHOICES)
    yoron = next(e for e in events if "Yoron" in e.title)
    assert yoron.review is None
    assert yoron.uid == "berklee-yoron-israel-inspiration-live-new-album-release-celebration-20261026T1930@boston-jazz-calendar"
    assert yoron.description.split("\n") == [
        "Yoron Israel: Inspiration Live—New Album Release Celebration",
        "Starts at 7:30pm",
        "Yoron Israel, renowned drummer, percussionist, composer, arranger, bandleader, and "
        "educator presents Inspiration Live to celebrate his new album, Inspiration.",
        "Event page: https://college.berklee.edu/events/yoron-israel-inspiration-live-new-album-release-celebration",
        "Admission: Free",
    ]


def test_jazz_ensemble_with_unclear_players_is_held_back():
    base = _listing("Penelope Jane")
    listing = berklee.Listing(
        **{**base.__dict__, "title": "Coltrane 100: Both Directions at Once", "summary": "A tribute to John Coltrane."}
    )
    assert berklee.classify(listing) == (
        "review",
        "Jazz, but couldn't tell if faculty or a visiting artist is playing",
    )


def test_review_events_are_marked():
    events = berklee.select_events(berklee.parse_listings(PAGE10_HTML), NO_CHOICES)
    flutes = next(e for e in events if "Autumn Flutes" in e.title)
    assert flutes.review == "Faculty or visiting artist, but not clearly jazz"


def test_choices_file_overrides():
    listings = berklee.parse_listings(PAGE0_HTML)
    keye = "https://college.berklee.edu/events/keye-xin-all-seven"
    yoron = "https://college.berklee.edu/events/yoron-israel-inspiration-live-new-album-release-celebration"
    events = berklee.select_events(listings, ({keye}, {yoron}))
    titles = {e.title: e.review for e in events}
    assert titles["Keye Xin: All Seven"] is None  # moved into the calendar
    assert not any("Yoron" in t for t in titles)  # always left out


def test_load_choices(tmp_path):
    path = tmp_path / "berklee.toml"
    path.write_text('include = ["https://college.berklee.edu/events/a/"]\nexclude = []\n')
    assert berklee.load_choices(path) == ({"https://college.berklee.edu/events/a"}, set())
    assert berklee.load_choices(tmp_path / "missing.toml") == (set(), set())


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeSession:
    """Stands in for the website so tests never touch the network."""

    def __init__(self, pages):
        self.headers = {}
        self.pages = pages
        self.requested = []

    def get(self, url, params=None, timeout=None):
        page = (params or {}).get("page", 0)
        self.requested.append(page)
        return FakeResponse(self.pages[page])


def test_fetch_stops_once_past_the_date_window():
    # Page 0 ends Oct 27; with a window ending Oct 26, one request is enough.
    session = FakeSession({0: PAGE0_HTML})
    berklee.fetch_event_pages(session, delay=0, until=datetime(2026, 10, 26, 23, tzinfo=BOSTON))
    assert session.requested == [0]
    assert "boston-jazz-calendar" in session.headers["User-Agent"]


def test_fetch_follows_next_page_link():
    session = FakeSession({0: PAGE0_HTML, 1: PAGE10_HTML.replace('?page=11"', "")})
    berklee.fetch_event_pages(session, delay=0, until=datetime(2026, 12, 31, tzinfo=BOSTON))
    assert session.requested == [0, 1]


def test_scrape_drops_events_past_window():
    session = FakeSession({0: PAGE0_HTML})
    events = berklee.scrape(session, delay=0, until=datetime(2026, 10, 26, 23, tzinfo=BOSTON), choices=NO_CHOICES)
    assert {e.title for e in events} == {"Yoron Israel: Inspiration Live—New Album Release Celebration"}


def test_review_file_lists_held_back_events():
    events = berklee.select_events(berklee.parse_listings(PAGE10_HTML), NO_CHOICES)
    text = build.review_text([e for e in events if e.review])
    assert "Autumn Flutes, Woodwinds, and Piano" in text
    assert "https://college.berklee.edu/events/autumn-flutes-woodwinds-and-piano-1" in text
    assert "Nothing to review" in build.review_text([])
