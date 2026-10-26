"""Scraper for Regattabar in the Charles Hotel, Cambridge.

Regattabar sells tickets through TicketWeb, whose terms of use forbid automated
tools, and its own site just links there. So we read its listings from Jazz
Near You instead (see jazzcal/jazznearyou.py). Ticket links still point to
TicketWeb; we only link to them, never read them.

Every show at Regattabar is jazz, so there's no filtering.
"""

import logging

from jazzcal.event import Event
from jazzcal.jazznearyou import REQUEST_DELAY, scrape_venue

VENUE = "Regattabar"
ADDRESS = "The Charles Hotel, 1 Bennett Street, Cambridge, MA 02138"
VENUE_URL = "https://www.jazznearyou.com/boston/venue/regattabar"


def scrape(session=None, delay: float = REQUEST_DELAY) -> list[Event]:
    return scrape_venue(VENUE_URL, VENUE, ADDRESS, "regattabar", session, delay)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for event in scrape():
        print(event.start, "|", event.title, "|", event.flag or event.url)
