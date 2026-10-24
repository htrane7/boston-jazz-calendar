"""Turn Events into an iCalendar (.ics) file that calendar apps can subscribe to."""

from datetime import date, datetime, timedelta, timezone

from icalendar import Calendar, Event as IcsEvent

from jazzcal.event import Event

CALENDAR_NAME = "Boston Jazz"
# Venues don't list end times, so each set is shown as this long.
SET_LENGTH = timedelta(minutes=90)


def to_ics(events: list[Event], now: datetime | None = None) -> bytes:
    now = now or datetime.now(timezone.utc)
    cal = Calendar()
    cal.add("prodid", "-//boston-jazz-calendar//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", CALENDAR_NAME)
    cal.add("x-wr-timezone", "America/New_York")

    for event in sorted(events, key=lambda e: (str(e.start), e.uid)):
        item = IcsEvent()
        item.add("uid", event.uid)
        item.add("dtstamp", now)
        item.add("location", f"{event.venue}, {event.address}")
        description = event.description
        if event.flag:
            # Unreadable time: show as an all-day entry so nothing is made up.
            item.add("summary", f"{event.title} (time TBD)")
            item.add("dtstart", event.start)
            description = f"{event.flag}\n\n{description}"
        else:
            item.add("summary", event.title)
            item.add("dtstart", event.start)
            item.add("dtend", event.start + SET_LENGTH)
        if event.url:
            item.add("url", event.url)
            description = f"{description}\n\nTickets: {event.url}"
        item.add("description", description.strip())
        cal.add_component(item)

    # Only describe Boston's daylight-saving rules for the years we need.
    cal.add_missing_timezones(first_date=date(now.year - 1, 1, 1), last_date=date(now.year + 3, 1, 1))
    return cal.to_ical()
