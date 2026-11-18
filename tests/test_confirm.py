import json

import pytest

from sycal.confirm import confirm_dates, main
from sycal.to_ics import write_outputs


@pytest.fixture
def run_dir(tmp_path, sample_file):
    ev = sample_file.events[2]
    ev.citation, ev.confidence = "p.2: 'There will be 2 homework assignments.'", "low"
    write_outputs(sample_file, tmp_path)
    return tmp_path


def test_confirmed_date_replaces_the_estimate(run_dir):
    confirm_dates(run_dir, {3: "2026-10-09"})
    ev = json.loads((run_dir / "events.json").read_text(encoding="utf-8"))["events"][2]
    assert (ev["date"], ev["confidence"]) == ("2026-10-09", "high")
    assert "[VERIFY]" not in (run_dir / "out.ics").read_text(encoding="utf-8")
    assert "No low-confidence events" in (run_dir / "review.md").read_text(encoding="utf-8")


def test_bad_date_changes_nothing(run_dir, capsys):
    before = (run_dir / "events.json").read_text(encoding="utf-8")
    assert main([str(run_dir), "--set", "3=2026-10-09", "--set", "4=2027-01-05"]) == 1
    assert "outside the term" in capsys.readouterr().out
    assert (run_dir / "events.json").read_text(encoding="utf-8") == before
    with pytest.raises(ValueError, match="no event 99"):
        confirm_dates(run_dir, {99: "2026-10-09"})
