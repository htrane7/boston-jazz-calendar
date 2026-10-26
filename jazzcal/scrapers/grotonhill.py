"""Scraper for Groton Hill Music Center in Groton.

Groton Hill's own site turns away automated requests (403 Forbidden), so we
read its listings from Jazz Near You instead (see jazzcal/jazznearyou.py).
Jazz Near You only lists Groton Hill's jazz shows, so there's no filtering.
"""

import logging

from jazzcal.event import Event
from jazzcal.jazznearyou import REQUEST_DELAY, scrape_venue

VENUE = "Groton Hill Music Center"
ADDRESS = "122 Old Ayer Road, Groton, MA 01450"
VENUE_URL = "https://www.jazznearyou.com/boston/venues/groton-hill-music-center"


def scrape(session=None, delay: float = REQUEST_DELAY) -> list[Event]:
    return scrape_venue(VENUE_URL, VENUE, ADDRESS, "grotonhill", session, delay)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for event in scrape():
        print(event.start, "|", event.title, "|", event.flag or event.url)
