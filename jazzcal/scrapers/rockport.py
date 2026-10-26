"""Scraper for Rockport Music's Shalin Liu Performance Center (https://tickets.rockportmusic.org/events).

The ticket site (Tessitura) loads its event list from its own data address,
/api/products/productionseasons. We make that same request: first load the
events page for its short-lived security code and cookies, then ask for the
list. Times come exact, with the time zone.

Jazz: shows in the site's "Jazz/R&B/Soul" filter, plus any show whose
description says jazz (the filter misses some, like JazzReach's METTA Quintet).
"""

import html
import logging
import re
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from jazzcal.event import BOSTON, Event
from jazzcal.text import first_sentence, format_time

log = logging.getLogger(__name__)

VENUE = "Shalin Liu Performance Center (Rockport Music)"
ADDRESS = "37 Main Street, Rockport, MA 01966"
EVENTS_URL = "https://tickets.rockportmusic.org/events"
API_URL = "https://tickets.rockportmusic.org/api/products/productionseasons"
USER_AGENT = "boston-jazz-calendar/0.1 (personal concert calendar)"
REQUEST_DELAY = 3  # seconds to wait before each request to the site
WEEKS_AHEAD = 16
JAZZ_FILTER = "Jazz/R&B/Soul"

_JAZZ_WORDS = re.compile(r"\b(?:jazz|bebop|bossa|samba|big band)\b", re.I)
_SERIES_LEAD_IN = re.compile(r"^an evening with$", re.I)


def clean_title(title_html: str) -> str:
    """'<h4>Upstairs on Main</h4><p>Little Miss and the Boom</p>' -> 'Little Miss and the Boom (Upstairs on Main)'.

    A heading before the name is a series label; one after it is a subtitle.
    """
    soup = BeautifulSoup(title_html or "", "html.parser")
    blocks = soup.find_all(["h1", "h2", "h3", "h4", "h5", "p"])
    if not blocks:
        return " ".join(soup.get_text(" ").split())
    labels, name, subtitle = [], [], []
    for block in blocks:
        text = " ".join(block.get_text(" ", strip=True).split())
        if not text:
            continue
        if block.name == "p":
            name.append(text)
        elif name:
            subtitle.append(text)
        elif not _SERIES_LEAD_IN.match(text):
            labels.append(text)
    title = " ".join(name + subtitle).rstrip(",")
    title = re.sub(r"\s+([,.!?;:])", r"\1", title)
    return f"{title} ({', '.join(labels)})" if labels else title


def _paragraphs(description_html: str) -> list[str]:
    soup = BeautifulSoup(description_html or "", "html.parser")
    for link in soup.find_all("a", string=re.compile(r"learn more", re.I)):
        link.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all("p"):
        p.append("\n")
    text = html.unescape(soup.get_text())
    return [" ".join(line.split()) for line in text.split("\n") if line.strip()]


def is_jazz(production: dict, jazz_ids: set[str]) -> bool:
    if production["productionSeasonId"] in jazz_ids:
        return True
    text = clean_title(production.get("productionTitle", "")) + " " + " ".join(
        _paragraphs(production.get("description", ""))
    )
    return bool(_JAZZ_WORDS.search(text))


def _event_notes(title, start, status, sentence, show_url, ticket_url) -> str:
    notes = [title]
    showtime = f"Starts at {format_time(start.time())}" if start else "Show time not listed, check the venue"
    notes.append(f"{showtime} ({status.rstrip('!')})" if status else showtime)
    if sentence:
        notes.append(sentence)
    if show_url:
        notes.append(f"Show page: {show_url}")
    if ticket_url:
        notes.append(f"Tickets: {ticket_url}")
    return "\n".join(notes)


def to_events(production: dict) -> list[Event]:
    """One Event per performance."""
    title = clean_title(production["productionTitle"])
    sentence = first_sentence(_paragraphs(production.get("description", "")))
    show_url = production.get("productionSeasonActionUrl")
    performances = [p for p in production.get("performances") or [] if p.get("isPerformanceVisible", True)]

    starts = {}
    for perf in performances:
        try:
            starts[perf["id"]] = datetime.fromisoformat(perf["performanceDate"]).astimezone(BOSTON)
        except (KeyError, TypeError, ValueError):
            starts[perf["id"]] = None
    days = [s.date() for s in starts.values() if s]

    events = []
    for perf in performances:
        start = starts[perf["id"]]
        status = (perf.get("performanceStatusMessage") or "").strip()
        notes = _event_notes(title, start, status, sentence, show_url, perf.get("actionUrl"))
        common = dict(
            uid=f"rockport-{perf['id']}@boston-jazz-calendar",
            venue=VENUE,
            address=ADDRESS,
            url=show_url or perf.get("actionUrl") or EVENTS_URL,
            description=notes,
            source="rockport",
        )
        if start is None:
            day = perf.get("displayDate")
            flag = f"Couldn't read the show time from {perf.get('performanceDate')!r}. Check {EVENTS_URL}"
            log.warning("Rockport performance %s (%s): %s", perf.get("id"), title, flag)
            if not day:
                continue  # no date at all: nothing to put on a calendar
            events.append(Event(title=title, start=datetime.strptime(day, "%B %d, %Y").date(),
                                flag=flag, **common))
            continue
        # Two shows on one day: say which one so the entries are easy to tell apart.
        label = f" ({format_time(start.time())} show)" if days.count(start.date()) > 1 else ""
        events.append(Event(title=title + label, start=start, **common))
    return events


def select_events(productions: list[dict], jazz_productions: list[dict]) -> list[Event]:
    jazz_ids = {p["productionSeasonId"] for p in jazz_productions}
    events = {}
    for production in productions + [p for p in jazz_productions if p not in productions]:
        try:
            if not is_jazz(production, jazz_ids):
                continue
            for event in to_events(production):
                events.setdefault(event.uid, event)
        except (KeyError, TypeError, ValueError):
            # One odd listing shouldn't stop the rest from being read.
            log.exception("Skipping Rockport listing %s that couldn't be read",
                          production.get("productionSeasonId"))
    return list(events.values())


def read_token(events_html: str) -> str:
    """The short-lived security code the site checks on each data request."""
    field = BeautifulSoup(events_html, "html.parser").find("input", attrs={"name": "__RequestVerificationToken"})
    if not field or not field.get("value"):
        raise ValueError("Rockport events page has no __RequestVerificationToken; the site may have changed")
    return field["value"]


def fetch_productions(session=None, delay: float = REQUEST_DELAY, now: datetime | None = None):
    """(all productions, Jazz/R&B/Soul productions) for the next few months."""
    session = session or requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    response = session.get(EVENTS_URL, timeout=30)
    response.raise_for_status()
    token = read_token(response.text)

    now = now or datetime.now(BOSTON)
    window = {
        "startDate": f"{now:%Y-%m-%d}T00:00:00",
        "endDate": f"{now + timedelta(weeks=WEEKS_AHEAD):%Y-%m-%d}T23:59:59",
    }
    results = []
    for keywords in ([], [JAZZ_FILTER]):
        time.sleep(delay)
        response = session.post(
            API_URL,
            json={**window, "keywords": keywords},
            headers={"RequestVerificationToken": token, "X-Requested-With": "XMLHttpRequest",
                     "Referer": EVENTS_URL},
            timeout=30,
        )
        response.raise_for_status()
        results.append(response.json())
    return results[0], results[1]


def scrape(session=None, delay: float = REQUEST_DELAY) -> list[Event]:
    return select_events(*fetch_productions(session, delay))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for event in scrape():
        print(event.start, "|", event.title, "|", event.flag or event.url)
