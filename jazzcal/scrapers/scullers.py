"""Scraper for Scullers Jazz Club (https://scullersjazz.com/calendar/).

Scullers has no calendar feed or API. Its calendar page loads empty, then a
WordPress plugin (MusicIDB) asks the site's server for the event list as HTML,
15 shows per page. We make that same request and read the HTML.
"""

import copy
import logging
import re
import time
from datetime import datetime, time as dtime

import requests
from bs4 import BeautifulSoup

from jazzcal.event import BOSTON, Event
from jazzcal.text import BULLETS, INSTRUMENT, first_sentence, format_time

log = logging.getLogger(__name__)

VENUE = "Scullers Jazz Club"
ADDRESS = "400 Soldiers Field Road, Boston, MA 02134"
CALENDAR_URL = "https://scullersjazz.com/calendar/"
AJAX_URL = "https://scullersjazz.com/wp-admin/admin-ajax.php"
USER_AGENT = "boston-jazz-calendar/0.1 (personal concert calendar)"
REQUEST_DELAY = 3  # seconds to wait before each request to the site
MAX_PAGES = 20  # safety stop so a site bug can't make us loop forever

# Promo text venues tack onto titles, e.g. "TIM RAY TRIO - Tickets on Sale Now".
_PROMO = re.compile(
    r"tickets?\b|on sale|sold out|selling fast|almost gone|few (?:tickets|seats) left"
    r"|low tickets|limited (?:tickets|seats)|just announced|new date|rescheduled"
    r"|(?:show|date) added|added show",
    re.I,
)
_TITLE_SEPARATOR = re.compile(r"(\s+[-–—|]\s+)")
_PARENTHESES = re.compile(r"\s*\(([^)]*)\)")

# "Doors at 6pm" is not a set time, so it's removed before reading times.
_DOORS = re.compile(r"doors?\s*(?:open\s*)?(?:at\s*)?\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?", re.I)
# Matches "7pm", "9:30 PM", and groups that share one am/pm like "7 & 9pm".
_TIME_GROUP = re.compile(
    r"((?:\d{1,2}(?::\d{2})?\s*(?:&|and|/)\s*)*)(\d{1,2}(?::\d{2})?)\s*([ap])\.?m\.?(?![a-z])",
    re.I,
)
_CLOCK = re.compile(r"(\d{1,2})(?::(\d{2}))?")

# Lineup lines like "Tim Ray-piano", "BENITO GONZALEZ – PIANO", "Mike Tucker/tenor sax".
_LINEUP = re.compile(
    rf"^(?P<name>.{{2,40}}?)\s*[-–—:/]\s*(?P<instrument>{INSTRUMENT}(?:\s*(?:&|and|,|/)\s*{INSTRUMENT})*)$",
    re.I,
)
# Seating rules, refund policy and similar text that every listing repeats.
_POLICY = re.compile(
    r"GA sections?|seated by host|first come|special (?:seating|needs|requirements|accommodations)"
    r"|box office|non-refundable|cannot be exchanged|purchase all seats|please note|please call"
    r"|Scullers Jazz Club Presents",
    re.I,
)
_LINE_BREAK = "\x00"
_BREAK_TAGS = ["br", "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"]


def clean_title(raw: str) -> str:
    """Remove promo text like "Tickets on Sale Now" but keep real subtitles."""
    title = _PARENTHESES.sub(lambda m: "" if _PROMO.search(m.group(1)) else m.group(0), raw)
    parts = _TITLE_SEPARATOR.split(" ".join(title.split()))
    # parts alternates text, separator, text, ...
    while len(parts) > 1 and _PROMO.search(parts[-1]):
        del parts[-2:]
    while len(parts) > 1 and _PROMO.search(parts[0]):
        del parts[:2]
    return "".join(parts).strip()


def parse_show_times(text: str) -> list[dtime] | None:
    """Read set times from text like "Shows at 7 & 9pm".

    Returns None when no time can be read with confidence, so the caller can
    flag the event instead of guessing.
    """
    text = _DOORS.sub("", text)
    times = []
    for match in _TIME_GROUP.finditer(text):
        is_pm = match.group(3).lower() == "p"
        for clock in _CLOCK.findall(match.group(1)) + [_CLOCK.fullmatch(match.group(2)).groups()]:
            hour, minute = int(clock[0]), int(clock[1] or 0)
            if not (1 <= hour <= 12 and 0 <= minute <= 59):
                return None
            times.append(dtime(hour % 12 + (12 if is_pm else 0), minute))
    return sorted(set(times)) or None


def _description_lines(description) -> list[str]:
    """Split the venue's description into clean lines.

    Line breaks come only from real paragraph and <br> breaks, not from bold or
    styled words, and extra spaces are removed.
    """
    if description is None:
        return []
    description = copy.copy(description)  # leave the parsed page untouched
    for tag in description.find_all(_BREAK_TAGS):
        tag.insert_before(_LINE_BREAK)
        if tag.name != "br":
            tag.insert_after(_LINE_BREAK)
    lines = (" ".join(part.split()) for part in description.get_text("").split(_LINE_BREAK))
    return [line for line in lines if line]


def _showtimes_line(times: list[dtime] | None, subtitle_text: str) -> str:
    if times is None:
        said = f" (site says “{subtitle_text}”)" if subtitle_text else ""
        return f"Show time not listed{said}, check the venue"
    if len(times) == 1:
        return f"One show at {format_time(times[0])}"
    parts = [format_time(t) for t in times]
    if len({t.hour >= 12 for t in times}) == 1:
        parts = [p[:-2] for p in parts[:-1]] + parts[-1:]  # "7 & 9pm", not "7pm & 9pm"
    return "Shows at " + ", ".join(parts[:-1]) + " & " + parts[-1]


