from dataclasses import asdict

import pytest

from sycal.meetings import find_meetings, guess_course, meeting_events, missing_meetings
from sycal.validate import validate_events


def _one(line: str):
    meetings = find_meetings(f"=== page 1 ===\n{line}\n")
    assert len(meetings) == 1, meetings
    m = meetings[0]
    return m.title, m.days, m.start, m.end


# One line from each real syllabus format we have, plus formats we expect to see.
@pytest.mark.parametrize(
    "line, expected",
    [
        ("Class TTh 9:30-10:50am Undergrad Teaching & Learning Facility (UTLF) 0203", ("Lecture", [1, 3], "09:30", "10:50")),
        ("Schedule: MWF 8:00 a.m.-8:50 a.m.", ("Lecture", [0, 2, 4], "08:00", "08:50")),
        ("Lectures : T/Th 2PM in SSC 329", ("Lecture", [1, 3], "14:00", None)),
        ("Class time and Place: Tuesday and Thursday 02:00 PM - 03:20 PM Humanities", ("Lecture", [1, 3], "14:00", "15:20")),
        ("Lectures: Tuesdays and Thursdays, 2:00–3:20 PM, Bourns A265.", ("Lecture", [1, 3], "14:00", "15:20")),
        ("Lecture: 9:30-10:50 AM, Tuesdays & Thursdays", ("Lecture", [1, 3], "09:30", "10:50")),
        ("Lecture meets TR 11-12:15pm in MSE 104", ("Lecture", [1, 3], "11:00", "12:15")),
        ("Lab: Mon-Fri 9am", ("Lab", [0, 1, 2, 3, 4], "09:00", None)),
        ("Labs Section 021 Wed. 2:00pm – 3:50pm UTLF 0403", ("Lab Section 021", [2], "14:00", "15:50")),
        ("Office hour: Tuesday and Thursday 3:30pm-4:20pm at Skye Hall 249 or by appointment.", ("Office hours", [1, 3], "15:30", "16:20")),
        ("TA Office Hours : Mohammad Jaminur Islam, Th 12-1 PM, WCH 136.", ("TA office hours", [3], "12:00", "13:00")),
    ],
)
def test_meeting_line_formats(line, expected):
    assert _one(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "Final: The final exam will be given on Thursday, March 20 8:00 a.m.-11:00 a.m. in the lecture room",
        "| 2 | Dates are hard | HW1 due Fri 10/2 at 11:59 PM |",
        "Final Exam: Wednesday, December 9, 8:00–11:00 AM, location TBA.",
        "Homework will be assigned every Friday before midnight and due next Friday at midnight.",
        "| Week | 1 (1.6- 1.12) | 2 (1.13- 1.19) | 8 (2.24 -3.2) |",
        "| F | 8.1 | 8.2 | 8.3 | exam1 | 8.5 |",
        "F: < 50",
        "Instructor: Qi S. Zhang, e-mail: qizhang@math.ucr.edu, Tel. 827-5014.",
        "Discussions (mandatory attendance) : Wed and Thu (see classes.ucr.edu )",
        "MTThF 4PM (by appointment), otherwise by appointment",
    ],
)
def test_not_weekly_meetings(line):
    assert find_meetings(f"=== page 1 ===\n{line}\n") == []


def test_heading_and_previous_line_give_the_kind():
    text = (
        "=== page 1 ===\nDISCUSSION INFORMATION\n"
        "Section 002: Ethan Nowaski Tuesday 10:00 AM-10:50 AM CHASS 2134\n"
        "Section 003: Ethan Nowaski Tuesday 11:00 AM-11:50 AM CHASS 2134\n"
        "=== page 2 ===\nOFFICE HOURS AND TUTORING\nWednesday: Liping 12:30 pm-2:30 pm Skye Hall 262A\n"
    )
    assert [(m.title, m.type, m.page) for m in find_meetings(text)] == [
        ("Discussion Section 002", "class", 1),
        ("Discussion Section 003", "class", 1),
        ("Office hours", "office_hours", 2),
    ]


def test_meeting_split_over_two_lines():
    text = "=== page 1 ===\nLecture: Tuesday and Thursday\n2:00-3:20 PM in Bourns A265\n"
    (m,) = find_meetings(text)
    assert (m.days, m.start, m.end, m.quote) == ([1, 3], "14:00", "15:20", "Lecture: Tuesday and Thursday 2:00-3:20 PM")


def test_unlabeled_meeting_is_low_confidence():
    (ev,) = meeting_events("=== page 1 ===\nTTh 9:30-10:50am\n", "CS 1", "2026-09-24", "2026-12-11")
    assert ev["title"] == "Weekly meeting" and ev["confidence"] == "low"


def test_guess_course():
    assert guess_course("=== page 1 ===\nCS150 Syllabus 1\n") == "CS 150"
    assert guess_course("=== page 1 ===\npage 1 of 5\nSyllabus\nMATH 009C-001 | First-Year Calculus\n") == "MATH 009C"


def test_meeting_events_pass_the_validator(sample_text):
    events = meeting_events(sample_text, "CS 999", "2026-09-24", "2026-12-11")
    assert [(e["title"], e["date"], e["recurrence"]) for e in events] == [
        ("Lecture", "2026-09-24", "FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261206"),  # ends before finals week
        ("Office hours", "2026-09-30", "FREQ=WEEKLY;BYDAY=WE;UNTIL=20261206"),
    ]
    assert validate_events(events, "2026-09-24", "2026-12-11", sample_text) == []


def test_missing_meetings_skips_ones_the_agent_wrote(sample_file, sample_text):
    events = [asdict(e) for e in sample_file.events]
    assert missing_meetings(events, sample_text, sample_file.term_start, sample_file.term_end) == []
    (added,) = missing_meetings(events[1:], sample_text, sample_file.term_start, sample_file.term_end)
    assert (added["course"], added["title"]) == ("CS 999", "Lecture")
