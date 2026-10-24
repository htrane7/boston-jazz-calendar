from datetime import date, datetime, time
from pathlib import Path

import pytest

from jazzcal.event import BOSTON
from jazzcal.scrapers import scullers

FIXTURES = Path(__file__).parent / "fixtures"
CALENDAR_HTML = (FIXTURES / "scullers_calendar.html").read_text()
PAGE1_HTML = (FIXTURES / "scullers_events_page1.html").read_text()


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("TIM RAY TRIO feat EDMAR COLON - Tickets on Sale Now", "TIM RAY TRIO feat EDMAR COLON"),
        ("ELAN TROTMAN - 25 YEARS IN MUSIC", "ELAN TROTMAN - 25 YEARS IN MUSIC"),
        ("SOLD OUT - CYRUS CHESTNUT TRIO", "CYRUS CHESTNUT TRIO"),
        ("Benny Green (Sold Out)", "Benny Green"),
        ("Santi Debriano – New Date! – Few Tickets Left", "Santi Debriano"),
        ("A MOTOWN CHRISTMAS", "A MOTOWN CHRISTMAS"),
    ],
)
def test_clean_title(raw, expected):
    assert scullers.clean_title(raw) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("One Show at 7pm", [time(19)]),
        ("ONE SHOW AT 7PM", [time(19)]),
        ("Shows at 7 & 9pm", [time(19), time(21)]),
        ("Shows at 7pm and 9:30 p.m.", [time(19), time(21, 30)]),
        ("Doors 6pm, show 7:30pm", [time(19, 30)]),
        ("Sunday brunch at 11am", [time(11)]),
        ("Shows at 7 & 9", None),  # no am/pm: don't guess
        ("Time TBA", None),
        ("", None),
        ("Show at 19pm", None),
    ],
)
def test_parse_show_times(text, expected):
    assert scullers.parse_show_times(text) == expected


def test_read_list_settings_from_saved_calendar_page():
    settings = scullers.read_list_settings(CALENDAR_HTML)
    assert settings == {"nonce": "d53b230c15", "entity_id": "venue:715", "results_per_page": "15"}


def test_read_list_settings_fails_loudly_if_site_changes():
    with pytest.raises(ValueError):
        scullers.read_list_settings("<html>redesigned site</html>")


def test_parse_saved_page():
    events = scullers.parse_events(PAGE1_HTML)
    # 14 shows on the page; 4 have two sets, so 18 calendar entries.
    assert len(events) == 18
    assert len({e.uid for e in events}) == 18
    assert all(e.flag is None for e in events)
    assert all(e.start.tzinfo == BOSTON for e in events)

    first = events[0]
    assert first.title == "TIM RAY TRIO feat EDMAR COLON"
    assert first.start == datetime(2026, 10, 24, 19, 0, tzinfo=BOSTON)
    assert first.uid == "scullers-75733-1900@boston-jazz-calendar"
    assert first.url.startswith("https://www.ticketweb.com/event/the-tim-ray-trio")
    assert "Tim Ray-piano" in first.description


def test_two_sets_become_two_entries():
    elan = [e for e in scullers.parse_events(PAGE1_HTML) if "ELAN TROTMAN" in e.title]
    assert [(e.title, e.start.time()) for e in elan] == [
        ("ELAN TROTMAN - 25 YEARS IN MUSIC (7pm show)", time(19)),
        ("ELAN TROTMAN - 25 YEARS IN MUSIC (9pm show)", time(21)),
    ]


def test_ids_stay_the_same_between_runs():
    first_run = [e.uid for e in scullers.parse_events(PAGE1_HTML)]
    second_run = [e.uid for e in scullers.parse_events(PAGE1_HTML)]
    assert first_run == second_run


def test_unreadable_time_is_flagged_not_guessed():
    html = PAGE1_HTML.replace("One Show at 7pm", "Time TBA", 1)
    event = scullers.parse_events(html)[0]
    assert event.start == date(2026, 10, 24)  # date only, no made-up time
    assert "Time TBA" in event.flag
    assert event.uid == "scullers-75733@boston-jazz-calendar"


def test_broken_listing_is_skipped_not_fatal():
    html = PAGE1_HTML.replace('title="Sat Oct 24, 2026"', 'title="not a date"', 1)
    events = scullers.parse_events(html)
    assert len(events) == 17
    assert "TIM RAY" not in events[0].title


def test_total_pages():
    assert scullers.total_pages(PAGE1_HTML) == 1


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeSession:
    """Stands in for the website so tests never touch the network."""

    def __init__(self):
        self.headers = {}
        self.posts = []

    def get(self, url, **kwargs):
        return FakeResponse(CALENDAR_HTML)

    def post(self, url, data, **kwargs):
        self.posts.append(data)
        return FakeResponse(PAGE1_HTML)


def test_scrape_stops_after_last_page():
    session = FakeSession()
    events = scullers.scrape(session=session, delay=0)
    assert len(events) == 18
    assert len(session.posts) == 1  # total pages is 1, so only one list request
    assert session.posts[0]["security"] == "d53b230c15"
    assert "boston-jazz-calendar" in session.headers["User-Agent"]
