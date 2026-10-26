# CLAUDE.md

## Goal

Collect jazz concerts from Boston venues into one calendar file (`.ics`) that
people can subscribe to.

Scrapers live in `jazzcal/scrapers/` (one file per venue). Saved web pages for
tests are in `tests/fixtures/`. Venues so far: Scullers, Berklee, Lilypad, Rockport (Shalin Liu),
Regattabar, Groton Hill.

Berklee has no genre labels, so `jazzcal/scrapers/berklee.py` sorts events by
keywords: jazz styles (wide net) played by faculty or visiting artists go in the
calendar; student shows are skipped; unsure ones go to `output/review.txt`. The
user's always-include/exclude decisions live in `choices/berklee.toml`.
Berklee's robots.txt asks for 10 seconds between requests.

Lilypad tags each show with genres; Jazz, Latin Jazz, Fusion and Improvisation
go in. Untagged shows that mention jazz go to `output/review.txt`, and your
decisions go in `choices/lilypad.toml`. The start time comes from the
description ("8pm doors / 8:30 start"), since the listed time is often doors.

Rockport: shows in the ticket site's "Jazz/R&B/Soul" filter, plus any whose
description says jazz.

Regattabar and Groton Hill are read from Jazz Near You (`jazzcal/jazznearyou.py`),
because TicketWeb's terms forbid scraping and Groton Hill's site blocks bots.
Don't try to get around those blocks. NEC is skipped for the same reason
(Cloudflare bot check).

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
