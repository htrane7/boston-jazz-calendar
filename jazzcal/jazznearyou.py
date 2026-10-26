"""Shared code for venues we read from Jazz Near You (https://www.jazznearyou.com).

Some venues block automated tools or forbid them in their terms. Jazz Near You,
a jazz listings site run by All About Jazz, lists their shows and allows
ordinary tools in its robots.txt (it only blocks AI crawlers).

Each venue page lists upcoming shows (no times). Each show's own page has the
date, start time, musicians and a description, so we read those too.
"""

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

from jazzcal.event import BOSTON, Event
from jazzcal.text import first_sentence, format_time

log = logging.getLogger(__name__)

USER_AGENT = "boston-jazz-calendar/0.1 (personal concert calendar)"
REQUEST_DELAY = 5  # seconds to wait before each request to the site
MAX_SHOWS = 30  # safety stop on requests per venue

_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?", re.I)


@dataclass
class Show:
    """One show from a Jazz Near You venue page."""

    show_id: str
    title: str
    url: str
    ticket_url: str | None


def parse_venue_page(html: str) -> list[Show]:
    shows = []
    for row in BeautifulSoup(html, "html.parser").select('div.data-row[id^="tr"]'):
        link = row.select_one("h5 a")
        if not link:
            continue
        ticket = row.select_one(".data-row-hang a[href]")
        shows.append(Show(
            show_id=row["id"].removeprefix("tr"),
            title=" ".join(link.get_text(" ", strip=True).split()),
            url=link["href"],
            ticket_url=ticket["href"] if ticket else None,
        ))
    return shows


def parse_show_page(html: str) -> dict:
    """Date, start time (None if unreadable), musicians, ticket link, description."""
    soup = BeautifulSoup(html, "html.parser")
    when_heading = soup.find("h3", string=re.compile(r"When"))
    when = when_heading.find_parent(class_="row") if when_heading else None
    day_tag = when.select_one('meta[itemprop="startDate"]') if when else None
    day = date.fromisoformat(day_tag["content"]) if day_tag else None

    when_text = when.get_text(" ", strip=True) if when else ""
    start = None
    if match := _TIME.search(when_text):
        hour, minute = int(match[1]), int(match[2] or 0)
        if hour <= 12 and minute <= 59:
            start = datetime.strptime(f"{hour}:{minute:02d}{match[3]}m", "%I:%M%p").time()

    musicians = []
    for name in soup.select('.card-body h5 a[id^="claimname_"]'):
        instrument = soup.select_one(f"#musician_instr{name['id'].removeprefix('claimname_')}")
        role = " ".join(instrument.get_text(" ", strip=True).split()) if instrument else ""
        musicians.append(f"{name.get_text(strip=True)} ({role})" if role else name.get_text(strip=True))

    ticket = soup.select_one('[itemprop="offers"] a[href]')
    about = soup.select_one("#lastpart") or soup.select_one("#firstpart")
    paragraphs = []
    if about:
        for link in about.select("a#showmore"):
            link.decompose()
        paragraphs = [" ".join(p.get_text(" ", strip=True).split()) for p in about.find_all("p")]
    return {
        "day": day,
        "start": start,
        "when_text": when_text.removeprefix("When").strip(),
        "musicians": musicians,
        "ticket_url": ticket["href"] if ticket else None,
        "paragraphs": [p for p in paragraphs if p],
    }


def _event_notes(title, details, show_url, ticket_url) -> str:
    musicians = details["musicians"]
    notes = [f"{title}: {', '.join(musicians)}" if musicians else title]
    if details["start"]:
        notes.append(f"Starts at {format_time(details['start'])}")
    else:
        notes.append(f"Show time not listed (site says “{details['when_text']}”), check the venue")
    if sentence := first_sentence(details["paragraphs"]):
        notes.append(sentence)
    notes.append(f"Show page: {show_url}")
    if ticket_url:
        notes.append(f"Tickets: {ticket_url}")
    return "\n".join(notes)


def to_event(show: Show, details: dict, venue: str, address: str, source: str) -> Event:
    ticket_url = details["ticket_url"] or show.ticket_url
    common = dict(
        title=show.title,
        venue=venue,
        address=address,
        url=show.url,
        description=_event_notes(show.title, details, show.url, ticket_url),
        source=source,
    )
    if details["start"] is None:
        flag = f"Couldn't read the show time from {details['when_text']!r}. Check {show.url}"
        log.warning("%s show %s (%s): %s", venue, show.show_id, show.title, flag)
        return Event(uid=f"{source}-{show.show_id}@boston-jazz-calendar", start=details["day"],
                     flag=flag, **common)
    return Event(
        uid=f"{source}-{show.show_id}@boston-jazz-calendar",
        start=datetime.combine(details["day"], details["start"], tzinfo=BOSTON),
        **common,
    )


def scrape_venue(venue_url: str, venue: str, address: str, source: str,
                 session=None, delay: float = REQUEST_DELAY) -> list[Event]:
    """Read a venue page, then each show's page, waiting between requests."""
    session = session or requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    response = session.get(venue_url, timeout=30)
    response.raise_for_status()

    events = []
    for show in parse_venue_page(response.text)[:MAX_SHOWS]:
        time.sleep(delay)
        try:
            page = session.get(show.url, timeout=30)
            page.raise_for_status()
            details = parse_show_page(page.text)
            if details["day"] is None:
                raise ValueError("no date on the show page")
            events.append(to_event(show, details, venue, address, source))
        except (requests.RequestException, AttributeError, KeyError, ValueError):
            # One odd show page shouldn't stop the rest from being read.
            log.exception("Skipping %s show %s that couldn't be read", venue, show.url)
    return events
