"""Run every venue scraper and write the combined calendar file.

Usage: python3 -m jazzcal.build
"""

import logging
import sys
from pathlib import Path

from jazzcal.ics import to_ics
from jazzcal.scrapers import scullers

log = logging.getLogger(__name__)

OUTPUT_FILE = Path("output/boston-jazz.ics")

# Add new venues here.
SCRAPERS = {
    "Scullers": scullers.scrape,
}


def run_scrapers(scrapers=SCRAPERS):
    events = []
    for name, scrape in scrapers.items():
        try:
            found = scrape()
        except Exception:
            # One broken venue shouldn't stop the others.
            log.exception("%s scraper failed; skipping it this run", name)
            continue
        log.info("%s: %d events", name, len(found))
        events.extend(found)
    return events


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    events = run_scrapers()
    if not events:
        log.error("No events found from any venue; not writing an empty calendar")
        return 1
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_bytes(to_ics(events))
    flagged = sum(1 for e in events if e.flag)
    log.info("Wrote %d events to %s (%d need a time check)", len(events), OUTPUT_FILE, flagged)
    return 0


if __name__ == "__main__":
    sys.exit(main())
