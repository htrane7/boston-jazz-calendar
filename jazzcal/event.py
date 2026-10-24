from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

BOSTON = ZoneInfo("America/New_York")


@dataclass
class Event:
    """One concert (or one set, when a show has several) at one venue."""

    uid: str  # stays the same between runs so calendar apps don't duplicate
    title: str
    venue: str
    address: str
    # A Boston-time datetime, or just a date when the show time couldn't be read.
    start: datetime | date
    url: str | None = None
    description: str = ""
    source: str = ""
    # Set when something needs a human to check, e.g. an unreadable show time.
    flag: str | None = None
    # Why this event is held back for you to decide on. Held-back events stay
    # out of the calendar and are listed in the review file instead.
    review: str | None = None
