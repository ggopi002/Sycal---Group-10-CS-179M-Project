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
  * citation quote appears in the extracted syllabus text (only with --text; with --fix a
    missing quote sets confidence low instead of failing)

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
from difflib import SequenceMatcher
from pathlib import Path

from icalendar import vRecur

from sycal.schema import check_event

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WEEKDAY_ALIASES = {
    "mon": 0, "monday": 0, "mondays": 0,
    "tue": 1, "tues": 1, "tuesday": 1, "tuesdays": 1,
    "wed": 2, "wednesday": 2, "wednesdays": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "thursdays": 3,
    "fri": 4, "friday": 4, "fridays": 4,
    "sat": 5, "saturday": 5, "saturdays": 5,
    "sun": 6, "sunday": 6, "sundays": 6,
}  # fmt: skip
_WEEKDAY_RE = re.compile(r"\b(" + "|".join(sorted(_WEEKDAY_ALIASES, key=len, reverse=True)) + r")\b\.?", re.I)
# Compact schedule codes like "MWF", "TTh", "TR" (case-sensitive, two or more days).
_COMPACT_RE = re.compile(r"\b((?:M|Tu|Th|T|W|R|F){2,})\b")
_COMPACT_DAY = {"M": 0, "T": 1, "Tu": 1, "W": 2, "Th": 3, "R": 3, "F": 4}
_BYDAY = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def named_weekdays(citation: str) -> set[int]:
    """Weekdays a citation names, as 0=Monday ... 6=Sunday."""
    quote = citation_quote(citation)
    days = {_WEEKDAY_ALIASES[m.group(1).lower()] for m in _WEEKDAY_RE.finditer(quote)}
    for m in _COMPACT_RE.finditer(quote):
        days |= {_COMPACT_DAY[d] for d in re.findall(r"Tu|Th|M|T|W|R|F", m.group(1))}
    return days
_PAGE_PREFIX_RE = re.compile(r"^\s*p(?:age)?\.?\s*\d+\s*[:,\-]?\s*", re.I)
_MULTI_QUOTE_RE = re.compile(r"(?<=['’\"])\s*[,;]\s*(?=p(?:age)?\.?\s*\d+\s*:)", re.I)


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


def _closest(citation: str, text: str) -> tuple[str, int, float] | None:
    """(line or table cell, its page, similarity) most like the quote, if any is at all close."""
    quote = normalize(citation_quote(citation))
    if not quote:
        return None
    best, best_score, page = None, 0.6, 1
    for line in text.splitlines():
        if m := re.match(r"=== page (\d+) ===", line):
            page = int(m.group(1))
            continue
        cells = [line.strip()]
        if line.startswith("|"):
            cells += [cell.strip() for cell in line.strip("|").split("|") if cell.strip()]
        for cand in cells:
            # Share of the quote found in the line, so a short quote from a long line
            # ("MWF 8:00-8:50" in "Schedule: MWF 8:00 a.m.-8:50 a.m.") still scores high.
            blocks = SequenceMatcher(None, quote, normalize(cand), autojunk=False).get_matching_blocks()
            score = sum(b.size for b in blocks) / len(quote)
            if score > best_score:
                best, best_score = (cand, page), score
    return (*best, best_score) if best else None


def closest_line(citation: str, text: str) -> str | None:
    """Shown in the error so the agent can copy the real words instead of guessing again."""
    found = _closest(citation, text)
    return found[0] if found else None


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
    named = named_weekdays(ev["citation"])
    if byday and named and named != {_BYDAY.index(d) for d in byday}:
        said = ",".join(_BYDAY[d] for d in sorted(named))
        errors.append(f"citation names {said} but recurrence BYDAY is {','.join(byday)}; use BYDAY={said}")
    elif byday and _BYDAY[first.weekday()] not in byday:  # only meaningful once BYDAY is right
        # Give the corrected date: small models can't work out "the next Wednesday" themselves.
        fixed = next(first + timedelta(days=k) for k in range(7) if _BYDAY[(first + timedelta(days=k)).weekday()] in byday)
        errors.append(
            f"date {ev['date']} is a {WEEKDAYS[first.weekday()].title()} but recurrence BYDAY is "
            f"{','.join(byday)}; the first {','.join(byday)} on or after it is {fixed.isoformat()}, so set date to that"
        )
    until = rule.get("UNTIL", [None])[0]
    if until is None and "COUNT" not in rule:
        errors.append("recurrence has no UNTIL or COUNT, so it would repeat forever; add UNTIL=<last day YYYYMMDD>")
    elif until is not None:
        until_day = until.date() if hasattr(until, "date") else until
        if until_day > term_end:
            errors.append(f"recurrence UNTIL {until_day.isoformat()} is after the term ends ({term_end.isoformat()})")
    return errors


