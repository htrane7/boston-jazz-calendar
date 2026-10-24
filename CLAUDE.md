# CLAUDE.md

## Goal

Collect jazz concerts from Boston venues into one calendar file (`.ics`) that
people can subscribe to.

Scrapers live in `jazzcal/scrapers/` (one file per venue). Saved web pages for
tests are in `tests/fixtures/`. Venues so far: Scullers, Berklee.

Berklee has no genre labels, so `jazzcal/scrapers/berklee.py` sorts events by
keywords: jazz styles (wide net) played by faculty or visiting artists go in the
calendar; student shows are skipped; unsure ones go to `output/review.txt`. The
user's always-include/exclude decisions live in `choices/berklee.toml`.
Berklee's robots.txt asks for 10 seconds between requests.

## Commands

- Run tests: `python3 -m pytest`
- Try the Scullers scraper on the live site: `python3 -m jazzcal.scrapers.scullers`
- Build the calendar from all venues: `python3 -m jazzcal.build` (writes `output/boston-jazz.ics`)

GitHub Actions (`.github/workflows/publish-calendar.yml`) runs the build every
Monday and publishes the file to GitHub Pages. New venues go in `SCRAPERS` in
`jazzcal/build.py`.

## Key rules

- Each venue gets its own scraper. If one breaks, the others still run.
- Every event needs a time zone (Boston time) and an ID that stays the same
  between runs, so calendar apps don't show duplicates.
- Never publish an empty calendar. If no events come back, stop with an error.
- Scrape politely: follow `robots.txt` and wait between requests.
- Tests use saved copies of web pages, not live sites.

## How to work with me

- Keep all responses short and in plain language.
- I'm learning GitHub and version control. Explain git ideas simply.
- Don't run git commands for me. Tell me which command to type instead.
