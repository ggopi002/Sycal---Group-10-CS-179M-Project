from sycal.estimate import counted_work, estimated_events
from sycal.holidays import missing_holidays
from sycal.meetings import meeting_events
from sycal.to_ics import is_estimate
from sycal.schema import event_from_dict
from sycal.validate import validate_events

TERM = ("2026-09-24", "2026-12-11")
CS180 = (
    "=== page 1 ===\nCS 180 Introduction to Software Engineering\n"
    "Class TTh 9:30-10:50am Undergrad Teaching & Learning Facility (UTLF) 0203\n"
    "Holidays Nov. 11 (Veteran’s Day), Nov. 26 (Thanksgiving)\n"
    "Homework Assignments and Quizzes\n"
    "There will be 2 homework assignments and 5 in-class quizzes. There will also be an\n"
    "optional cumulative final exam (similar in length to a regular quiz).\n"
)


def test_counted_work():
    assert [(n, k) for _, _, n, k in counted_work(CS180)] == [(5, 0), (2, 1)]
    assert counted_work("=== page 1 ===\nUsually there will be one quiz per week, in discussion.\n") == []
    assert counted_work("=== page 1 ===\nExample: if out of 16 quizzes, you missed 2 of them.\n") == []
    nine_c = "=== page 2 ===\nQuizzes: There will be four 20-minute weekly paper quizzes, in Weeks 3, 5, 8, and 9.\n"
    assert [(p, n) for p, _, n, _ in counted_work(nine_c)] == [(2, 4)]


def test_cs180_quizzes_and_homework_are_estimated():
    events = meeting_events(CS180, "", *TERM)
    events += missing_holidays(events, CS180, *TERM)
    added = estimated_events(events, CS180, *TERM)
    quizzes = [e for e in added if e["title"].startswith("Quiz")]
    homework = [e for e in added if e["title"].startswith("Homework")]
    assert len(quizzes) == 5 and len(homework) == 2
    assert all(e["start"] == "09:30" and e["date"] not in ("2026-11-11", "2026-11-26") for e in quizzes)
    assert all(e["date"] < "2026-12-07" for e in added)  # nothing in finals week
    assert all(is_estimate(event_from_dict(e)) for e in added)  # shown as "estimated" until confirmed
    assert validate_events(events + added, *TERM, CS180) == []


def test_listed_weeks_are_used():
    text = "=== page 1 ===\nSchedule: MWF 8:00 a.m.-8:50 a.m.\nThere will be four quizzes, in Weeks 3, 5, 8, and 9.\n"
    added = estimated_events(meeting_events(text, "MATH 9C", "2025-01-06", "2025-03-21"), text, "2025-01-06", "2025-03-21")
    assert [e["date"] for e in added] == ["2025-01-20", "2025-02-03", "2025-02-24", "2025-03-03"]


def test_nothing_added_when_the_agent_wrote_them():
    events = meeting_events(CS180, "", *TERM) + [{"title": "Quiz 1"}, {"title": "HW 2 due"}]
    assert estimated_events(events, CS180, *TERM) == []


def test_estimated_quizzes_move_to_lecture_days_and_final_to_finals_week():
    from sycal.validate import repair_estimated_exams

    events = meeting_events(CS180, "", *TERM)
    cite = "p.1: 'There will be 2 homework assignments and 5 in-class quizzes.'"
    quiz = {"course": "CS 180", "title": "Quiz 1", "type": "exam", "date": "2026-10-05", "start": None, "end": None,
            "recurrence": None, "citation": cite, "confidence": "low"}  # fmt: skip
    final = quiz | {"title": "Final Exam", "date": "2026-12-04", "citation": "p.1: 'optional cumulative final exam'"}
    events += [quiz, final]

    assert len(repair_estimated_exams(events, *TERM)) == 2
    assert (quiz["date"], quiz["start"], quiz["end"]) == ("2026-10-06", "09:30", "10:50")  # Mon -> Tue lecture
    assert final["date"] == "2026-12-08"  # first Tue/Thu of finals week
