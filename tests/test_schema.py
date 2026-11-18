from dataclasses import asdict

import pytest

from sycal.schema import SchemaError, check_event, dump_event_file, event_from_dict, load_event_file


def test_round_trip(tmp_path, sample_file):
    dump_event_file(sample_file, tmp_path / "events.json")
    assert load_event_file(tmp_path / "events.json") == sample_file


def test_bare_list_takes_term_from_caller(tmp_path):
    (tmp_path / "bare.json").write_text("[]")
    loaded = load_event_file(tmp_path / "bare.json", syllabus="s.pdf", term_start="2026-09-24", term_end="2026-12-11")
    assert (loaded.syllabus, loaded.term_start, loaded.events) == ("s.pdf", "2026-09-24", [])


@pytest.mark.parametrize(
    "change, problem",
    [
        ({"type": "quiz"}, "type 'quiz'"),
        ({"date": "10/29/2026"}, "not YYYY-MM-DD"),
        ({"start": "2pm"}, "not 24-hour"),
        ({"recurrence": "EVERY TUESDAY"}, "not a valid RRULE"),
        ({"location": "Bourns"}, "unknown field"),
    ],
)
def test_bad_fields_are_reported(sample_file, change, problem):
    raw = asdict(sample_file.events[0]) | change
    assert any(problem in p for p in check_event(raw))
    with pytest.raises(SchemaError):
        event_from_dict(raw)
