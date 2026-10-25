"""Check an events.json file and print errors the agent can act on.

PLACEHOLDER - owner: Guru. Working first version of the checks from the proposal plus the
citation-grounding check (our ethics mitigation). Extend the checks, but keep the output
format stable: the agent prompt relies on it.

Checks:
  * every event matches the schema (sycal/schema.py)
  * dates fall inside the term; recurring events have an UNTIL/COUNT inside the term
  * weekdays named in the citation match the date (one-off events)
  * recurring events' BYDAY includes the first date's weekday
  * no duplicate events
  * end time is after start time
  * citation quote appears in the extracted syllabus text (only with --text)

Output: "OK: ..." and exit 0, or "FAIL: N error(s)" then one line per error and exit 1.
Exit 2 means the file could not be read at all (bad JSON, wrong top-level shape).

Usage:
    python -m sycal.validate events.json --term-start 2026-09-24 --term-end 2026-12-11 --text text.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from icalendar import vRecur

from sycal.schema import check_event

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WEEKDAY_ALIASES = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "saturday": 5,
    "sunday": 6,
}  # fmt: skip
_WEEKDAY_RE = re.compile(r"\b(" + "|".join(sorted(_WEEKDAY_ALIASES, key=len, reverse=True)) + r")\b\.?", re.I)
_BYDAY = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
_PAGE_PREFIX_RE = re.compile(r"^\s*p(?:age)?\.?\s*\d+\s*[:,\-]?\s*", re.I)


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[‐-―−]", "-", text)
    text = re.sub(r"[‘’‛`]", "'", text)
    text = re.sub(r"[“”]", '"', text)
    return re.sub(r"\s+", " ", text).strip()


def citation_quote(citation: str) -> str:
    """"p.3: '10/29 - Midterm'" -> "10/29 - Midterm"."""
    return _PAGE_PREFIX_RE.sub("", citation).strip().strip("'\"‘’“”").strip()


def is_grounded(citation: str, text: str) -> bool:
    quote = normalize(citation_quote(citation))
    return bool(quote) and quote in normalize(text)


def week_table(term_start: str, term_end: str) -> list[tuple[int, date]]:
    """(week number, Monday of that week). Week 1 is the week containing term_start."""
    start, end = date.fromisoformat(term_start), date.fromisoformat(term_end)
    monday = start - timedelta(days=start.weekday())
    weeks = []
    while monday <= end:
        weeks.append((len(weeks) + 1, monday))
        monday += timedelta(days=7)
    return weeks


def format_week_table(term_start: str, term_end: str) -> str:
    return "\n".join(
        f"Week {n:>2}: Mon {m.isoformat()} ... Fri {(m + timedelta(days=4)).isoformat()}"
        for n, m in week_table(term_start, term_end)
    )


def _recurrence_errors(ev: dict, term_end: date) -> list[str]:
    rule = vRecur.from_ical(str(ev["recurrence"]).removeprefix("RRULE:"))
    errors = []
    first = date.fromisoformat(ev["date"])
    byday = [str(d)[-2:] for d in rule.get("BYDAY", [])]
    if byday and _BYDAY[first.weekday()] not in byday:
        errors.append(
            f"date {ev['date']} is a {WEEKDAYS[first.weekday()].title()} but recurrence BYDAY is "
            f"{','.join(byday)}; set date to the first actual occurrence"
        )
    until = rule.get("UNTIL", [None])[0]
    if until is None and "COUNT" not in rule:
        errors.append("recurrence has no UNTIL or COUNT, so it would repeat forever; add UNTIL=<last day YYYYMMDD>")
    elif until is not None:
        until_day = until.date() if hasattr(until, "date") else until
        if until_day > term_end:
            errors.append(f"recurrence UNTIL {until_day.isoformat()} is after the term ends ({term_end.isoformat()})")
    return errors


def validate_events(raw_events: list, term_start: str, term_end: str, text: str | None = None) -> list[str]:
    """Return one human-readable error string per problem (empty list = valid)."""
    t_start, t_end = date.fromisoformat(term_start), date.fromisoformat(term_end)
    errors: list[str] = []
    seen: dict[tuple, int] = {}
    n = len(raw_events)

    for i, ev in enumerate(raw_events, 1):
        label = f"event {i} of {n}"
        if isinstance(ev, dict) and ev.get("title"):
            label += f" ({ev['title']})"

        shape = check_event(ev)
        if shape:
            errors.extend(f"{label}: {p}" for p in shape)
            continue

        day = date.fromisoformat(ev["date"])
        if not t_start <= day <= t_end:
            errors.append(f"{label}: date {ev['date']} is outside the term ({term_start} to {term_end})")

        if ev.get("recurrence"):
            errors.extend(f"{label}: {e}" for e in _recurrence_errors(ev, t_end))
        else:
            named = {_WEEKDAY_ALIASES[m.group(1).lower()] for m in _WEEKDAY_RE.finditer(citation_quote(ev["citation"]))}
            if named and day.weekday() not in named:
                said = "/".join(WEEKDAYS[d].title() for d in sorted(named))
                errors.append(f"{label}: date {ev['date']} is a {WEEKDAYS[day.weekday()].title()} but citation says {said}")

        if ev.get("start") and ev.get("end") and ev["end"] <= ev["start"]:
            errors.append(f"{label}: end {ev['end']} is not after start {ev['start']}")

        key = (ev["type"], ev["date"], ev.get("start"), normalize(ev["title"]))
        if key in seen:
            errors.append(f"{label}: duplicate of event {seen[key]}")
        else:
            seen[key] = i

        if text is not None and not is_grounded(ev["citation"], text):
            errors.append(
                f"{label}: citation quote not found in the syllabus text; copy the exact words from text.txt"
            )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("events", help="events.json (bare list or wrapped)")
    parser.add_argument("--term-start", help="YYYY-MM-DD (default: from the events file)")
    parser.add_argument("--term-end", help="YYYY-MM-DD (default: from the events file)")
    parser.add_argument("--text", help="extracted syllabus text; enables the citation check")
    args = parser.parse_args(argv)

    try:
        raw = json.loads(Path(args.events).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"FAIL: {args.events} does not exist")
        return 2
    except json.JSONDecodeError as e:
        print(f"FAIL: {args.events} is not valid JSON: {e.msg} at line {e.lineno} column {e.colno}")
        return 2
    meta = raw if isinstance(raw, dict) else {}
    events = raw.get("events") if isinstance(raw, dict) else raw
    if not isinstance(events, list):
        print("FAIL: expected a JSON list of events")
        return 2
    term_start = args.term_start or meta.get("term_start")
    term_end = args.term_end or meta.get("term_end")
    if not (term_start and term_end):
        print("FAIL: term dates unknown; pass --term-start and --term-end")
        return 2
    text = Path(args.text).read_text(encoding="utf-8") if args.text else None

    errors = validate_events(events, term_start, term_end, text)
    if errors:
        print(f"FAIL: {len(errors)} error(s)")
        print("\n".join(errors))
        return 1
    print(f"OK: {len(events)} event(s), no errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
