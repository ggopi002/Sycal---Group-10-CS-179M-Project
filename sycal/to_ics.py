"""events.json -> .ics calendar + "needs review" list.

PLACEHOLDER - owner: Guru. Working first version; extend as needed (locations, alarms,
per-course calendars). Low-confidence events get a "[VERIFY]" prefix in the calendar itself
so a student sees the warning even if they never open review.md.

Usage:
    python -m sycal.to_ics outputs/run/events.json -o outputs/run/out.ics --review outputs/run/review.md
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Calendar
from icalendar import Event as VEvent
from icalendar import vRecur

from sycal.schema import Event, EventFile, load_event_file

TIMEZONE = ZoneInfo("America/Los_Angeles")
VERIFY_PREFIX = "[VERIFY] "


def _uid(ev: Event) -> str:
    key = "|".join([ev.course, ev.title, ev.type, ev.date, ev.start or ""])
    return hashlib.sha1(key.encode()).hexdigest()[:16] + "@sycal"


def _at(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(hhmm), tzinfo=TIMEZONE)


def to_calendar(event_file: EventFile) -> Calendar:
    cal = Calendar()
    cal.add("prodid", "-//SyCal.ai//CS 179M Group 10//EN")
    cal.add("version", "2.0")
    for ev in event_file.events:
        vevent = VEvent()
        vevent.add("uid", _uid(ev))
        vevent.add("dtstamp", datetime.now(TIMEZONE))
        summary = f"{ev.course}: {ev.title}"
        vevent.add("summary", (VERIFY_PREFIX if ev.confidence == "low" else "") + summary)
        vevent.add("description", f"Source: {ev.citation}")
        vevent.add("categories", [ev.type])
        if ev.start is None:
            vevent.add("dtstart", ev.day)
            vevent.add("dtend", ev.day + timedelta(days=1))
        else:
            vevent.add("dtstart", _at(ev.day, ev.start))
            vevent.add("dtend", _at(ev.day, ev.end or ev.start))
        if ev.recurrence:
            rule = vRecur.from_ical(ev.recurrence.removeprefix("RRULE:"))
            until = rule.get("UNTIL", [None])[0]
            if ev.start is not None and isinstance(until, date) and not isinstance(until, datetime):
                # RFC 5545: a timed DTSTART needs a UTC UNTIL; treat a bare date as end of that day locally.
                rule["UNTIL"] = [datetime.combine(until, time(23, 59, 59), tzinfo=TIMEZONE).astimezone(UTC)]
            vevent.add("rrule", rule)
        cal.add_component(vevent)
    return cal


def review_markdown(event_file: EventFile) -> str:
    low = [ev for ev in event_file.events if ev.confidence == "low"]
    lines = [f"# Needs review: {event_file.syllabus}", ""]
    if not low:
        lines.append("No low-confidence events.")
    for ev in low:
        when = ev.date + (f" {ev.start}" if ev.start else "") + (f"-{ev.end}" if ev.end else "")
        lines.append(f"- [ ] **{ev.title}** ({ev.type}) on {when}  \n  Source: {ev.citation}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("events")
    parser.add_argument("-o", "--output", required=True, help=".ics path")
    parser.add_argument("--review", help="write the needs-review list here")
    args = parser.parse_args(argv)

    event_file = load_event_file(args.events)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_bytes(to_calendar(event_file).to_ical())
    if args.review:
        Path(args.review).write_text(review_markdown(event_file), encoding="utf-8")
    n_low = sum(ev.confidence == "low" for ev in event_file.events)
    print(f"wrote {len(event_file.events)} event(s) to {args.output}; {n_low} need review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
