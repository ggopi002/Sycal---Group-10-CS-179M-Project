from dataclasses import asdict
from datetime import date

from icalendar import Calendar

from sycal.holidays import finals_week_start, gives_date, holiday_dates, missing_holidays, skipped_holidays
from sycal.to_ics import to_calendar
from sycal.validate import repair_finals, repair_holidays, validate_events

QUIZ = {
    "course": "CS 999", "title": "Quiz 4", "type": "exam", "date": "2026-11-26", "start": "14:00", "end": "14:30",
    "recurrence": None, "citation": "p.1: 'There will be 5 in-class quizzes.'", "confidence": "low",
}  # fmt: skip


def _raw(sample_file):
    return [asdict(e) for e in sample_file.events]


def test_holiday_dates(sample_file):
    assert holiday_dates(sample_file.events) == {date(2026, 11, 26): "No class (Thanksgiving)"}
    cs180 = {"type": "other", "title": "Veteran’s Day Holiday", "date": "2026-11-11", "start": None,
             "citation": "p.1: 'Holidays Nov. 11 (Veteran’s Day), Nov. 26 (Thanksgiving)'"}  # fmt: skip
    assert holiday_dates([cs180]) == {date(2026, 11, 11): "Veteran’s Day Holiday"}
    # an all-day "other" event that isn't a day off (e.g. a drop deadline) is not a holiday
    assert holiday_dates([cs180 | {"title": "Last day to drop", "citation": "p.1: 'Last day to drop: 10/9'"}]) == {}


def test_weekly_class_skips_holidays_in_the_ics(sample_file):
    lecture, office_hours = to_calendar(sample_file).walk("VEVENT")[:2]
    assert "20261126" in lecture["EXDATE"].to_ical().decode()  # Thanksgiving is a Thursday
    assert "EXDATE" not in office_hours  # Wednesdays: no holiday to skip
    Calendar.from_ical(to_calendar(sample_file).to_ical())  # still a valid calendar
    assert skipped_holidays(sample_file.events[0], holiday_dates(sample_file.events)) == [date(2026, 11, 26)]


def test_estimated_date_moves_off_a_holiday(sample_file):
    events = _raw(sample_file) + [dict(QUIZ)]
    errors = validate_events(events, sample_file.term_start, sample_file.term_end)
    assert any("no-class day (No class (Thanksgiving))" in e and "2026-12-01" in e for e in errors)

    assert len(repair_holidays(events)) == 1
    assert events[-1]["date"] == "2026-12-01"  # next Tue/Thu lecture after Thanksgiving
    assert validate_events(events, sample_file.term_start, sample_file.term_end) == []


def test_syllabus_date_on_a_holiday_is_kept_but_flagged(sample_file):
    stated = QUIZ | {"citation": "p.1: 'Quiz 4 Thursday 11/26'", "confidence": "high"}
    events = _raw(sample_file) + [stated]
    assert any("no-class day" in e for e in validate_events(events, sample_file.term_start, sample_file.term_end))

    assert "needs review" in repair_holidays(events)[0]
    assert (events[-1]["date"], events[-1]["confidence"]) == ("2026-11-26", "low")


def test_gives_date():
    day = date(2026, 11, 11)
    assert gives_date("p.2: 'Quiz 3 - Wed 11/11 in class'", day)
    assert gives_date("p.1: 'Holidays Nov. 11 (Veteran’s Day)'", day)
    assert gives_date("p.1: 'Midterm in class, Week 8'", day)
    assert not gives_date("p.1: 'Quiz 4 - TTh 9:30-10:50'", day)


CS180 = (
    "=== page 1 ===\nCS 180 Introduction to Software Engineering\n"
    "Class TTh 9:30-10:50am Undergrad Teaching & Learning Facility (UTLF) 0203\n"
    "Holidays Nov. 11 (Veteran’s Day), Nov. 26 (Thanksgiving)\n"
    "There will be 2 homework assignments and 5 in-class quizzes. There will also be an\n"
    "optional cumulative final exam.\n"
)


def test_holidays_are_read_from_the_syllabus_text():
    events = missing_holidays([], CS180, "2026-09-24", "2026-12-11")
    assert [(e["course"], e["title"], e["date"]) for e in events] == [
        ("CS 180", "No class (Veteran’s Day)", "2026-11-11"),
        ("CS 180", "No class (Thanksgiving)", "2026-11-26"),
    ]
    assert validate_events(events, "2026-09-24", "2026-12-11", CS180) == []
    assert missing_holidays(events, CS180, "2026-09-24", "2026-12-11") == []  # already there


def test_finals_week_ends_classes_and_moves_estimates(sample_file):
    assert finals_week_start(sample_file.term_start, sample_file.term_end) == date(2026, 12, 7)
    events = _raw(sample_file)
    events[0]["recurrence"] = "FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261211"
    events.append(QUIZ | {"date": "2026-12-08"})  # estimated, in finals week

    fixes = repair_finals(events, sample_file.term_start, sample_file.term_end)
    assert len(fixes) == 2
    assert events[0]["recurrence"] == "FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261206"
    assert events[-1]["date"] == "2026-12-03"  # last Tue/Thu lecture before finals week
    assert events[-2]["date"] == "2026-12-09"  # the Final Exam stays in finals week


def test_no_class_cells_in_a_schedule_grid():
    text = (
        "=== page 3 ===\nLECTURE SCHEDULE AND IMPORTANT DATES\n"
        "| Week | 1 (1.6- 1.12) | 2 (1.13- 1.19) | 3 (1.20- 1.26) | 7 (2.17- 2.23) |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| M | Intro | 8.1 | N/A | N/A |\n"
        "| W | 8.1 | 8.2 | 8.2 | 8.7 |\n"
    )
    events = missing_holidays([], text, "2025-01-06", "2025-03-21", "MATH 009C")
    assert [e["date"] for e in events] == ["2025-01-20", "2025-02-17"]  # MLK Day, Presidents' Day
    assert validate_events(events, "2025-01-06", "2025-03-21", text) == []
