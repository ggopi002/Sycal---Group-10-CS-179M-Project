"""The web UI end to end, with the agent replaced by a stub that writes a finished run."""

import io
import json

import pytest

from agent import run
from sycal.schema import EventFile, load_event_file
from sycal.to_ics import write_outputs
from tests.conftest import SAMPLE_LABEL
from ui import app as ui


class _InlineThread:
    def __init__(self, target, args, daemon):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@pytest.fixture
def client(tmp_path, monkeypatch, sample_file):
    monkeypatch.setattr(run, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(ui, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(ui, "REPO", tmp_path)
    monkeypatch.setattr(ui.threading, "Thread", _InlineThread)

    def fake_run_one(syllabus, model_profile, mode, run_id):
        sample_file.events[2].citation = "p.2: 'There will be 2 homework assignments.'"
        sample_file.events[2].confidence = "low"
        out_dir = tmp_path / run_id / f"{model_profile}-{mode}" / syllabus.stem
        out_dir.mkdir(parents=True)
        write_outputs(EventFile(syllabus.file, syllabus.term_start, syllabus.term_end, sample_file.events), out_dir)
        return {"exit_status": "Submitted"}

    monkeypatch.setattr(run, "run_one", fake_run_one)
    return ui.app.test_client()


def _upload(client, **form):
    data = {"syllabus": (io.BytesIO(b"<p>syllabus</p>"), "cs180.html"), "term_start": "2026-09-24", "term_end": "2026-12-11"}
    return client.post("/upload", data=data | form, content_type="multipart/form-data")


def test_upload_runs_and_shows_estimate(client):
    resp = _upload(client)
    page = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "Check these" in page and "estimated" in page
    assert "Download calendar" in page


def test_confirming_a_date_updates_the_calendar(client, tmp_path):
    run_id = _upload(client).headers["Location"].rsplit("/", 1)[1]
    resp = client.post(f"/runs/{run_id}/confirm", data={"date-3": "2026-10-09"}, follow_redirects=True)
    assert "Saved 1 date" in resp.get_data(as_text=True)

    out_dir = tmp_path / run_id / f"{ui.MODEL}-full" / "cs180"
    ev = load_event_file(out_dir / "events.json").events[2]
    assert (ev.date, ev.confidence) == ("2026-10-09", "high")
    assert client.get(f"/runs/{run_id}/out.ics").data.startswith(b"BEGIN:VCALENDAR")


def test_bad_term_and_bad_run_id_are_rejected(client):
    resp = _upload(client, term_end="2026-09-01")
    assert resp.headers["Location"].endswith("/")
    assert client.get("/runs/..%2f..%2fetc").status_code == 404


def test_calendar_expands_weekly_meetings(sample_file):
    months = ui._months(sample_file)
    assert [m["name"] for m in months] == ["September", "October", "November", "December"]
    days = {cell["day"]: cell for m in months for week in m["weeks"] for cell in week if cell["in_month"]}
    lecture = sample_file.events[0]  # Tue/Thu from 2026-09-24
    assert lecture in days[ui.date(2026, 10, 6)]["events"] and lecture in days[ui.date(2026, 10, 8)]["events"]
    assert lecture not in days[ui.date(2026, 10, 7)]["events"]
    assert days[ui.date(2026, 11, 26)]["off"]  # "No class Thursday 11/26"


def test_stopped_run_can_still_become_a_calendar(client, tmp_path, monkeypatch, sample_file):
    def killed_run_one(syllabus, model_profile, mode, run_id):
        out_dir = tmp_path / run_id / f"{model_profile}-{mode}" / syllabus.stem
        out_dir.mkdir(parents=True)
        events = json.loads(SAMPLE_LABEL.read_text(encoding="utf-8"))["events"]
        (out_dir / "events.json").write_text(json.dumps(events), encoding="utf-8")
        raise KeyboardInterrupt  # stand-in for the server being stopped mid-run

    monkeypatch.setattr(run, "run_one", killed_run_one)
    with pytest.raises(KeyboardInterrupt):
        _upload(client)
    run_id = next(tmp_path.glob("ui-*")).name
    ui._running.discard(run_id)

    assert "Build calendar from what it wrote" in client.get(f"/runs/{run_id}").get_data(as_text=True)
    page = client.post(f"/runs/{run_id}/finish", follow_redirects=True).get_data(as_text=True)
    assert "Your term" in page and "Download calendar" in page
