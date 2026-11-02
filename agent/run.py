"""
    python -m agent.run --model qwen-local --mode full --syllabus sample.html
    python -m agent.run --experiment agent/experiments/smoke.yaml

Each run writes outputs/<run_id>/<model>-<mode>/<syllabus stem>/:
    text.txt           extracted syllabus (written by the agent)
    events.agent.json  exactly what the agent wrote
    events.json        final events: invalid ones dropped, ungrounded citations set to low confidence
    out.ics, review.md calendar + needs-review list
    trajectory.json    full mini-swe-agent conversation (for error analysis)
and appends one row to outputs/ledger.csv.

Score a run with: python -m eval.score outputs/<run_id>/<model>-<mode>
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml
from minisweagent.agents.default import DefaultAgent
from minisweagent.models import get_model

from agent.environment import BashEnvironment
from sycal import to_ics
from sycal.schema import EventFile, check_event, dump_event_file, event_from_dict
from sycal.validate import format_week_table, is_grounded, validate_events

REPO = Path(__file__).resolve().parent.parent
AGENT_DIR = REPO / "agent"
SYLLABI_DIR = REPO / "data" / "syllabi"
OUTPUTS_DIR = REPO / "outputs"
LEDGER = OUTPUTS_DIR / "ledger.csv"
LEDGER_FIELDS = [
    "timestamp", "run_id", "model", "mode", "syllabus", "exit_status", "steps", "cost_usd",
    "prompt_tokens", "completion_tokens", "n_events", "n_dropped", "n_ungrounded", "n_low", "validation_errors",
]  # fmt: skip


@dataclass
class Syllabus:
    file: str
    course: str
    term_start: str
    term_end: str

    @property
    def stem(self) -> str:
        return Path(self.file).stem


def load_manifest(path: Path = SYLLABI_DIR / "manifest.csv") -> dict[str, Syllabus]:
    with open(path, newline="", encoding="utf-8") as f:
        return {row["file"]: Syllabus(**row) for row in csv.DictReader(f)}


def _expand_env(value):
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_settings(model_profile: str, mode: str) -> tuple[dict, dict]:
    """Return (agent+env settings, model config) for one model profile and mode."""
    config = yaml.safe_load((AGENT_DIR / "config.yaml").read_text(encoding="utf-8"))
    profiles = yaml.safe_load((AGENT_DIR / "models.yaml").read_text(encoding="utf-8"))
    if model_profile not in profiles:
        raise SystemExit(f"unknown model profile '{model_profile}'; choose from {', '.join(profiles)}")
    if mode not in config["modes"]:
        raise SystemExit(f"unknown mode '{mode}'; choose from {', '.join(config['modes'])}")
    agent_cfg = config["agent"] | (config["modes"][mode] or {})
    agent_cfg["system_template"] = (AGENT_DIR / config["prompts"]["system"]).read_text(encoding="utf-8")
    agent_cfg["instance_template"] = (AGENT_DIR / config["prompts"]["instance"]).read_text(encoding="utf-8")
    model_cfg = config["model"] | _expand_env(profiles[model_profile])
    return {"agent": agent_cfg, "environment": config["environment"]}, model_cfg


def ledger_total(path: Path | None = None) -> float:
    path = path or LEDGER
    if not path.exists():
        return 0.0
    with open(path, newline="", encoding="utf-8") as f:
        return sum(float(row["cost_usd"] or 0) for row in csv.DictReader(f))


def append_ledger(row: dict, path: Path | None = None) -> None:
    path = path or LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def _shell_path(path: Path) -> str:
    """Path as the agent should type it: repo-relative when possible, forward slashes always."""
    try:
        return path.relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def _token_usage(messages: list[dict]) -> tuple[int, int]:
    prompt = completion = 0
    for msg in messages:
        usage = (msg.get("extra", {}).get("response") or {}).get("usage") or {}
        prompt += usage.get("prompt_tokens") or 0
        completion += usage.get("completion_tokens") or 0
    return prompt, completion


def finalize(out_dir: Path, syllabus: Syllabus) -> dict:
    """Turn the agent's events.json into the final event file, .ics, and review list.

    Harness-side safety net (ethics mitigation): events whose citation can't be found in the
    syllabus text are kept but forced to confidence=low, so they get a [VERIFY] tag.
    """
    stats = {"n_events": 0, "n_dropped": 0, "n_ungrounded": 0, "n_low": 0, "validation_errors": ""}
    events_path, text_path = out_dir / "events.json", out_dir / "text.txt"
    if not events_path.exists():
        stats["validation_errors"] = "no events.json"
        return stats
    try:
        raw = json.loads(events_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        stats["validation_errors"] = f"invalid JSON: {e.msg}"
        return stats
    shutil.copy(events_path, out_dir / "events.agent.json")
    raw_events = raw.get("events", []) if isinstance(raw, dict) else raw
    if not isinstance(raw_events, list):
        raw_events = []
    text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""

    stats["validation_errors"] = len(validate_events(raw_events, syllabus.term_start, syllabus.term_end, text or None))
    valid = [e for e in raw_events if not check_event(e)]
    stats["n_dropped"] = len(raw_events) - len(valid)
    events = [event_from_dict(e) for e in valid]
    for ev in events:
        if not is_grounded(ev.citation, text) and ev.confidence != "low":
            ev.confidence = "low"
            stats["n_ungrounded"] += 1
    event_file = EventFile(syllabus.file, syllabus.term_start, syllabus.term_end, events)
    dump_event_file(event_file, events_path)
    (out_dir / "out.ics").write_bytes(to_ics.to_calendar(event_file).to_ical())
    (out_dir / "review.md").write_text(to_ics.review_markdown(event_file), encoding="utf-8")
    stats["n_events"] = len(events)
    stats["n_low"] = sum(ev.confidence == "low" for ev in events)
    return stats


def run_one(syllabus: Syllabus, model_profile: str, mode: str, run_id: str, *, model=None) -> dict:
    """Run the agent on one syllabus. `model` overrides the profile (used by tests)."""
    settings, model_cfg = load_settings(model_profile, mode)
    out_dir = OUTPUTS_DIR / run_id / f"{model_profile}-{mode}" / syllabus.stem
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    env_cfg = settings["environment"]
    env = BashEnvironment(
        cwd=str(REPO),
        timeout=env_cfg["timeout"],
        # Put this interpreter first on PATH so `python -m sycal...` finds the project's packages.
        env=env_cfg["env"] | {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")},
    )
    agent = DefaultAgent(
        model or get_model(config=model_cfg), env, **settings["agent"], output_path=out_dir / "trajectory.json"
    )
    try:
        result = agent.run(
            task="",
            syllabus=_shell_path(SYLLABI_DIR / syllabus.file),
            run_dir=_shell_path(out_dir),
            course=syllabus.course,
            term_start=syllabus.term_start,
            term_end=syllabus.term_end,
            week_table=format_week_table(syllabus.term_start, syllabus.term_end),
            mode=mode,
        )
        exit_status = result.get("exit_status", "")
    except Exception as e:  # model server down, context overflow, ...: record it and keep going
        exit_status = f"{type(e).__name__}: {e}"[:200]

    prompt_tokens, completion_tokens = _token_usage(agent.messages)
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "run_id": run_id,
        "model": model_profile,
        "mode": mode,
        "syllabus": syllabus.file,
        "exit_status": exit_status,
        "steps": agent.n_calls,
        "cost_usd": round(agent.cost, 6),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    } | finalize(out_dir, syllabus)
    append_ledger(row)
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--experiment", help="YAML with models / modes / syllabi lists")
    parser.add_argument("--model", action="append", help="model profile from agent/models.yaml (repeatable)")
    parser.add_argument("--mode", action="append", choices=["baseline", "full"], help="(repeatable)")
    parser.add_argument("--syllabus", action="append", help="file name from data/syllabi/manifest.csv (repeatable)")
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--max-total-cost", type=float, default=20.0, help="stop if outputs/ledger.csv exceeds this")
    args = parser.parse_args(argv)

    plan = yaml.safe_load(Path(args.experiment).read_text(encoding="utf-8")) if args.experiment else {}
    models = args.model or plan.get("models") or ["qwen-local"]
    modes = args.mode or plan.get("modes") or ["full"]
    manifest = load_manifest()
    names = args.syllabus or plan.get("syllabi") or list(manifest)
    missing = [n for n in names if n not in manifest]
    if missing:
        raise SystemExit(f"not in data/syllabi/manifest.csv: {', '.join(missing)}")

    for model_profile in models:
        for mode in modes:
            for name in names:
                spent = ledger_total()
                if spent >= args.max_total_cost:
                    print(f"budget stop: ledger total ${spent:.2f} >= ${args.max_total_cost:.2f}")
                    return 1
                print(f"[{model_profile} / {mode}] {name} ...", flush=True)
                row = run_one(manifest[name], model_profile, mode, args.run_id)
                print(
                    f"  {row['exit_status']}: {row['n_events']} events, {row['n_low']} low-confidence, "
                    f"{row['validation_errors']} validation errors, {row['steps']} steps, ${row['cost_usd']:.4f}"
                )
    print(f"\nscore with: python -m eval.score outputs/{args.run_id}/<model>-<mode>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
