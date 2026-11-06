"""Runs the real harness (bash, extract, validate, finalize, ledger) with a scripted model."""

import csv

from minisweagent.models.test_models import DeterministicModel, make_output

from agent import run
from agent.run import Syllabus


def test_num_gpu_only_set_by_env_on_local_models(monkeypatch):
    monkeypatch.delenv("SYCAL_NUM_GPU", raising=False)
    assert "num_gpu" not in run.load_settings("qwen-local", "full")[1]["model_kwargs"]

    monkeypatch.setenv("SYCAL_NUM_GPU", "0")
    assert run.load_settings("qwen-local", "full")[1]["model_kwargs"]["num_gpu"] == 0
    assert "num_gpu" not in run.load_settings("luna", "full")[1]["model_kwargs"]


def test_scripted_agent_run(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(run, "LEDGER", tmp_path / "ledger.csv")
    syllabus = Syllabus("sample.html", "CS 999", "2026-09-24", "2026-12-11")
    out = (tmp_path / "t" / "qwen-local-full" / "sample").as_posix()
    copy_label = (
        "python -c \"import json; d = json.load(open('data/labels/sample.json', encoding='utf-8')); "
        "d['events'][2]['citation'] = 'p.1: made up'; "
        f"json.dump(d['events'], open('{out}/events.json', 'w', encoding='utf-8'))\""
    )
    script = [
        f"python -m sycal.extract data/syllabi/sample.html -o {out}/text.txt",
        copy_label,
        f"python -m sycal.validate {out}/events.json --term-start 2026-09-24 --term-end 2026-12-11 --text {out}/text.txt",
        "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
    ]
    model = DeterministicModel(outputs=[make_output("THOUGHT", [{"command": c}], cost=0.0) for c in script])

    row = run.run_one(syllabus, "qwen-local", "full", "t", model=model)

    assert row["exit_status"] == "Submitted"
    assert row["steps"] == 4
    assert row["n_events"] == 10
    assert row["n_ungrounded"] == 1  # the made-up citation was downgraded to low confidence
    assert (tmp_path / "t" / "qwen-local-full" / "sample" / "out.ics").exists()
    with open(tmp_path / "ledger.csv", encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 1
