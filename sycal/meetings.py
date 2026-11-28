"""Find weekly meetings (lectures, labs, discussions, office hours) in extracted syllabus text.

Owner: Guru. Rule-based on purpose: a small model sometimes skips the one line that says when
class meets, and that line is the most important event in the syllabus. Syllabi write it in
many ways, so any line where a group of weekdays sits next to a clock time counts:

    Class TTh 9:30-10:50am                       Schedule: MWF 8:00 a.m.-8:50 a.m.
    Lectures : T/Th 2PM in SSC 329               Tuesday and Thursday 02:00 PM - 03:20 PM
    Section 021 Wed. 2:00pm – 3:50pm             Office hours: Wednesdays 10–11 AM
    TA Office Hours : Mohammad, Th 12-1 PM       Lecture: 9:30-10:50 AM, Tuesdays & Thursdays

A day followed by a date ("Thursday, March 20 8:00 a.m.") or an exam/deadline word is a
one-off, not a weekly meeting, and is left to the agent.

Usage:
    python -m sycal.meetings outputs/run/text.txt --term-start 2026-09-24 --term-end 2026-12-11
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

BYDAY = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")

_DAY_WORDS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tues": 1, "tue": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thurs": 3, "thur": 3, "thu": 3, "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}  # fmt: skip
_CODE_DAYS = {"M": 0, "Tu": 1, "T": 1, "W": 2, "Th": 3, "R": 3, "F": 4}
_WORD = r"(?i:" + "|".join(sorted(_DAY_WORDS, key=len, reverse=True)) + r")s?\b\.?"
# Compact codes are case-sensitive ("TTh", "MWF", "TR", single "F"), so they only count next to a time.
_CODE = r"(?:Tu|Th|M|T|W|R|F)+\b"
_DAY = rf"\b(?:{_WORD}|{_CODE})"
_RANGE_SEP = r"\s*(?:-|–|through|thru|to)\s*"
_GROUP_RE = re.compile(rf"{_DAY}(?:(?:\s*(?:,|/|&|\+|and)\s*|{_RANGE_SEP}|\s+){_DAY})*")
_DAY_RE = re.compile(_DAY)
_ENDS_WITH_DAYS_RE = re.compile(rf"(?:{_GROUP_RE.pattern})[\s,:;]*$")

_CLOCK = r"(\d{1,2})(?::([0-5]\d))?\s*(?:([ap])\.?\s?m\b\.?)?"
_TIME_RE = re.compile(rf"(?<![\d:/.]){_CLOCK}(?:\s*(?:-|–|—|to)\s*{_CLOCK})?(?![\d/]|\.\d)", re.I)

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DATE_RE = re.compile(rf"\b{_MONTH}\s*\d{{1,2}}\b|\b\d{{1,2}}/\d{{1,2}}\b|\b\d{{4}}-\d{{2}}-\d{{2}}\b", re.I)
_ONE_OFF_RE = re.compile(r"\b(exams?|finals?|midterms?|quiz(?:zes)?|due|deadline)\b", re.I)
_COURSE_RE = re.compile(r"\b([A-Z]{2,5})\s?(\d{1,3}[A-Z]{0,2})\b")

# First match wins, so "Labs Section 021" is a lab and "OFFICE HOURS AND TUTORING" office hours.
_KINDS = [
    (re.compile(r"office\s*hours?|student hours", re.I), "office_hours", "Office hours"),
    (re.compile(r"\blabs?\b|laborator", re.I), "class", "Lab"),
    (re.compile(r"discussion|recitation", re.I), "class", "Discussion"),
    (re.compile(r"lectures?|\bclass\b|schedule|\bmeets?\b|meeting|time and place", re.I), "class", "Lecture"),
]
_SECTION_RE = re.compile(r"\bsec(?:tion)?\.?\s*(\d{1,3}[A-Z]?)\b", re.I)


@dataclass
class Meeting:
    title: str
    type: str  # "class" or "office_hours"
    days: list[int]  # 0=Monday ... 6=Sunday
    start: str
    end: str | None
    page: int
    quote: str  # words copied from the syllabus, for the citation
    sure: bool  # the line, or a heading near it, says what kind of meeting this is


def _days(group: str) -> list[int]:
    tokens = list(_DAY_RE.finditer(group))
    days: set[int] = set()
    for k, tok in enumerate(tokens):
        word = tok.group(0).rstrip(".").lower()
        word = word if word in _DAY_WORDS else word.rstrip("s")
        found = [_DAY_WORDS[word]] if word in _DAY_WORDS else [_CODE_DAYS[c] for c in re.findall(r"Tu|Th|M|T|W|R|F", tok.group(0))]
        # "Mon-Fri", "M-F", "Monday through Thursday" name every day in between.
        if k and re.fullmatch(_RANGE_SEP, group[tokens[k - 1].end() : tok.start()]) and days:
            days |= set(range(max(days), found[0] + 1))
        days |= set(found)
    return sorted(days)


def _days_before(window: str) -> list[int] | None:
    groups = list(_GROUP_RE.finditer(window))
    if not groups:
        return None
    group, gap = groups[-1], window[groups[-1].end() :]
    if re.fullmatch(r"[\s,:;()|]*", gap):
        return _days(group.group(0))
    # "Wednesday: Liping 12:30 pm": a spelled-out day may have a short label before the time.
    spelled_out = all(re.fullmatch(_WORD, tok.group(0)) for tok in _DAY_RE.finditer(group.group(0)))
    if spelled_out and len(gap) <= 30 and not re.search(r"\d", gap):
        return _days(group.group(0))
    return None


def _days_after(rest: str) -> list[int] | None:
    """ "9:30-10:50 AM, Tuesdays and Thursdays" """
    group = _GROUP_RE.match(rest.lstrip(" ,;(on"))
    return _days(group.group(0)) if group else None


def _to_24h(hour: int, minute: int, half: str | None) -> int:
    if half is None:  # no am/pm: 8-11 are mornings, 12 is noon, 1-7 are afternoons
        half = "a" if 8 <= hour <= 11 else "p" if hour <= 12 else None
    if half == "p" and hour < 12:
        hour += 12
    elif half == "a" and hour == 12:
        hour = 0
    return hour * 60 + minute


def _times(m: re.Match) -> tuple[str, str | None] | None:
    h1, m1, ap1, h2, m2, ap2 = m.groups()
    ap1, ap2 = (ap1 or "").lower() or None, (ap2 or "").lower() or None
    # A bare number is a time only with a colon, an am/pm, or as a range like "10-12".
    if not (m1 or ap1 or ap2 or (h2 and int(h1) <= 12 and int(h2) <= 12)):
        return None
    if int(h1) > 23 or (h2 and int(h2) > 23):
        return None
    end = _to_24h(int(h2), int(m2 or 0), ap2 or ap1) if h2 else None
    start = _to_24h(int(h1), int(m1 or 0), ap1 or ap2)
    if end is not None and start >= end and ap1 is None:  # "11-12:15pm" starts at 11 am
        start = _to_24h(int(h1), int(m1 or 0), "a")
    if end is not None and end <= start:
        end = None
    fmt = lambda minutes: f"{minutes // 60:02d}:{minutes % 60:02d}"  # noqa: E731
    return fmt(start), fmt(end) if end is not None else None


def _kind(text: str) -> tuple[str, str] | None:
    for pattern, kind, title in _KINDS:
        if pattern.search(text):
            return kind, title
    return None


def _line_meetings(line: str) -> list[tuple[list[int], str, str | None, str, str]]:
    """(days, start, end, quote, label text) for each weekly meeting on one line."""
    times = [(t, parsed) for t in _TIME_RE.finditer(line) if (parsed := _times(t))]
    found, prev_end = [], 0
    for k, (t, (start, end)) in enumerate(times):
        window = line[prev_end : t.start()]
        prev_end = t.end()
        rest = line[t.end() : times[k + 1][0].start() if k + 1 < len(times) else len(line)]
        days = _days_before(window)
        if days is None and k + 1 == len(times):
            days = _days_after(rest)
        if not days or _DATE_RE.search(window) or _ONE_OFF_RE.search(window):
            continue
        if re.match(r"\s*\(?\s*by appointment", rest, re.I):  # not a fixed time slot
            continue
        # "(ID: 806 ...); Shahariar , F 12-1 PM" -> "Shahariar , F 12-1 PM"
        quote = (window.rsplit(";", 1)[-1].lstrip(" ,)") + line[t.start() : t.end()]).strip()
        found.append((days, start, end, quote, window))
    return found


def find_meetings(text: str) -> list[Meeting]:
    meetings: list[Meeting] = []
    lines, page = text.splitlines(), 1
    last: tuple[int, str, str] | None = None  # (line index, type, title) of the previous meeting
    for i, line in enumerate(lines):
        if m := re.match(r"=== page (\d+) ===", line):
            page = int(m.group(1))
            continue
        found = _line_meetings(line)
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if not found and _ENDS_WITH_DAYS_RE.search(line) and nxt and not nxt.startswith("==="):
            found = _line_meetings(f"{line} {nxt}")  # "Lecture: Tuesday and Thursday" / "2:00-3:20 PM"
        for days, start, end, quote, label in found:
            if (kind := _kind(label) or _kind(line)) is not None:
                sure = True
            elif last and last[0] == i - 1:  # "Section 022 Wed. 6:00pm" under "Labs Section 021 ..."
                kind, sure = last[1:], True
            elif (kind := next((k for prev in reversed(lines[max(0, i - 3) : i]) if (k := _kind(prev))), None)):
                sure = True
            else:
                kind, sure = ("class", "Weekly meeting"), False
            kind_type, title = kind
            last = (i, kind_type, title)
            if kind_type == "office_hours":
                who = re.search(r"\b(TA|instructor|professor)\b", line, re.I)
                title = f"{'TA' if who and who.group(1) == 'TA' else 'Instructor'} office hours" if who else title
            elif section := _SECTION_RE.search(label):
                title = f"{title} Section {section.group(1)}"
            if any(m.days == days and m.start == start and m.type == kind_type for m in meetings):
                continue  # the same meeting repeated elsewhere in the syllabus
            meetings.append(Meeting(title, kind_type, days, start, end, page, quote, sure))
    return meetings


def guess_course(text: str) -> str:
    """ "CS 180", "MATH 009C" from the top of the syllabus, or "" if there is no course code."""
    m = _COURSE_RE.search("\n".join(text.splitlines()[:15]))
    return f"{m.group(1)} {m.group(2)}" if m else ""


def first_day(term_start: str, days: list[int]) -> date:
    start = date.fromisoformat(term_start)
    return next(start + timedelta(days=k) for k in range(7) if (start + timedelta(days=k)).weekday() in days)


def meeting_events(text: str, course: str, term_start: str, term_end: str) -> list[dict]:
    """Every weekly meeting as an event dict in the schema's shape, repeating until finals week."""
    course = course or guess_course(text)
    end = date.fromisoformat(term_end)
    finals = end - timedelta(days=end.weekday())  # same rule as holidays.finals_week_start
    last = finals - timedelta(days=1) if finals - date.fromisoformat(term_start) >= timedelta(weeks=4) else end
    until = last.strftime("%Y%m%d")
    return [
        {
            "course": course,
            "title": m.title,
            "type": m.type,
            "date": first_day(term_start, m.days).isoformat(),
            "start": m.start,
            "end": m.end,
            "recurrence": f"FREQ=WEEKLY;BYDAY={','.join(BYDAY[d] for d in m.days)};UNTIL={until}",
            "citation": f"p.{m.page}: '{m.quote}'",
            "confidence": "high" if m.sure else "low",
        }
        for m in find_meetings(text)
    ]


