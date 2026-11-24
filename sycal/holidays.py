"""No-class days (holidays and finals week), and keeping events off them.

Owner: Guru. A holiday is an all-day "other" event whose title or quote says there is no class
("Veteran's Day Holiday", "No class Thursday 11/26 (Thanksgiving)"); the UI already shades those
days. The schema has no exception-date field, so nothing new is stored:
  * a weekly class or office hour skips holidays (EXDATE in the .ics, a gap in the UI calendar)
  * a one-off event whose date was estimated moves off a holiday to the next class day
  * a one-off event the syllabus itself dates on a holiday stays, flagged for review
    (sycal/validate.py does both)
  * holidays written in the syllabus but missing from the agent's events are added

Finals week is the last week of the term (the term end includes finals): weekly meetings stop
before it and estimated dates stay out of it.

Works on raw event dicts and on schema Events alike.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from sycal.meetings import BYDAY, guess_course

_HOLIDAY_RE = re.compile(
    r"holiday|\bno (?:class|lecture|school|lab|discussion|section)(?:es|s)?\b|campus (?:is )?closed|"
    r"university (?:is )?closed|thanksgiving|veteran|labor day|memorial day|independence day|juneteenth|"
    r"martin luther|\bmlk\b|president'?s'? day|cesar chavez|spring break|winter break|fall break|\brecess\b",
    re.I,
)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
# "Nov. 11", "November 26th", "11/26" (not "01/06/2025", which is a range end, not a day off)
_LINE_DATE_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*(\d{1,2})(?:st|nd|rd|th)?\b"
    r"|\b(\d{1,2})/(\d{1,2})\b(?!/)",
    re.I,
)


def _get(ev: object, key: str):
    return ev.get(key) if isinstance(ev, dict) else getattr(ev, key, None)


def _day(ev: object) -> date | None:
    try:
        return date.fromisoformat(str(_get(ev, "date")))
    except ValueError:
        return None


def _weekdays(rule: str) -> set[int]:
    m = re.search(r"BYDAY=([^;]*)", rule, re.I)
    days = (d.strip().upper()[-2:] for d in m.group(1).split(",")) if m else ()
    return {BYDAY.index(d) for d in days if d in BYDAY}


def is_holiday(ev: object) -> bool:
    """An all-day, one-time "other" event that marks a day without class."""
    return (
        _get(ev, "type") == "other"
        and not _get(ev, "start")
        and not _get(ev, "recurrence")
        and bool(_HOLIDAY_RE.search(f"{_get(ev, 'title')} {_get(ev, 'citation')}"))
    )


def holiday_dates(events) -> dict[date, str]:
    """{date: holiday title} for every holiday event."""
    return {day: _get(ev, "title") for ev in events if is_holiday(ev) and (day := _day(ev))}


def class_days(events) -> set[int]:
    """Weekdays (0=Monday) the weekly class meetings fall on."""
    return {d for ev in events if _get(ev, "type") == "class" for d in _weekdays(str(_get(ev, "recurrence") or ""))}


def next_class_day(day: date, holidays: dict[date, str], weekdays: set[int]) -> date:
    """First day after `day` that is a class day (any weekday if none are known) and not a holiday."""
    weekdays = weekdays or {0, 1, 2, 3, 4}
    nxt = day + timedelta(days=1)
    while nxt.weekday() not in weekdays or nxt in holidays:
        nxt += timedelta(days=1)
    return nxt


def prev_class_day(day: date, holidays: dict[date, str], weekdays: set[int]) -> date:
    """Last day before `day` that is a class day (any weekday if none are known) and not a holiday."""
    weekdays = weekdays or {0, 1, 2, 3, 4}
    prev = day - timedelta(days=1)
    while prev.weekday() not in weekdays or prev in holidays:
        prev -= timedelta(days=1)
    return prev


def finals_week_start(term_start: str, term_end: str) -> date | None:
    """Monday of the term's last week, which is finals week (the term end includes finals).
    None for a term too short to have one."""
    start, end = date.fromisoformat(term_start), date.fromisoformat(term_end)
    monday = end - timedelta(days=end.weekday())
    return monday if monday - start >= timedelta(weeks=4) else None


def in_finals_week(day: date, term_start: str, term_end: str) -> bool:
    finals = finals_week_start(term_start, term_end)
    return finals is not None and finals <= day <= date.fromisoformat(term_end)


def _on_line(line: str, term_start: date, term_end: date):
    """(day, name in parentheses after it) for each date on a line that falls in the term."""
    for m in _LINE_DATE_RE.finditer(line):
        month = _MONTHS.index(m.group(1).lower()[:3]) + 1 if m.group(1) else int(m.group(3))
        dd = int(m.group(2) or m.group(4))
        for year in sorted({term_start.year, term_end.year}):
            try:
                day = date(year, month, dd)
            except ValueError:
                continue
            if term_start <= day <= term_end:
                name = re.match(r"\s*\(([^)]{2,40})\)", line[m.end() :])
                yield day, (name.group(1) if name else None), m.group(0)
                break


_ROW_DAYS = {"m": 0, "mon": 0, "monday": 0, "t": 1, "tu": 1, "tue": 1, "tues": 1, "tuesday": 1, "w": 2, "wed": 2,
             "wednesday": 2, "r": 3, "th": 3, "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "f": 4, "fri": 4, "friday": 4}  # fmt: skip
_NO_CLASS_CELL_RE = re.compile(r"^(?:n/?a|no class(?:es)?|no lecture|holiday|campus closed|-+)$", re.I)


def _table_days_off(line: str, header: list[str], term_start: date):
    """Days a week-by-weekday schedule grid marks "N/A" / "no class": in the row
    "| M | Intro | 8.1 | N/A |" under "| Week | 1 (1.6- 1.12) | 2 (...) | 3 (...) |", Monday of week 3."""
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    weekday = _ROW_DAYS.get(cells[0].lower().rstrip(".")) if cells else None
    if weekday is None:
        return
    week1 = term_start - timedelta(days=term_start.weekday())
    for cell, head in zip(cells[1:], header[1:]):
        week = re.match(r"\s*(\d{1,2})\b", head)
        if week and _NO_CLASS_CELL_RE.match(cell):
            yield week1 + timedelta(weeks=int(week.group(1)) - 1, days=weekday)


def holiday_events(text: str, term_start: str, term_end: str, course: str = "") -> list[dict]:
    """A no-class event for every date on a syllabus line that names a holiday
    ("Holidays Nov. 11 (Veteran's Day), Nov. 26 (Thanksgiving)"), and for every "N/A" cell
    of a week-by-weekday schedule grid."""
    start, end = date.fromisoformat(term_start), date.fromisoformat(term_end)
    course = course or guess_course(text)
    events, page, header = [], 1, None
    for line in text.splitlines():
        if m := re.match(r"=== page (\d+) ===", line):
            page = int(m.group(1))
            continue
        if line.startswith("|"):
            if re.match(r"\|\s*week\b", line, re.I):
                header = [c.strip() for c in line.strip().strip("|").split("|")]
            elif header:
                for day in _table_days_off(line, header, start):
                    if start <= day <= end:
                        events.append({
                            "course": course, "title": "No class", "type": "other", "date": day.isoformat(),
                            "start": None, "end": None, "recurrence": None,
                            "citation": f"p.{page}: '{line.strip()}'", "confidence": "high",
                        })  # fmt: skip
        else:
            header = None
        if not _HOLIDAY_RE.search(line):
            continue
        for day, name, said in _on_line(line, start, end):
            # In a table row, quote just the cell with the date, so its weekday is the only one named.
            quote = next((c.strip() for c in line.split("|") if said in c), line.strip()) if "|" in line else line.strip()
            events.append({
                "course": course, "title": f"No class ({name})" if name else "No class", "type": "other",
                "date": day.isoformat(), "start": None, "end": None, "recurrence": None,
                "citation": f"p.{page}: '{quote}'", "confidence": "high",
            })  # fmt: skip
    return events


def missing_holidays(raw_events: list, text: str, term_start: str, term_end: str, course: str = "") -> list[dict]:
    """Holidays in the syllabus text that the agent's events don't already mark."""
    taken = set(holiday_dates(raw_events))
    course = course or next((ev["course"] for ev in raw_events if isinstance(ev, dict) and ev.get("course")), "")
    added = []
    for ev in holiday_events(text, term_start, term_end, course):
        if ev["date"] not in {d.isoformat() for d in taken}:
            taken.add(date.fromisoformat(ev["date"]))
            added.append(ev)
    return added


def gives_date(citation: str, day: date) -> bool:
    """Whether the quote itself puts the event on `day` ("10/14", "Oct. 14", "Week 6 Thursday"),
    as opposed to the model estimating it from "5 in-class quizzes"."""
    quote = citation.lower()
    return bool(
        day.isoformat() in quote
        or re.search(rf"\b0?{day.month}/0?{day.day}\b", quote)
        or re.search(rf"\b{_MONTHS[day.month - 1]}[a-z]*\.?\s*0?{day.day}(?:st|nd|rd|th)?\b", quote)
        or re.search(r"\bweeks?\s*\d+", quote)
    )


def skipped_holidays(ev: object, holidays: dict[date, str]) -> list[date]:
    """Holidays a weekly event would otherwise land on; calendars leave these days out."""
    rule = str(_get(ev, "recurrence") or "")
    first = _day(ev)
    if not rule or first is None or _get(ev, "type") == "other":
        return []
    weekdays = _weekdays(rule) or {first.weekday()}
    until = re.search(r"UNTIL=(\d{8})", rule)
    last = datetime.strptime(until.group(1), "%Y%m%d").date() if until else date.max
    return [d for d in sorted(holidays) if first <= d <= last and d.weekday() in weekdays]
