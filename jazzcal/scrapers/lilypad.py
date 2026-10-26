"""Scraper for The Lilypad in Inman Square (https://www.lilypadinman.com).

The site runs on Squarespace, which gives every page a JSON version
(add ?format=json). The homepage's JSON has every upcoming event with its
genre tags and full description, so one request is enough.

The time Squarespace lists is often the doors time; the real start is in the
first line of the description ("7:30 doors / 8pm show"), so we read that.
"""

import html
import logging
import re
from datetime import datetime, time as dtime

import requests
from bs4 import BeautifulSoup

from jazzcal.choices import CHOICES_DIR, load_choices
from jazzcal.event import BOSTON, Event
from jazzcal.text import INSTRUMENT, first_sentence, format_time

log = logging.getLogger(__name__)

VENUE = "The Lilypad"
ADDRESS = "1353 Cambridge Street, Cambridge, MA 02139"
SITE_URL = "https://www.lilypadinman.com"
JSON_URL = f"{SITE_URL}/?format=json"
USER_AGENT = "boston-jazz-calendar/0.1 (personal concert calendar)"
CHOICES_FILE = CHOICES_DIR / "lilypad.toml"

# Lilypad's genre tags that count as jazz (a wide net).
JAZZ_TAGS = {"Jazz", "Latin Jazz", "Fusion", "Improvisation"}
# Untagged shows that mention these are held back for you to decide on.
_JAZZ_WORDS = re.compile(r"\b(?:jazz|bebop|hard[- ]bop|bossa|samba|choro|big band)\b", re.I)
_SKIP_TITLE = re.compile(r"cancel+ed|postponed|private event", re.I)

# "8:30 start", "Doors 8pm", "10:15 music", "7pm", "4 - 7pm", "11pm - 1am".
_CLOCK = re.compile(r"(?<![\d$])(\d{1,2})(?::(\d{2}))?\s*([ap])?\.?m?\.?(?![\d:])", re.I)
_START_WORD = re.compile(r"start|show|music|set", re.I)
_DOORS_WORD = re.compile(r"doors?", re.I)
_PRICE = re.compile(r"\$|free|admission|suggested|donation|cover|sliding scale|students", re.I)

# "Jerry Bergonzi , Tenor Saxophone", "Allan Chase-alto & baritone saxophones",
# "Kenny Werner: piano", "John Lockwood – bass, formerly with Joe Henderson".
_LINEUP = re.compile(
    rf"^(?P<name>[A-Z][^,:]{{1,39}}?)\s*[-–—:,]\s*"
    rf"(?P<instrument>{INSTRUMENT}(?:\s*(?:&|and|,|/)\s*{INSTRUMENT})*)\s*(?:,.*)?$",
    re.I,
)
_PLACEHOLDER = "Double-click to edit"
_TICKET_LINK = re.compile(r"ticket|eventbrite|luma\.com|dice\.fm|tixr|etix|showclix", re.I)


def _paragraphs(body_html: str) -> list[str]:
    """Each paragraph's text, without Squarespace filler."""
    soup = BeautifulSoup(body_html or "", "html.parser")
    paragraphs = []
    for tag in soup.select(".sqs-html-content p, .sqs-html-content h1, .sqs-html-content h2,"
                           " .sqs-html-content h3, .sqs-html-content h4"):
        text = " ".join(tag.get_text(" ", strip=True).split())
        text = re.sub(r"\s+([,.!?;:])", r"\1", text)  # "Bergonzi , Tenor" -> "Bergonzi, Tenor"
        if text and _PLACEHOLDER not in text and text not in "-–—":
            paragraphs.append(text)
    return paragraphs


def _info_line(paragraphs: list[str], excerpt: str) -> str:
    """The "$15 / 7pm doors / 7:30 start" line: the first one with times or prices."""
    for text in paragraphs[:3]:
        if "/" in text and (_PRICE.search(text) or _CLOCK.search(text)):
            return text
    return " ".join(BeautifulSoup(excerpt or "", "html.parser").get_text(" ").split())


def _clock(hour: int, minute: int, ampm: str | None, listed: datetime) -> dtime | None:
    """A clock time; with no am/pm, pick the one closest to the listed time."""
    if hour > 12 or minute > 59:
        return None
    if ampm:
        return dtime(hour % 12 + (12 if ampm.lower() == "p" else 0), minute)
    listed_minutes = listed.hour * 60 + listed.minute
    options = [dtime(hour % 12, minute), dtime(hour % 12 + 12, minute)]
    best = min(options, key=lambda t: abs(t.hour * 60 + t.minute - listed_minutes))
    gap = abs(best.hour * 60 + best.minute - listed_minutes)
    return best if gap <= 4 * 60 else None


def read_times(info: str, listed: datetime) -> tuple[dtime | None, dtime | None]:
    """(start, doors) from the info line. Either can be None."""
    start = doors = loose = None
    for part in re.split(r"\s*/\s*", info):
        if "$" in part:
            continue  # "$5 - 15 sliding scale" is a price, not a time
        clocks = list(_CLOCK.finditer(part))
        if not clocks:
            continue
        has_start, has_doors = _START_WORD.search(part), _DOORS_WORD.search(part)
        first = clocks[0]
        # In a range like "4 - 7pm", the first time shares the second one's am/pm.
        ampm = first[3] or (clocks[1][3] if len(clocks) > 1 else None)
        if not (has_start or has_doors or ampm or first[2]):
            continue  # a bare number like "21 piece" isn't a time
        found = _clock(int(first[1]), int(first[2] or 0), ampm, listed)
        if found is None:
            continue
        if has_start:
            start = start or found
        elif has_doors:
            doors = doors or found
        else:
            loose = loose or found  # "7pm", "Every Monday at 7PM", "10pm - 1am"
    return start or loose, doors


