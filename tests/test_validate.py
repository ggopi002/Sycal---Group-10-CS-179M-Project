import json
from dataclasses import asdict

from sycal.validate import (
    format_week_table,
    is_grounded,
    main,
    named_weekdays,
    repair_against_text,
    repair_event,
    states_date,
    validate_events,
)


def _raw(sample_file):
    return [asdict(e) for e in sample_file.events]


def _validate(events, sample_file, text=None):
    return validate_events(events, sample_file.term_start, sample_file.term_end, text)


def test_sample_label_is_valid(sample_file, sample_text):
    assert _validate(_raw(sample_file), sample_file, sample_text) == []


def test_wrong_weekday(sample_file):
    events = _raw(sample_file)
    events[4]["date"] = "2026-10-27"  # Midterm citation says Thursday; 10/27 is a Tuesday
    assert any("citation says Thursday" in e for e in _validate(events, sample_file))


def test_outside_term(sample_file):
    events = _raw(sample_file)
    events[2]["date"] = "2027-01-15"
    assert any("outside the term" in e for e in _validate(events, sample_file))


def test_duplicate(sample_file):
    events = _raw(sample_file)
    events.append(dict(events[3]))
    assert any("duplicate of event 4" in e for e in _validate(events, sample_file))


def test_recurrence_without_until(sample_file):
    events = _raw(sample_file)
    events[0]["recurrence"] = "FREQ=WEEKLY;BYDAY=TU,TH"
    assert any("repeat forever" in e for e in _validate(events, sample_file))


def test_citation_grounding(sample_text):
    assert is_grounded("p.1: 'HW1 due Fri 10/2 at 11:59 PM'", sample_text)
    assert not is_grounded("p.1: 'HW1 due Monday 10/5'", sample_text)


def test_week_table(sample_file):
    table = format_week_table(sample_file.term_start, sample_file.term_end)
    assert "Week  6: Mon 2026-10-26" in table


def test_recurring_byday_must_match_citation(sample_file):
    events = _raw(sample_file)
    events[0]["recurrence"] = "FREQ=WEEKLY;BYDAY=MO,TH;UNTIL=20261203"  # citation says Tuesdays and Thursdays
    assert any("use BYDAY=TU,TH" in e for e in _validate(events, sample_file))


def test_compact_weekday_codes():
    assert named_weekdays("p.1: 'Class TTh 9:30-10:50am'") == {1, 3}
    assert named_weekdays("p.1: 'Schedule: MWF 8:00 a.m.'") == {0, 2, 4}
    assert named_weekdays("p.1: 'MATH 009C-001'") == set()


def test_repair_fixes_only_unambiguous_slips():
    ev = {"type": "lab", "start": "2:00pm", "end": "9", "recurrence": "FREQ=WEEKLY;BYDAY=WED;UNTIL=20261204", "confidence": "high"}
    assert len(repair_event(ev)) == 3
    assert ev == {"type": "class", "start": "14:00", "end": "9", "recurrence": "FREQ=WEEKLY;BYDAY=WE;UNTIL=20261204", "confidence": "high"}


def test_wrong_first_date_gets_corrected_date(sample_file):
    events = _raw(sample_file)
    events[1]["date"] = "2026-09-28"  # Office hours are Wednesdays; 9/28 is a Monday
    assert any("set date to" in e and "2026-09-30" in e for e in _validate(events, sample_file))


def test_near_miss_citation_snaps_to_real_line(sample_file, sample_text):
    ev = _raw(sample_file)[2] | {"citation": "p.1: 'HW1 is due Fri 10/2 at 11:59 PM'"}
    assert repair_against_text(ev, sample_text)
    assert is_grounded(ev["citation"], sample_text)


def test_citation_with_different_numbers_is_not_snapped(sample_file, sample_text):
    # A made-up HW2 must not be grounded on the real HW1 line.
    ev = _raw(sample_file)[2] | {"title": "HW2 due", "date": "2026-10-09", "citation": "p.1: 'HW2 due Fri 10/9 at 11:59 PM'"}
    assert repair_against_text(ev, sample_text) == []


