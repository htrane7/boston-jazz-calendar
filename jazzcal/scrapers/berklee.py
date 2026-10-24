"""Scraper for Berklee College of Music events (https://college.berklee.edu/events).

Berklee has no calendar feed or API, and no genre labels. We read the public
events list (10 events per page) and judge from each listing's title and
summary whether it's jazz and whether faculty or visiting artists are playing.
Student recitals are left out. Events we can't decide on are held back for
review instead of guessed.
"""

import logging
import re
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from jazzcal.event import BOSTON, Event
from jazzcal.text import first_sentence, format_time

log = logging.getLogger(__name__)

EVENTS_URL = "https://college.berklee.edu/events"
USER_AGENT = "boston-jazz-calendar/0.1 (personal concert calendar)"
REQUEST_DELAY = 10  # seconds between requests; Berklee's robots.txt asks for 10
WEEKS_AHEAD = 6  # about 20 pages, so a run takes 3-4 minutes
MAX_PAGES = 40  # safety stop so a site bug can't make us loop forever
CHOICES_FILE = Path(__file__).resolve().parents[2] / "choices" / "berklee.toml"

# Not concerts: skipped no matter what.
_SKIP_TITLE = re.compile(r"open mic|admissions?\b|info(?:rmation)? session|audition|campus tour", re.I)

# Clear jazz signs. Cast wide: bossa nova, fusion, Latin jazz and so on count too.
_JAZZ_ARTISTS = (
    r"Coltrane|Thelonious|Ellington|Mingus|Miles Davis|Charlie Parker|Dizzy Gillespie"
    r"|Bill Evans|Chick Corea|Herbie Hancock|Wayne Shorter|Sonny Rollins|Ella Fitzgerald"
    r"|Billie Holiday|Sarah Vaughan|Jobim|Pat Metheny|Chris Potter|Brad Mehldau"
    r"|Esperanza Spalding|Terri Lyne Carrington|Danilo P[eé]rez|Gary Burton|Joe Lovano"
    r"|Yellowjackets|Weather Report|Snarky Puppy|Dave Brubeck|Wynton Marsalis|Lee Morgan"
    r"|Art Blakey"
)
_JAZZ = re.compile(
    r"jazz|be-?bop|\bbop\b|post-bop|\bswing(?:ing)?\b|big band|bossa|samba|\bchoro\b"
    r"|brazilian|afro-cuban|fusion|great american songbook|" + _JAZZ_ARTISTS,
    re.I,
)
# Styles near jazz: not enough alone, but worth a look if faculty are playing.
_JAZZ_NEARBY = re.compile(
    r"improvis|standards|blues|groove|latin|caribbean|tango|flamenco|funk|\bsoul\b|gospel|afrobeat",
    re.I,
)
# Faculty and visiting-artist signs. These win over student signs, since
# "faculty and students perform" is a faculty show.
_PRO = re.compile(
    r"faculty|professor|\bchair\b|visiting (?:artist|composer)|guest (?:artist|performer)"
    r"|special guest|in residence|residency|GRAMMY|renowned|legend(?:ary)?|acclaimed"
    r"|award-winning|album release|educator|alumn",
    re.I,
)
# A person's own show: "Sera Chen: Enduring Palette", "Lara Pereira and Friends",
# "Liam Backhoff Presents...", "Skye's Fusion Band". Without a faculty or
# visiting-artist sign, these are almost always student shows.
_NAME = r"[A-Z][\w'’.-]+"
_PERSONAL_SHOW = re.compile(
    rf"^(?:{_NAME}\s){{0,2}}{_NAME}(?:\s*:|\s+(?:and|&|ft\.?|feat\.?)\s|\s+Presents\b|$)|^{_NAME}['’]s\s"
)
_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([.,;:!?])")
_STUDENT = re.compile(r"\bstudents?\b|(?:senior|junior|class|degree|graduate) recital|['’]s recital", re.I)


@dataclass
class Listing:
    """One row of Berklee's events list."""

    title: str
    start: datetime
    url: str
    venue: str
    address: str
    summary: str
    admission: str
    ticket_url: str | None
    canceled: bool