def _admission(info: str) -> str:
    parts = [p for p in re.split(r"\s*/\s*", info) if _PRICE.search(p)]
    return " / ".join(parts)


def _lineup(paragraphs: list[str]) -> list[str]:
    lineup = []
    for text in paragraphs:
        if len(text) <= 120 and (match := _LINEUP.match(text)):
            lineup.append(f"{match['name'].strip()} ({match['instrument'].lower()})")
    return lineup


def _title_key(item: dict) -> str:
    return " ".join(html.unescape(item.get("title", "")).split()).lower()


def classify(item: dict, paragraphs: list[str], jazz_titles: set[str] = frozenset()) -> tuple[str, str | None]:
    """("include" | "review" | "skip", reason).

    jazz_titles: shows tagged as jazz on some other date. Weekly series are
    sometimes tagged on one week and not the next.
    """
    title = html.unescape(item.get("title", ""))
    if _SKIP_TITLE.search(title):
        return "skip", "canceled or private"
    if JAZZ_TAGS & set(item.get("categories") or []) or _title_key(item) in jazz_titles:
        return "include", None
    prose = [p for p in paragraphs[1:] if len(p) >= 60][:2]
    if _JAZZ_WORDS.search(" ".join([title, *prose])):
        return "review", "Mentions jazz, but Lilypad didn't tag it as jazz"
    return "skip", "not jazz"


def _event_notes(title, lineup, showtimes, sentence, url, ticket_url, admission) -> str:
    notes = [f"{title}: {', '.join(lineup)}" if lineup else title, showtimes]
    if sentence:
        notes.append(sentence)
    notes.append(f"Event page: {url}")
    if ticket_url:
        notes.append(f"Tickets: {ticket_url}")
    elif admission:
        notes.append(f"Admission: {admission}")
    return "\n".join(notes)


def to_event(item: dict, review: str | None = None) -> Event:
    title = " ".join(html.unescape(item["title"]).split())
    url = SITE_URL + item["fullUrl"]
    listed = datetime.fromtimestamp(item["startDate"] / 1000, BOSTON).replace(second=0, microsecond=0)
    texts = _paragraphs(item.get("body", ""))
    info = _info_line(texts, item.get("excerpt", ""))
    start, doors = read_times(info, listed)

    flag = None
    if start:
        begins = datetime.combine(listed.date(), start, tzinfo=BOSTON)
        showtimes = f"Starts at {format_time(start)}" + (f" (doors {format_time(doors)})" if doors else "")
    elif doors or info:
        # No start time written down: use the site's listed time and say so.
        begins = listed
        showtimes = (f"Doors at {format_time(doors)}, start time not listed" if doors
                     else f"Listed at {format_time(listed.time())}")
    else:
        begins = listed.date()
        flag = f"Couldn't read the show time. Check {url}"
        showtimes = f"Show time not listed, check {url}"
        log.warning("Lilypad event %s (%s): %s", item["id"], title, flag)

    lineup = _lineup(texts)
    prose = [t for t in texts if t != info and not _LINEUP.match(t)]
    links = BeautifulSoup(item.get("body") or "", "html.parser").select("a[href]")
    ticket_url = next(
        (a["href"] for a in links if _TICKET_LINK.search(a["href"] + " " + a.get_text())), None
    )
    return Event(
        uid=f"lilypad-{item['id']}@boston-jazz-calendar",
        title=title,
        venue=VENUE,
        address=ADDRESS,
        start=begins,
        url=url,
        description=_event_notes(title, lineup, showtimes, first_sentence(prose), url,
                                 ticket_url, _admission(info)),
        source="lilypad",
        flag=flag,
        review=review,
    )


def select_events(data: dict, choices=None) -> list[Event]:
    """Jazz shows from the homepage JSON, plus held-back maybes."""
    include, exclude = choices if choices is not None else load_choices(CHOICES_FILE)
    items = data.get("upcoming") or []
    jazz_titles = {_title_key(i) for i in items if JAZZ_TAGS & set(i.get("categories") or [])}
    events = {}
    for item in items:
        try:
            key = (SITE_URL + item["fullUrl"]).rstrip("/")
            if key in exclude:
                continue
            decision, reason = classify(item, _paragraphs(item.get("body", "")), jazz_titles)
            if key in include:
                decision = "include"
            if decision == "skip":
                continue
            event = to_event(item, review=reason if decision == "review" else None)
        except (KeyError, TypeError, ValueError):
            # One odd listing shouldn't stop the rest from being read.
            log.exception("Skipping Lilypad listing %s that couldn't be read", item.get("id"))
            continue
        events.setdefault(event.uid, event)
    return list(events.values())


def fetch_events(session=None) -> dict:
    session = session or requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    response = session.get(JSON_URL, timeout=30)
    response.raise_for_status()
    return response.json()


def scrape(session=None, choices=None) -> list[Event]:
    return select_events(fetch_events(session), choices)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for event in scrape():
        print(event.start, "|", event.title, "|", event.review or event.flag or "in calendar")
