"""No-class days, and keeping events off them.

Owner: Guru. A holiday is an all-day "other" event whose title or quote says there is no class
("Veteran's Day Holiday", "No class Thursday 11/26 (Thanksgiving)"); the UI already shades those
days. The schema has no exception-date field, so nothing new is stored:
  * a weekly class or office hour skips holidays (EXDATE in the .ics, a gap in the UI calendar)
  * a one-off event whose date was estimated moves off a holiday to the next class day
  * a one-off event the syllabus itself dates on a holiday stays, flagged for review
    (sycal/validate.py does both)

Works on raw event dicts and on schema Events alike.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from sycal.meetings import BYDAY

_HOLIDAY_RE = re.compile(
    r"holiday|\bno (?:class|lecture|school|lab|discussion|section)(?:es|s)?\b|campus (?:is )?closed|"
    r"university (?:is )?closed|thanksgiving|veteran|labor day|memorial day|independence day|juneteenth|"
    r"martin luther|\bmlk\b|president'?s'? day|cesar chavez|spring break|winter break|fall break|\brecess\b",
    re.I,
)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


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


def gives_date(citation: str, day: date) -> bool:
    """Whether the quote itself puts the event on `day` ("10/14", "Oct. 14", "Week 6 Thursday"),
    as opposed to the model estimating it from "5 in-class quizzes"."""
    quote = citation.lower()
    return bool(
        day.isoformat() in quote
        or re.search(rf"\b0?{day.month}/0?{day.day}\b", quote)
        or re.search(rf"\b{_MONTHS[day.month - 1]}[a-z]*\.?\s*0?{day.day}(?:st|nd|rd|th)?\b", quote)
        or re.search(r"\bweek\s*\d+", quote)
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