def _byday(rule: object) -> set[str]:
    m = re.search(r"BYDAY=([^;]*)", str(rule or ""), re.I)
    return {d.strip().upper()[-2:] for d in m.group(1).split(",")} if m else set()


def missing_meetings(raw_events: list, text: str, term_start: str, term_end: str, course: str = "") -> list[dict]:
    """Weekly meetings in the text that no recurring event covers (same start time and a shared
    day). Adding them in code means a model that skips the meeting line ("Class TTh 9:30-10:50am")
    still puts every lecture on the calendar."""
    covered = {
        (day, ev.get("start"))
        for ev in raw_events
        if isinstance(ev, dict) and ev.get("recurrence")
        for day in _byday(ev["recurrence"])
    }
    course = course or next((ev["course"] for ev in raw_events if isinstance(ev, dict) and ev.get("course")), "")
    return [
        ev
        for ev in meeting_events(text, course, term_start, term_end)
        if not any((day, ev["start"]) in covered for day in _byday(ev["recurrence"]))
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("text", help="extracted syllabus text (python -m sycal.extract)")
    parser.add_argument("--course", default="")
    parser.add_argument("--term-start", required=True)
    parser.add_argument("--term-end", required=True)
    args = parser.parse_args(argv)
    text = Path(args.text).read_text(encoding="utf-8")
    for ev in meeting_events(text, args.course, args.term_start, args.term_end):
        print(json.dumps(ev, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