def _event_notes(title, description, times, subtitle_text, ticket_url) -> str:
    """Short notes: who's playing, showtimes, one sentence, show page, tickets."""
    lineup, paragraphs = [], []
    for line in _description_lines(description):
        if _POLICY.search(line):
            continue
        if match := _LINEUP.match(line):
            lineup.append(f"{match['name']} ({match['instrument'].lower()})")
        elif (
            paragraphs
            and len(paragraphs[-1]) >= 40
            and paragraphs[-1][0] not in BULLETS
            and not paragraphs[-1].endswith((".", "!", "?", ":", "\"", "”", ")"))
        ):
            paragraphs[-1] += " " + line  # sentence was split by a stray line break
        else:
            paragraphs.append(line)

    notes = [f"{title}: {', '.join(lineup)}" if lineup else title]
    notes.append(_showtimes_line(times, subtitle_text))
    if sentence := first_sentence(paragraphs):
        notes.append(sentence)
    notes.append(f"Scullers calendar: {CALENDAR_URL}")
    if ticket_url:
        notes.append(f"Tickets: {ticket_url}")
    return "\n".join(notes)


def _parse_listing(li) -> list[Event]:
    event_id = li["id"].removeprefix("event-")
    title = clean_title(li.select_one(".titleofevent a").get_text(" ", strip=True))
    day = datetime.strptime(li.select_one("h3.date")["title"], "%a %b %d, %Y").date()

    link = li.select_one("a.TicketLink") or li.select_one(".eventPosterArea a")
    ticket_url = link["href"] if link else None
    subtitle = li.select_one(".subtitleEvent")
    subtitle_text = subtitle.get_text(" ", strip=True) if subtitle else ""
    times = parse_show_times(subtitle_text)

    common = dict(
        venue=VENUE,
        address=ADDRESS,
        url=ticket_url or CALENDAR_URL,
        description=_event_notes(
            title, li.select_one(".eventDescription"), times, subtitle_text, ticket_url
        ),
        source="scullers",
    )

    if times is None:
        flag = f"Couldn't read the show time from {subtitle_text!r}. Check {CALENDAR_URL}"
        log.warning("Scullers event %s (%s): %s", event_id, title, flag)
        return [Event(uid=f"scullers-{event_id}@boston-jazz-calendar", title=title,
                      start=day, flag=flag, **common)]

    return [
        Event(
            uid=f"scullers-{event_id}-{t:%H%M}@boston-jazz-calendar",
            # With two sets, say which one so the entries are easy to tell apart.
            title=f"{title} ({format_time(t)} show)" if len(times) > 1 else title,
            start=datetime.combine(day, t, tzinfo=BOSTON),
            **common,
        )
        for t in times
    ]


def parse_events(html: str) -> list[Event]:
    """Turn one page of the event list into Events."""
    events = []
    for li in BeautifulSoup(html, "html.parser").select('li.listEvent[id^="event-"]'):
        try:
            events.extend(_parse_listing(li))
        except (AttributeError, KeyError, TypeError, ValueError):
            # One odd listing shouldn't stop the rest from being read.
            log.exception("Skipping Scullers listing %s that couldn't be read", li.get("id"))
    return events


def total_pages(html: str) -> int | None:
    field = BeautifulSoup(html, "html.parser").select_one("input.totalPages")
    value = field.get("value", "") if field else ""
    return int(value) if value.isdigit() else None


def read_list_settings(calendar_html: str) -> dict[str, str]:
    """Pull the settings the event-list request needs from the calendar page.

    The "nonce" is a short-lived code the site checks on each request.
    """
    nonce = re.search(r'"ajax_nonce":"(\w+)"', calendar_html)
    if not nonce:
        raise ValueError("Scullers calendar page has no ajax_nonce; the site may have changed")
    soup = BeautifulSoup(calendar_html, "html.parser")

    def field(field_id: str, default: str) -> str:
        tag = soup.find("input", id=field_id)
        return tag.get("value") or default if tag else default

    return {
        "nonce": nonce.group(1),
        "entity_id": field("entityIdParam", "venue:715"),
        "results_per_page": field("resultsPerPage", "15"),
    }


def fetch_event_pages(session=None, delay: float = REQUEST_DELAY) -> list[str]:
    """Download every page of upcoming events, waiting between requests."""
    session = session or requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    response = session.get(CALENDAR_URL, timeout=30)
    response.raise_for_status()
    settings = read_list_settings(response.text)

    pages = []
    for page in range(1, MAX_PAGES + 1):
        time.sleep(delay)
        response = session.post(
            AJAX_URL,
            data={
                "action": "load_events_list",
                "security": settings["nonce"],
                "largePics": "false",
                "listType": "upcoming",
                "resultsPerPage": settings["results_per_page"],
                "page": page,
                "descrip": "1",
                "buttons": "left",
                "entity_id": settings["entity_id"],
                "entity_type": "",
                "list_style": "full",
                "show_venue": "hide",
                "show_artist": "show",
            },
            headers={"Referer": CALENDAR_URL},
            timeout=30,
        )
        response.raise_for_status()
        pages.append(response.text)
        last_page = total_pages(response.text)
        if last_page is None or page >= last_page or 'id="event-' not in response.text:
            break
    return pages


def scrape(session=None, delay: float = REQUEST_DELAY) -> list[Event]:
    events = {}
    for html in fetch_event_pages(session, delay):
        for event in parse_events(html):
            events.setdefault(event.uid, event)
    return list(events.values())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for event in scrape():
        print(event.start, "|", event.title, "|", event.flag or event.url)
