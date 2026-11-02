"""Event schema shared by the agent, the validator, the .ics writer, and the scorer.

SHARED FILE: changes need a PR approved by all three teammates (see TEAM.md).

Event files on disk use this wrapper:

    {
      "syllabus": "sample.html",
      "term_start": "2026-09-24",
      "term_end": "2026-12-11",
      "events": [ {event}, ... ]
    }

A bare JSON list of events is also accepted (the agent writes that form);
the term metadata is then supplied by the caller.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from icalendar import vRecur

EVENT_TYPES = ("exam", "assignment", "class", "office_hours", "other")
CONFIDENCE_LEVELS = ("high", "low")
FIELDS = ("course", "title", "type", "date", "start", "end", "recurrence", "citation", "confidence")

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class SchemaError(ValueError):
    pass


@dataclass
class Event:
    course: str
    title: str
    type: str
    date: str
    start: str | None = None
    end: str | None = None
    recurrence: str | None = None
    """RRULE value without the "RRULE:" prefix, e.g. "FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261204".
    `date` is the first occurrence."""
    citation: str = ""
    """Page and quoted source text, e.g. "p.3: '10/29 — Midterm (in class)'"."""
    confidence: str = "high"

    @property
    def day(self) -> date:
        return date.fromisoformat(self.date)


@dataclass
class EventFile:
    syllabus: str
    term_start: str
    term_end: str
    events: list[Event] = field(default_factory=list)


def check_event(d: object) -> list[str]:
    """Return every shape problem with one raw event dict (empty list if it is valid)."""
    if not isinstance(d, dict):
        return [f"expected a JSON object, got {type(d).__name__}"]
    problems = []
    for key in ("course", "title", "type", "date", "citation", "confidence"):
        if key not in d:
            problems.append(f"missing field '{key}'")
    for key in d:
        if key not in FIELDS:
            problems.append(f"unknown field '{key}'")
    if "type" in d and d["type"] not in EVENT_TYPES:
        problems.append(f"type '{d['type']}' must be one of {', '.join(EVENT_TYPES)}")
    if "confidence" in d and d["confidence"] not in CONFIDENCE_LEVELS:
        problems.append(f"confidence '{d['confidence']}' must be 'high' or 'low'")
    if "date" in d:
        try:
            date.fromisoformat(str(d["date"]))
        except ValueError:
            problems.append(f"date '{d['date']}' is not YYYY-MM-DD")
    for key in ("start", "end"):
        value = d.get(key)
        if value is not None and not _TIME_RE.match(str(value)):
            problems.append(f"{key} '{value}' is not 24-hour HH:MM or null")
    if d.get("end") is not None and d.get("start") is None:
        problems.append("end is set but start is null")
    if d.get("recurrence") is not None:
        try:
            # from_ical returns {} for text with no KEY=VALUE parts, so require FREQ explicitly.
            if "FREQ" not in vRecur.from_ical(str(d["recurrence"]).removeprefix("RRULE:")):
                raise ValueError
        except Exception:
            problems.append(f"recurrence '{d['recurrence']}' is not a valid RRULE (e.g. FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261204)")
    return problems


def event_from_dict(d: dict) -> Event:
    problems = check_event(d)
    if problems:
        raise SchemaError("; ".join(problems))
    return Event(**{k: d.get(k) for k in FIELDS if k in d})


def load_event_file(
    path: str | Path,
    *,
    syllabus: str | None = None,
    term_start: str | None = None,
    term_end: str | None = None,
) -> EventFile:
    """Load a wrapped or bare-list event file. Keyword arguments fill in (or override) term metadata."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        raw = {"events": raw}
    if not isinstance(raw, dict) or not isinstance(raw.get("events"), list):
        raise SchemaError("expected a JSON list of events or an object with an 'events' list")
    meta = {
        "syllabus": syllabus or raw.get("syllabus") or "",
        "term_start": term_start or raw.get("term_start") or "",
        "term_end": term_end or raw.get("term_end") or "",
    }
    return EventFile(**meta, events=[event_from_dict(e) for e in raw["events"]])


def dump_event_file(event_file: EventFile, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(asdict(event_file), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
