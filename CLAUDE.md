# CLAUDE.md

## Goal

Collect jazz concerts from Boston venues into one calendar file (`.ics`) that
people can subscribe to. The project is just starting, so there's no code yet.

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
