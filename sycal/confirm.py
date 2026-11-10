"""Put dates the student confirmed into a finished run, then rebuild out.ics and review.md.

The agent may estimate a date the syllabus never gives ("5 in-class quizzes"); those events are
low confidence and tagged [VERIFY]. Once the student knows the real date, this records it and
the event loses the tag. Event numbers are the ones review.md lists (1-based, as in events.json).

Usage:
    python -m sycal.confirm outputs/<run>/<model>-<mode>/<syllabus> --set 7=2026-10-15 --set 8=2026-11-12
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

from sycal.schema import EventFile, load_event_file
from sycal.to_ics import write_outputs

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def confirm_dates(run_dir: Path, dates: dict[int, str]) -> EventFile:
    """Set each numbered event's date and mark it high confidence. Checks every date before
    changing anything, so a typo leaves the run as it was."""
    event_file = load_event_file(run_dir / "events.json")
    term_start, term_end = date.fromisoformat(event_file.term_start), date.fromisoformat(event_file.term_end)
    for n, day in dates.items():
        if not 1 <= n <= len(event_file.events):
            raise ValueError(f"there is no event {n}; events.json has {len(event_file.events)}")
        if not _DATE_RE.match(day):
            raise ValueError(f"event {n}: '{day}' is not YYYY-MM-DD")
        if not term_start <= date.fromisoformat(day) <= term_end:
            raise ValueError(f"event {n}: {day} is outside the term ({event_file.term_start} to {event_file.term_end})")
    for n, day in dates.items():
        ev = event_file.events[n - 1]
        ev.date, ev.confidence = day, "high"
    write_outputs(event_file, run_dir)
    return event_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", help="folder with events.json (the one review.md is in)")
    parser.add_argument("--set", action="append", default=[], metavar="N=YYYY-MM-DD", help="(repeatable)")
    args = parser.parse_args(argv)

    try:
        dates = {int(n): day.strip() for n, day in (s.split("=", 1) for s in args.set)}
    except ValueError:
        print("FAIL: each --set must look like 7=2026-10-15")
        return 2
    try:
        event_file = confirm_dates(Path(args.run_dir), dates)
    except FileNotFoundError:
        print(f"FAIL: {args.run_dir}/events.json does not exist")
        return 2
    except ValueError as e:
        print(f"FAIL: {e}")
        return 1
    n_low = sum(ev.confidence == "low" for ev in event_file.events)
    print(f"confirmed {len(dates)} date(s); {n_low} event(s) still need review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