def validate_events(
    raw_events: list, term_start: str, term_end: str, text: str | None = None, *, strict_citations: bool = True
) -> list[str]:
    """Return one human-readable error string per problem (empty list = valid)."""
    by_event = errors_by_event(raw_events, term_start, term_end, text, strict_citations=strict_citations)
    return [e for i in sorted(by_event) for e in by_event[i]]


def errors_by_event(
    raw_events: list, term_start: str, term_end: str, text: str | None = None, *, strict_citations: bool = True
) -> dict[int, list[str]]:
    """{1-based event index: its error strings}, only for events with errors.
    strict_citations=False skips the citation check (the caller flags those events instead)."""
    t_start, t_end = date.fromisoformat(term_start), date.fromisoformat(term_end)
    by_event: dict[int, list[str]] = {}
    seen: dict[tuple, int] = {}
    n = len(raw_events)

    for i, ev in enumerate(raw_events, 1):
        label = f"event {i} of {n}"
        if isinstance(ev, dict) and ev.get("title"):
            label += f" ({ev['title']})"
        errors = by_event.setdefault(i, [])

        shape = check_event(ev)
        if shape:
            errors.extend(f"{label}: {p}" for p in shape)
            continue

        day = date.fromisoformat(ev["date"])
        if not t_start <= day <= t_end:
            errors.append(f"{label}: date {ev['date']} is outside the term ({term_start} to {term_end})")

        if ev.get("recurrence"):
            errors.extend(f"{label}: {e}" for e in _recurrence_errors(ev, t_end))
        elif ev["type"] in ("class", "office_hours") and len(named_weekdays(ev["citation"])) >= 2:
            # "TTh 9:30-10:50" is a weekly meeting; as a one-off it would put one lecture on the calendar.
            days = ",".join(_BYDAY[d] for d in sorted(named_weekdays(ev["citation"])))
            errors.append(
                f"{label}: citation names weekly meeting days {days} but recurrence is null; "
                f"add recurrence FREQ=WEEKLY;BYDAY={days};UNTIL=<last class day YYYYMMDD>"
            )
        else:
            named = named_weekdays(ev["citation"])
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

        if strict_citations and text is not None and not is_grounded(ev["citation"], text):
            near = closest_line(ev["citation"], text)
            hint = f"; the closest line is '{near}', so copy words from it exactly" if near else ""
            errors.append(f"{label}: citation quote not found in the syllabus text{hint}")

    return {i: errors for i, errors in by_event.items() if errors}


def flag_ungrounded(raw_events: list, text: str) -> list[str]:
    """Set confidence low on valid events whose citation isn't in the text, so they get a
    [VERIFY] tag instead of failing the check. Wording isn't worth a rewrite of the file."""
    flagged = []
    for i, ev in enumerate(raw_events, 1):
        if not check_event(ev) and not is_grounded(ev["citation"], text):
            ev["confidence"] = "low"
            flagged.append(f"needs review, event {i} ({ev['title']}): citation not found in the syllabus text, set confidence low")
    return flagged


# Format slips with only one possible meaning. Fixing them in code takes no model step;
# asking a small model to fix them costs a full rewrite of events.json, sometimes many.
_TYPE_SYNONYMS = {
    "lecture": "class", "lab": "class", "discussion": "class", "section": "class", "seminar": "class",
    "quiz": "exam", "midterm": "exam", "final": "exam", "test": "exam",
    "homework": "assignment", "hw": "assignment", "project": "assignment", "deadline": "assignment",
    "holiday": "other", "no_class": "other", "office hours": "office_hours", "officehours": "office_hours",
}  # fmt: skip
_BYDAY_NAMES = {
    "MON": "MO", "TUE": "TU", "TUES": "TU", "WED": "WE", "THU": "TH", "THUR": "TH", "THURS": "TH",
    "FRI": "FR", "SAT": "SA", "SUN": "SU",
}  # fmt: skip
_CLOCK_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?(?::\d{2})?\s*([ap])?\.?\s*m?\.?\s*$", re.I)


def _repair_time(value: str) -> str | None:
    m = _CLOCK_RE.match(value)
    if not m:
        return None
    hour, minute, half = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if half == "p" and hour < 12:
        hour += 12
    elif half == "a" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59 or (not half and m.group(2) is None):
        return None  # a bare "9" is too ambiguous to guess
    return f"{hour:02d}:{minute:02d}"


def repair_event(ev: object) -> list[str]:
    """Fix unambiguous format slips in one raw event, in place. Returns what was changed."""
    if not isinstance(ev, dict):
        return []
    fixes = []
    if "confidence" not in ev:  # unstated confidence is the safe default: the event gets [VERIFY]
        ev["confidence"] = "low"
        fixes.append("confidence missing -> low")
    kind = ev.get("type")
    if isinstance(kind, str) and kind.strip().lower() in _TYPE_SYNONYMS:
        ev["type"] = _TYPE_SYNONYMS[kind.strip().lower()]
        fixes.append(f"type {kind} -> {ev['type']}")
    for key in ("start", "end"):
        value = ev.get(key)
        if isinstance(value, str) and value and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
            fixed = _repair_time(value)
            if fixed:
                ev[key] = fixed
                fixes.append(f"{key} {value} -> {fixed}")
    rule = ev.get("recurrence")
    if isinstance(rule, str):
        def fix_byday(m: re.Match) -> str:
            days = [_BYDAY_NAMES.get(d.strip().upper(), d.strip().upper()) for d in m.group(1).split(",")]
            return "BYDAY=" + ",".join(days)

        fixed = re.sub(r"BYDAY=([^;]*)", fix_byday, rule, flags=re.I)
        if fixed != rule:
            ev["recurrence"] = fixed
            fixes.append(f"recurrence {rule} -> {fixed}")
    return fixes