def _field(row, name: str) -> str:
    tag = row.select_one(f".field--name-field-{name}")
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def parse_listings(html: str) -> list[Listing]:
    listings = []
    for row in BeautifulSoup(html, "html.parser").select(".views-row .event.teaser"):
        try:
            link = row.select_one(".title a")
            hall = _field(row, "event-venue-title")
            ticket = row.select_one(".fieldgroup-event-ticket a[href]")
            listings.append(
                Listing(
                    title=" ".join(link.get_text(" ", strip=True).split()),
                    start=datetime.fromisoformat(row.select_one("time[datetime]")["datetime"]).astimezone(BOSTON),
                    url=urljoin(EVENTS_URL, link["href"]),
                    venue=hall if "Berklee" in hall else f"{hall}, Berklee",
                    address=", ".join(
                        part
                        for part in [
                            _field(row, "event-address"),
                            _field(row, "event-city"),
                            f"{_field(row, 'event-state')} {_field(row, 'event-zip')}".strip(),
                        ]
                        if part
                    ),
                    summary=_SPACE_BEFORE_PUNCTUATION.sub(
                        r"\1", " ".join(" ".join(p.get_text(" ", strip=True).split()) for p in row.select(".text > p"))
                    ).strip(),
                    admission=_field(row, "admission").removeprefix("Admission").strip(),
                    ticket_url=ticket["href"] if ticket else None,
                    canceled=row.select_one(".event-instance-status-canceled") is not None,
                )
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            # One odd listing shouldn't stop the rest from being read.
            log.exception("Skipping a Berklee listing that couldn't be read")
    return listings


def classify(listing: Listing) -> tuple[str, str]:
    """Decide "include", "review" or "skip" for one listing, with the reason."""
    text = f"{listing.title} {listing.summary}"
    if listing.canceled:
        return "skip", "canceled"
    if _SKIP_TITLE.search(listing.title) or "virtual" in listing.venue.lower():
        return "skip", "not a concert"

    if _PRO.search(text):
        who = "pro"
    elif _STUDENT.search(text) or _PERSONAL_SHOW.match(listing.title):
        return "skip", "student performance"
    else:
        who = "unknown"

    if _JAZZ.search(text):
        if who == "pro":
            return "include", "jazz, faculty or visiting artist"
        return "review", "Jazz, but couldn't tell if faculty or a visiting artist is playing"
    if _JAZZ_NEARBY.search(text) and who == "pro":
        return "review", "Faculty or visiting artist, but not clearly jazz"
    return "skip", "not jazz"


def load_choices(path: Path = CHOICES_FILE) -> tuple[set[str], set[str]]:
    """Event pages you've said to always include or always leave out."""
    if not path.exists():
        return set(), set()
    data = tomllib.loads(path.read_text())

    def urls(key):
        return {url.strip().rstrip("/") for url in data.get(key, [])}

    return urls("include"), urls("exclude")


def _event_notes(listing: Listing) -> str:
    """Short notes: who's playing, start time, one sentence, event page, tickets."""
    notes = [listing.title, f"Starts at {format_time(listing.start.time())}"]
    if sentence := first_sentence([listing.summary]):
        notes.append(sentence)
    notes.append(f"Event page: {listing.url}")
    if listing.ticket_url:
        notes.append(f"Tickets: {listing.ticket_url}")
    elif listing.admission:
        notes.append(f"Admission: {listing.admission}")
    return "\n".join(notes)


def to_event(listing: Listing, review: str | None = None) -> Event:
    slug = listing.url.rstrip("/").rsplit("/", 1)[-1]
    return Event(
        uid=f"berklee-{slug}-{listing.start:%Y%m%dT%H%M}@boston-jazz-calendar",
        title=listing.title,
        venue=listing.venue,
        address=listing.address,
        start=listing.start,
        url=listing.url,
        description=_event_notes(listing),
        source="berklee",
        review=review,
    )


def select_events(listings: list[Listing], choices=None) -> list[Event]:
    """Jazz shows by faculty or visiting artists, plus held-back maybes."""
    include, exclude = choices if choices is not None else load_choices()
    events = {}
    for listing in listings:
        key = listing.url.rstrip("/")
        if key in exclude:
            continue
        decision, reason = classify(listing)
        if key in include and not listing.canceled:
            decision = "include"
        if decision == "skip":
            continue
        event = to_event(listing, review=reason if decision == "review" else None)
        events.setdefault(event.uid, event)
    return list(events.values())


def fetch_event_pages(session=None, delay: float = REQUEST_DELAY, until: datetime | None = None) -> list[str]:
    """Download pages of the events list until we pass `until`, waiting between requests."""
    session = session or requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    until = until or datetime.now(BOSTON) + timedelta(weeks=WEEKS_AHEAD)

    pages = []
    for page in range(MAX_PAGES):
        if page:
            time.sleep(delay)
        response = session.get(EVENTS_URL, params={"page": page} if page else None, timeout=30)
        response.raise_for_status()
        pages.append(response.text)
        starts = [listing.start for listing in parse_listings(response.text)]
        has_next = f'?page={page + 1}"' in response.text
        if not starts or max(starts) > until or not has_next:
            break
    return pages


def scrape(session=None, delay: float = REQUEST_DELAY, until: datetime | None = None, choices=None) -> list[Event]:
    until = until or datetime.now(BOSTON) + timedelta(weeks=WEEKS_AHEAD)
    listings = [
        listing
        for html in fetch_event_pages(session, delay, until)
        for listing in parse_listings(html)
        if listing.start <= until
    ]
    return select_events(listings, choices)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for event in scrape():
        print(event.start, "|", event.title, "|", event.review or "in calendar")
