"""Estimated dates for graded work a syllabus counts but never dates ("5 in-class quizzes").

Owner: Guru. The prompt asks the agent to estimate these, but a small model often leaves them
out. For each counted kind the agent wrote no event for, the dates are spread evenly over the
teaching weeks here: quizzes and midterms at lecture time on lecture days, homework due Friday
at 23:59, never on a holiday or in finals week. "in Weeks 3, 5, 8, and 9" puts them in those
weeks. Every one is low confidence and cites the sentence that counts them, so it shows as
"estimated" until the student confirms the date.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from sycal.holidays import class_days, finals_week_start, holiday_dates
from sycal.meetings import guess_course
from sycal.validate import week_table

_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}  # fmt: skip
_COUNT = rf"\b(\d{{1,2}}|{'|'.join(_NUMBERS)})\s+(?:(?!and\b|or\b)[\w-]+\s+){{0,3}}?"
# (counted noun, event type, title, how the agent's own events for it are titled)
_KINDS = [
    (r"quiz(?:zes)?\b", "exam", "Quiz", re.compile(r"quiz", re.I)),
    (r"(?:homework|hw)(?:\s+assignments?|s)?\b|problem sets?\b", "assignment", "Homework", re.compile(r"homework|\bhw|problem set", re.I)),
    (r"midterms?(?:\s+exams?)?\b", "exam", "Midterm", re.compile(r"midterm", re.I)),
]  # fmt: skip
# Only a sentence that states the count: "There will be 5 quizzes", not "if out of 16 quizzes".
_STATES_COUNT_RE = re.compile(r"\bthere (?:will be|are|is)\b|\btotal of\b|\bwe will have\b", re.I)
_WEEKS_RE = re.compile(r"\bweeks?\s+(\d{1,2}(?:\s*(?:,|and|&)\s*(?:and\s+)?\d{1,2})*)", re.I)


def _sentences(text: str):
    """(page, sentence), with wrapped lines joined so a sentence is whole."""
    parts = re.split(r"^=== page (\d+) ===$", text, flags=re.M)
    for page, body in zip(parts[1::2], parts[2::2]):
        # a sentence ends at . ! ? even when a closing quote or bracket follows ('aka "free passes." There')
        for sentence in re.split(r"(?<=[.!?])\s+|(?<=[.!?][\"”’)])\s+", " ".join(body.split())):
            yield int(page), sentence


def counted_work(text: str) -> list[tuple[int, str, int, int]]:
    """(page, sentence, how many, index into _KINDS) for each kind of work the syllabus counts."""
    found, seen = [], set()
    for page, sentence in _sentences(text):
        if not _STATES_COUNT_RE.search(sentence):
            continue
        for k, (noun, *_rest) in enumerate(_KINDS):
            m = re.search(_COUNT + rf"(?:{noun})", sentence, re.I)
            # "one quiz per week" is a recurring thing, not a count to spread out.
            if not m or k in seen or re.match(r"\s*(?:per|each|every|a) week", sentence[m.end() :], re.I):
                continue
            n = int(m.group(1)) if m.group(1).isdigit() else _NUMBERS[m.group(1).lower()]
            if 1 <= n <= 20:
                seen.add(k)
                found.append((page, sentence, n, k))
    return found


def estimated_events(raw_events: list, text: str, term_start: str, term_end: str, course: str = "") -> list[dict]:
    """Low-confidence events for counted work the agent wrote nothing for."""
    events = [ev for ev in raw_events if isinstance(ev, dict)]
    start, end = date.fromisoformat(term_start), date.fromisoformat(term_end)
    stop = finals_week_start(term_start, term_end) or end + timedelta(days=1)
    holidays = holiday_dates(events)
    weeks = week_table(term_start, term_end)
    meetings = [ev for ev in events if ev.get("type") == "class" and ev.get("recurrence")]
    lecture = next((ev for ev in meetings if re.search(r"lecture|class", str(ev.get("title")), re.I)), None)
    lecture = lecture or (meetings[0] if meetings else None)
    lecture_days = class_days([lecture]) if lecture else set()
    course = course or next((ev["course"] for ev in events if ev.get("course")), "") or guess_course(text)

    def teaching_days(weekdays: set[int], first: date) -> list[date]:
        days, d = [], max(first, start)
        while d < stop and d <= end:
            if d.weekday() in weekdays and d not in holidays:
                days.append(d)
            d += timedelta(days=1)
        return days

    added = []
    for page, sentence, n, k in counted_work(text):
        _noun, kind, title, agent_title = _KINDS[k]
        if any(agent_title.search(str(ev.get("title", ""))) for ev in events):
            continue  # the agent already wrote these; its dates beat an even spread
        if kind == "assignment":
            weekdays, (at, until) = {4}, ("23:59", None)
        else:
            weekdays = lecture_days or {0, 1, 2, 3, 4}
            at, until = (lecture.get("start"), lecture.get("end")) if lecture else (None, None)
        listed = _WEEKS_RE.search(sentence)
        listed_weeks = [int(w) for w in re.findall(r"\d+", listed.group(1))] if listed else []
        if len(listed_weeks) == n and all(1 <= w <= len(weeks) for w in listed_weeks):
            all_days = teaching_days(weekdays, start)
            picks = [next((d for d in all_days if weeks[w - 1][1] <= d < weeks[w - 1][1] + timedelta(days=7)), None) for w in listed_weeks]
        else:
            # Skip week 1 (syllabus week); spread the rest evenly from week 2 up to finals week.
            days = teaching_days(weekdays, weeks[1][1] if len(weeks) > 1 else start)
            picks = sorted({days[int((j + 0.5) * len(days) / n)] for j in range(n)}) if days else []
        for j, day in enumerate((d for d in picks if d), 1):
            added.append({
                "course": course, "title": f"{title} {j}" if n > 1 else title, "type": kind,
                "date": day.isoformat(), "start": at, "end": until if at else None, "recurrence": None,
                "citation": f"p.{page}: '{sentence}'", "confidence": "low",
            })  # fmt: skip
    return added
