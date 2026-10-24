"""Run every venue scraper and write the combined calendar file.

Usage: python3 -m jazzcal.build
"""

import logging
import sys
from pathlib import Path

from jazzcal.ics import to_ics
from jazzcal.scrapers import berklee, scullers

log = logging.getLogger(__name__)

OUTPUT_FILE = Path("output/boston-jazz.ics")
REVIEW_FILE = Path("output/review.txt")

# Add new venues here.
SCRAPERS = {
    "Scullers": scullers.scrape,
    "Berklee": berklee.scrape,
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


def review_text(held_back) -> str:
    """A plain list of events the scrapers weren't sure about."""
    lines = [
        "Events held back for you to decide on. They are NOT in the calendar.",
        "To include or exclude one for good, paste its page address into",
        "choices/berklee.toml.",
        "",
    ]
    if not held_back:
        lines.append("Nothing to review this week.")
    for event in sorted(held_back, key=lambda e: e.start):
        lines += [
            f"{event.start:%a %b %d, %-I:%M%p} | {event.title}",
            f"  Why: {event.review}",
            f"  Page: {event.url}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    events = run_scrapers()
    calendar = [e for e in events if not e.review]
    held_back = [e for e in events if e.review]
    if not calendar:
        log.error("No events found from any venue; not writing an empty calendar")
        return 1
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_bytes(to_ics(calendar))
    REVIEW_FILE.write_text(review_text(held_back))
    flagged = sum(1 for e in calendar if e.flag)
    log.info("Wrote %d events to %s (%d need a time check)", len(calendar), OUTPUT_FILE, flagged)
    log.info("%d events held back for review in %s", len(held_back), REVIEW_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
