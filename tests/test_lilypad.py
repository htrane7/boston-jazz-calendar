import json
from datetime import datetime, time
from pathlib import Path

import pytest

from jazzcal.event import BOSTON
from jazzcal.scrapers import lilypad

FIXTURES = Path(__file__).parent / "fixtures"
DATA = json.loads((FIXTURES / "lilypad_events.json").read_text())
NO_CHOICES = (set(), set())
LISTED = datetime(2026, 10, 26, 20, tzinfo=BOSTON)  # Squarespace's listed time: 8pm


def _events():
    return lilypad.select_events(DATA, NO_CHOICES)


def _event(title_part):
    return next(e for e in _events() if title_part in e.title)


@pytest.mark.parametrize(
    "info, expected",
    [
        ("$15 @ the door / $10 students / 8:30 start / 8pm doors / seated", (time(20, 30), time(20))),
        ("$15 Cover @ the Door / Start 8:30pm / Doors 8pm / Seated Show", (time(20, 30), time(20))),
        ("$30 day of show / $25 advance / 7:30 doors / 8pm show / all ages", (time(20), time(19, 30))),
        ("$15 admission / $10 students / 7pm / seated", (time(19), None)),
        ("$5 - 15 sliding scale admission / 4 - 7pm / all ages", (time(16), None)),
        ("$14 advance / $18 door / 11pm - 1am / seated & standing", (time(23), None)),
        ("$15 admission / 7:30 doors / standing / all ages", (None, time(19, 30))),
        ("$20 admission / $5 kids / 5:30 show / seated", (time(17, 30), None)),
        ("New Music for the 21 piece Jazz Orchestra", (None, None)),
        ("$15 admission / seated", (None, None)),
    ],
)
def test_read_times(info, expected):
    assert lilypad.read_times(info, LISTED) == expected


def test_no_am_pm_far_from_listed_time_is_not_guessed():
    # "2 start" with a listed 8pm time: 2am and 2pm are both too far off to trust.
    assert lilypad.read_times("$10 / 2 start", LISTED) == (None, None)


def test_start_time_comes_from_the_description_not_the_doors_time():
    bergonzi = _event("Jerry Bergonzi Quartet")
    assert bergonzi.start == datetime(2026, 10, 26, 20, 30, tzinfo=BOSTON)  # listed as 8pm doors
    assert bergonzi.uid == "lilypad-6ab5495b45872a4489441ac0@boston-jazz-calendar"


def test_notes_format():
    bergonzi = _event("Jerry Bergonzi Quartet")
    assert bergonzi.description.split("\n") == [
        "Jerry Bergonzi Quartet: Jerry Bergonzi (tenor saxophone), Luther Gray (drums), "
        "Plamen Karadonev (piano), Sean Farias (bass), Special Guest (trumpet)",
        "Starts at 8:30pm (doors 8pm)",
        "A fine, high-powered tenor saxophonist with a tone influenced by John Coltrane, a mastery "
        "of chord changes, and a strong musical imagination, Jerry Bergonzi has long had an "
        "underground following in the Boston area.",
        "Event page: " + bergonzi.url,
        "Admission: $15 @ the door / $10 students",
    ]


def test_ticket_link_used_when_there_is_one():
    pablo = _event("Pablo ablanedo")
    assert pablo.description.split("\n")[-1].startswith("Tickets: https://www.eventbrite.com/")


def test_jazz_tags_decide_what_goes_in():
    titles = {e.title for e in _events() if not e.review}
    assert "Gill Aharon Trio" in titles  # Jazz + Avant-garde
    assert "Café Gherkinforke" in titles  # Fusion
    assert "Little Barrie" not in titles  # untagged rock show
    assert "The Lilypad Variety Show" not in titles  # open mic
    assert "Hatha Yoga w/ Live Music" not in titles
    assert not any("Eliot Thompson" in t for t in titles)  # "Jam Session" alone isn't jazz


def test_weekly_series_counts_as_jazz_even_on_untagged_weeks():
    mehler = [e for e in _events() if e.title == "Elan Mehler Trio"]
    assert len(mehler) > 5
    assert all(e.review is None for e in mehler)


def test_untagged_show_that_mentions_jazz_is_held_back():
    lafayette = _event("Lafayette Gilchrist")
    assert lafayette.review == "Mentions jazz, but Lilypad didn't tag it as jazz"


def test_choices_file_overrides():
    lafayette = next(i for i in DATA["upcoming"] if "Lafayette" in i["title"])
    include = {lilypad.SITE_URL + lafayette["fullUrl"]}
    # Each week of a series has its own page, so leaving a series out means every week's page.
    exclude = {lilypad.SITE_URL + i["fullUrl"] for i in DATA["upcoming"] if "Bergonzi" in i["title"]}
    events = lilypad.select_events(DATA, (include, exclude))
    assert next(e for e in events if "Lafayette" in e.title).review is None
    assert not any("Bergonzi" in e.title for e in events)


def test_unreadable_time_is_flagged():
    item = {**next(i for i in DATA["upcoming"] if "Bergonzi" in i["title"]), "body": "", "excerpt": ""}
    event = lilypad.to_event(item)
    assert event.start == LISTED.date()
    assert event.flag and "Couldn't read the show time" in event.flag


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class FakeSession:
    """Stands in for the website so tests never touch the network."""

    def __init__(self):
        self.headers = {}
        self.requested = []

    def get(self, url, timeout=None):
        self.requested.append(url)
        return FakeResponse(DATA)


def test_scrape_makes_one_polite_request():
    session = FakeSession()
    events = lilypad.scrape(session, choices=NO_CHOICES)
    assert session.requested == ["https://www.lilypadinman.com/?format=json"]
    assert "boston-jazz-calendar" in session.headers["User-Agent"]
    assert len(events) == 66
