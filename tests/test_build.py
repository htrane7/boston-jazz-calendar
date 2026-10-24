from datetime import date, datetime, timezone
from pathlib import Path

from icalendar import Calendar

from jazzcal import build
from jazzcal.ics import SET_LENGTH, to_ics
from jazzcal.scrapers import scullers

PAGE1_HTML = (Path(__file__).parent / "fixtures" / "scullers_events_page1.html").read_text()
NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def test_ics_has_every_event_in_boston_time():
    events = scullers.parse_events(PAGE1_HTML)
    cal = Calendar.from_ical(to_ics(events, now=NOW))
    items = cal.walk("VEVENT")
    assert len(items) == 18
    first = items[0]
    assert str(first["summary"]) == "TIM RAY TRIO feat EDMAR COLON"
    assert first["uid"] == "scullers-75733-1900@boston-jazz-calendar"
    assert first.decoded("dtstart").tzinfo.key == "America/New_York"
    assert first.decoded("dtend") - first.decoded("dtstart") == SET_LENGTH
    assert cal.walk("VTIMEZONE")  # time zone info included for calendar apps


def test_flagged_event_is_all_day_with_note():
    html = PAGE1_HTML.replace("One Show at 7pm", "Time TBA", 1)
    cal = Calendar.from_ical(to_ics(scullers.parse_events(html), now=NOW))
    first = cal.walk("VEVENT")[0]
    assert first.decoded("dtstart") == date(2026, 10, 24)
    assert "time TBD" in str(first["summary"])
    assert "Time TBA" in str(first["description"])


def test_same_events_give_same_file():
    events = scullers.parse_events(PAGE1_HTML)
    assert to_ics(events, now=NOW) == to_ics(events, now=NOW)


def test_one_broken_scraper_does_not_stop_others():
    def broken():
        raise RuntimeError("site down")

    events = build.run_scrapers({"Broken": broken, "Good": lambda: scullers.parse_events(PAGE1_HTML)})
    assert len(events) == 18


def test_no_events_means_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "OUTPUT_FILE", tmp_path / "boston-jazz.ics")
    monkeypatch.setattr(build, "run_scrapers", lambda: [])
    assert build.main() == 1
    assert not (tmp_path / "boston-jazz.ics").exists()