def test_weekly_class_without_recurrence_is_flagged(sample_file):
    events = _raw(sample_file)
    events[0]["recurrence"] = None  # "Tuesdays and Thursdays" as a single lecture
    assert any("add recurrence FREQ=WEEKLY;BYDAY=TU,TH" in e for e in _validate(events, sample_file))


def test_short_quote_from_long_line_snaps(sample_file, sample_text):
    ev = _raw(sample_file)[0] | {"citation": "p.1: 'Tuesdays and Thursdays 2:00-3:20 PM'"}  # line says "2:00–3:20 PM, Bourns A265."
    repair_against_text(ev, sample_text)
    assert is_grounded(ev["citation"], sample_text)


def test_glued_quotes_from_one_line_snap_to_it():
    text = "=== page 1 ===\nHolidays Nov. 11 (Veteran’s Day), Nov. 26 (Thanksgiving)\n"
    ev = {"course": "CS 180", "title": "Thanksgiving", "type": "other", "date": "2026-11-26",
          "start": None, "end": None, "recurrence": None, "confidence": "high",
          "citation": "p.1: 'Holidays Nov. 11 (Veteran’s Day)', p.1: 'Holidays Nov. 26 (Thanksgiving)'"}
    repair_against_text(ev, text)
    assert ev["citation"] == "p.1: 'Holidays Nov. 11 (Veteran’s Day), Nov. 26 (Thanksgiving)'"


def test_byday_follows_grounded_citation(sample_file, sample_text):
    ev = _raw(sample_file)[0] | {"recurrence": "FREQ=WEEKLY;BYDAY=MO,TH;UNTIL=20261203"}
    assert any("MO,TH -> TU,TH" in f for f in repair_against_text(ev, sample_text))
    assert ev["recurrence"] == "FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261203"


def test_fix_flags_ungrounded_citation_instead_of_failing(tmp_path, sample_file, capsys):
    events = _raw(sample_file)
    events[0]["citation"] = "p.1: 'nothing like this is in the syllabus'"
    path, text = tmp_path / "events.json", tmp_path / "text.txt"
    path.write_text(json.dumps(events), encoding="utf-8")
    text.write_text("=== page 1 ===\n" + "\n".join(e["citation"] for e in events[1:]), encoding="utf-8")
    args = [str(path), "--term-start", sample_file.term_start, "--term-end", sample_file.term_end, "--text", str(text)]

    assert main(args) == 1  # without --fix a missing quote is still an error
    assert main(args + ["--fix"]) == 0
    assert "needs review, event 1" in capsys.readouterr().out
    assert json.loads(path.read_text(encoding="utf-8"))[0]["confidence"] == "low"


def test_missing_confidence_defaults_to_low():
    ev = {"course": "CS 1", "title": "x", "type": "other", "date": "2026-10-01", "citation": "p.1: 'x'"}
    assert repair_event(ev) == ["confidence missing -> low"]
    assert ev["confidence"] == "low"


def test_states_date():
    assert states_date("p.1: 'HW1 due Fri 10/2 at 11:59 PM'")
    assert states_date("p.1: 'Holidays Nov. 11 (Veteran's Day)'")
    assert states_date("p.1: 'Midterm in class, Week 6'")
    assert not states_date("p.2: 'There will be 2 homework assignments and 5 in-class quizzes.'")


def test_undated_event_must_be_low_confidence(sample_file):
    events = _raw(sample_file)
    events[2]["citation"] = "p.2: 'There will be 2 homework assignments and 5 in-class quizzes.'"
    assert any("citation gives no date" in e for e in _validate(events, sample_file))
    events[2]["confidence"] = "low"  # an estimate the student confirms later is allowed
    assert not any("citation gives no date" in e for e in _validate(events, sample_file))


def test_fix_marks_estimated_dates_low(tmp_path, sample_file, capsys):
    events = _raw(sample_file)
    events[2]["citation"] = "p.1: 'There will be 2 homework assignments.'"
    path = tmp_path / "events.json"
    path.write_text(json.dumps(events), encoding="utf-8")

    assert main([str(path), "--fix"] + ["--term-start", sample_file.term_start, "--term-end", sample_file.term_end]) == 0
    assert "the date is an estimate" in capsys.readouterr().out
    assert json.loads(path.read_text(encoding="utf-8"))[2]["confidence"] == "low"
