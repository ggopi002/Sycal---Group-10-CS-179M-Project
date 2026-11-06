from dataclasses import asdict

from sycal.validate import format_week_table, is_grounded, validate_events


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