def repair_against_text(ev: object, text: str | None) -> list[str]:
    """Fixes that need the syllabus: snap a near-miss citation to the real line, and move a
    recurring event's first date onto its meeting day. Returns what was changed."""
    if check_event(ev):
        return []
    fixes = []
    if text is not None and not is_grounded(ev["citation"], text):
        # A citation may glue several quotes together ("p.1: 'A', p.1: 'B'"); each part must
        # land on the same real line for the snap to be safe.
        parts = _MULTI_QUOTE_RE.split(ev["citation"])
        lines = set()
        for part in parts:
            found = _closest(part, text)
            quote = citation_quote(part)
            # Wording only: if the numbers differ (dates, times, HW1 vs HW2) it may be a different
            # event, and grounding it on someone else's line would defeat the citation check.
            if found and found[2] >= 0.9 and set(re.findall(r"\d+", quote)) <= set(re.findall(r"\d+", found[0])):
                lines.add(found[:2])
            else:
                lines.add(None)
        if len(lines) == 1 and None not in lines:
            line, page = lines.pop()
            new = f"p.{page}: '{line}'"
            fixes.append(f"citation {ev['citation']} -> {new}")
            ev["citation"] = new
    if ev.get("recurrence"):
        rule = vRecur.from_ical(str(ev["recurrence"]).removeprefix("RRULE:"))
        byday = {_BYDAY.index(str(d)[-2:]) for d in rule.get("BYDAY", [])}
        named = named_weekdays(ev["citation"])
        first = date.fromisoformat(ev["date"])
        # A grounded citation's days are the syllabus's own words; this is exactly what the
        # "use BYDAY=..." error would ask the model to do, without the model step.
        if byday and named and named != byday and text is not None and is_grounded(ev["citation"], text):
            old, new = ",".join(_BYDAY[d] for d in sorted(byday)), ",".join(_BYDAY[d] for d in sorted(named))
            ev["recurrence"] = re.sub(r"BYDAY=[^;]*", f"BYDAY={new}", str(ev["recurrence"]), flags=re.I)
            fixes.append(f"recurrence BYDAY {old} -> {new} (days named in the citation)")
            byday = named
        # Only when the days themselves agree with the syllabus; otherwise BYDAY is the thing to fix.
        if byday and (not named or named == byday) and first.weekday() not in byday:
            fixed = next(first + timedelta(days=k) for k in range(7) if (first + timedelta(days=k)).weekday() in byday)
            fixes.append(f"date {ev['date']} -> {fixed.isoformat()} (first meeting day on or after it)")
            ev["date"] = fixed.isoformat()
    return fixes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("events", help="events.json (bare list or wrapped)")
    parser.add_argument("--term-start", help="YYYY-MM-DD (default: from the events file)")
    parser.add_argument("--term-end", help="YYYY-MM-DD (default: from the events file)")
    parser.add_argument("--text", help="extracted syllabus text; enables the citation check")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="repair unambiguous format slips in the file first, and flag (not fail) citations not found in --text",
    )
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
    # updates for catching incorrect dates
    try:
        t_start, t_end = date.fromisoformat(term_start), date.fromisoformat(term_end)
    except ValueError as e:
        print(f"FAIL: term dates must be YYYY-MM-DD ({e})")
        return 2
    if t_start > t_end:
        print(f"FAIL: term start {term_start} is after term end {term_end}")
        return 2
    try:
        text = Path(args.text).read_text(encoding="utf-8") if args.text else None
    except FileNotFoundError:
        print(f"FAIL: {args.text} does not exist; run python -m sycal.extract first")
        return 2

    fixed = []
    if args.fix:
        fixed = [
            f"auto-fixed event {i}: {f}"
            for i, ev in enumerate(events, 1)
            for f in repair_event(ev) + repair_against_text(ev, text)
        ]
        if text is not None:
            fixed += flag_ungrounded(events, text)
        if fixed:
            Path(args.events).write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    errors = validate_events(events, term_start, term_end, text, strict_citations=not args.fix)
    if errors:
        print(f"FAIL: {len(errors)} error(s)")
        print("\n".join(errors + fixed))
        return 1
    print(f"OK: {len(events)} event(s), no errors")
    if fixed:
        print("\n".join(fixed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
