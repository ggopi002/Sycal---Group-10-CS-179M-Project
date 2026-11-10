"""SyCal web UI. Owner: Rehan.

Upload a syllabus and the agent runs on it in the background (full mode). The results page
shows the events, lets the student confirm or correct the dates that need review, and offers
the .ics. Uploads go to outputs/uploads/<run id>/, results to outputs/<run id>/.

Run from the repo root (a local model needs Ollama running):
    pip install -e ".[ui]"
    python -m ui.app
Then open http://127.0.0.1:5000. SYCAL_UI_MODEL picks the model profile (default qwen25-local).
"""

import json
import calendar
import os
import re
import threading
from collections import defaultdict
from datetime import date, datetime, time
from pathlib import Path

from dateutil.rrule import rrulestr
from flask import Flask, abort, flash, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

from agent import run
from sycal.confirm import confirm_dates
from sycal.schema import Event, EventFile, load_event_file
from sycal.to_ics import is_estimate

REPO = Path(__file__).resolve().parent.parent
UPLOAD_DIR = REPO / "outputs" / "uploads"  # outputs/ is already git-ignored
ALLOWED_EXTENSIONS = {".pdf", ".html", ".htm"}
DOWNLOADS = {"out.ics", "events.json", "review.md"}
MODEL = os.environ.get("SYCAL_UI_MODEL", "qwen25-local")
MODE = "full"
_RUN_ID_RE = re.compile(r"^ui-\d{8}-\d{6}(-\d+)?$")
_DAYS = {"MO": "Mon", "TU": "Tue", "WE": "Wed", "TH": "Thu", "FR": "Fri", "SA": "Sat", "SU": "Sun"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB max upload
app.secret_key = "sycal-dev-only"  # needed for flash messages

_running: set[str] = set()  # run ids whose agent thread is still going (lost on restart)


def _job_path(run_id: str) -> Path:
    return run.OUTPUTS_DIR / run_id / "job.json"


def _load_job(run_id: str) -> dict:
    if not _RUN_ID_RE.match(run_id) or not _job_path(run_id).exists():
        abort(404)
    job = json.loads(_job_path(run_id).read_text(encoding="utf-8"))
    if job["status"] == "running" and run_id not in _running:
        job["status"] = "stopped"  # the server restarted mid-run
    return job


def _save_job(run_id: str, job: dict) -> None:
    _job_path(run_id).parent.mkdir(parents=True, exist_ok=True)
    _job_path(run_id).write_text(json.dumps(job, indent=2), encoding="utf-8")


def _out_dir(job: dict) -> Path:
    return run.OUTPUTS_DIR / job["run_id"] / f"{job['model']}-{MODE}" / Path(job["file"]).stem


def _run_agent(run_id: str, job: dict) -> None:
    syllabus = run.Syllabus(job["file"], job["course"], job["term_start"], job["term_end"])
    try:
        job["row"] = run.run_one(syllabus, job["model"], MODE, run_id)
        job["status"] = "done"
    except Exception as e:  # keep the page useful: show what went wrong instead of spinning forever
        job["status"], job["error"] = "error", f"{type(e).__name__}: {e}"[:300]
    finally:
        _save_job(run_id, job)
        _running.discard(run_id)


def _new_run_id() -> str:
    base = "ui-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id, n = base, 1
    while (run.OUTPUTS_DIR / run_id).exists():
        n += 1
        run_id = f"{base}-{n}"
    return run_id


def _recent_runs(limit: int = 5) -> list[dict]:
    jobs = sorted(run.OUTPUTS_DIR.glob("ui-*/job.json"), reverse=True)[:limit]
    return [_load_job(p.parent.name) for p in jobs]


def _repeats(rule: str | None) -> str:
    """'FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261211' -> 'Weekly Tue/Thu until 2026-12-11'."""
    if not rule:
        return ""
    parts = dict(p.split("=", 1) for p in rule.removeprefix("RRULE:").split(";") if "=" in p)
    text = parts.get("FREQ", "").title()
    if "BYDAY" in parts:
        text += " " + "/".join(_DAYS.get(d[-2:], d) for d in parts["BYDAY"].split(","))
    if until := parts.get("UNTIL"):
        text += f" until {until[:4]}-{until[4:6]}-{until[6:8]}"
    return text


def _occurrences(ev: Event, start: date, end: date) -> list[date]:
    """Every day the event lands on within [start, end], so the page shows what the .ics will."""
    if not ev.recurrence:
        return [ev.day]
    try:
        rule = rrulestr(ev.recurrence.removeprefix("RRULE:"), dtstart=datetime.combine(ev.day, time()))
        return [d.date() for d in rule.between(datetime.combine(start, time()), datetime.combine(end, time.max), inc=True)]
    except (ValueError, TypeError):  # a rule dateutil can't expand (e.g. a UTC UNTIL): show the first day
        return [ev.day]


def _months(event_file: EventFile) -> list[dict]:
    """One planner page per month of the term: weeks of days, each with its events."""
    start, end = date.fromisoformat(event_file.term_start), date.fromisoformat(event_file.term_end)
    by_day: dict[date, list[Event]] = defaultdict(list)
    for ev in event_file.events:
        for day in _occurrences(ev, start, end):
            by_day[day].append(ev)
    for evs in by_day.values():
        evs.sort(key=lambda ev: ev.start or "")  # all-day items first, then by time

    months, year, month = [], start.year, start.month
    while (year, month) <= (end.year, end.month):
        weeks = []
        for week in calendar.Calendar(firstweekday=6).monthdatescalendar(year, month):  # weeks start on Sunday
            days = []
            for day in week:
                evs = by_day.get(day, []) if day.month == month else []
                days.append({
                    "day": day,
                    "in_month": day.month == month,
                    "in_term": start <= day <= end,
                    "off": any(ev.type == "other" and not ev.start for ev in evs),  # holiday / no class
                    "events": evs,
                })  # fmt: skip
            weeks.append(days)
        months.append({"id": f"{year}-{month:02d}", "name": calendar.month_name[month], "year": year, "weeks": weeks})
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def _progress(job: dict) -> list[str]:
    """What the agent has done so far, read from the trajectory it saves after every step."""
    path = _out_dir(job) / "trajectory.json"
    try:
        messages = json.loads(path.read_text(encoding="utf-8"))["messages"]
    except (OSError, ValueError, KeyError):
        return []
    steps = []
    for i, msg in enumerate(messages):
        actions = msg.get("extra", {}).get("actions") if msg.get("role") == "assistant" else None
        if not actions:
            continue
        command = actions[0].get("command", "")
        reply = messages[i + 1].get("content", "") if i + 1 < len(messages) else ""
        if "events.json" in command and "<<" in command:
            n_events = command.count('"title"')
            steps.append(f"Wrote {n_events} events")
        elif "sycal.validate" in command:
            result = re.search(r"\b(OK|FAIL): ?([^\n<]*)", reply if isinstance(reply, str) else "")
            steps.append(
                "Checking the events…" if not result
                else "Check passed" if result[1] == "OK"
                else f"Check found {result[2].strip() or 'problems'}; fixing them"
            )  # fmt: skip
        elif "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in command:
            steps.append("Finished; building your calendar")
        else:
            steps.append("Ran a command")
    return steps


@app.get("/")
def home():
    return render_template("index.html", recent=_recent_runs(), model=MODEL)


@app.post("/upload")
def upload():
    file = request.files.get("syllabus")
    if not file or not file.filename:
        flash("Please choose a file first.", "error")
        return redirect(url_for("home"))

    filename = secure_filename(file.filename)
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        flash("Please upload a PDF or HTML file.", "error")
        return redirect(url_for("home"))

    term_start, term_end = request.form.get("term_start", ""), request.form.get("term_end", "")
    try:
        if date.fromisoformat(term_start) >= date.fromisoformat(term_end):
            raise ValueError
    except ValueError:
        flash("Please give the first and last day of the term, with the last day after the first.", "error")
        return redirect(url_for("home"))

    run_id = _new_run_id()
    (UPLOAD_DIR / run_id).mkdir(parents=True)
    file.save(UPLOAD_DIR / run_id / filename)
    job = {
        "run_id": run_id,
        "file": (UPLOAD_DIR / run_id / filename).relative_to(REPO).as_posix(),
        "name": filename,
        "course": request.form.get("course", "").strip(),
        "term_start": term_start,
        "term_end": term_end,
        "model": MODEL,
        "status": "running",
        "started": datetime.now().isoformat(timespec="seconds"),
    }
    _save_job(run_id, job)
    _running.add(run_id)
    threading.Thread(target=_run_agent, args=(run_id, job), daemon=True).start()
    return redirect(url_for("results", run_id=run_id))


@app.get("/runs/<run_id>")
def results(run_id: str):
    job = _load_job(run_id)
    events, months = [], []
    if job["status"] == "done" and (_out_dir(job) / "out.ics").exists():
        event_file = load_event_file(_out_dir(job) / "events.json")
        events = [
            {"n": n, "ev": ev, "estimate": is_estimate(ev), "repeats": _repeats(ev.recurrence)}
            for n, ev in sorted(enumerate(event_file.events, 1), key=lambda p: (p[1].date, p[1].start or ""))
        ]
        months = _months(event_file)
    review = [e for e in events if e["ev"].confidence == "low"]
    # The agent's own file, before finalize: lets a stopped run still become a calendar.
    salvageable = job["status"] == "stopped" and (_out_dir(job) / "events.json").exists()
    started = datetime.fromisoformat(job["started"]) if job.get("started") else None
    return render_template(
        "results.html",
        job=job,
        events=events,
        review=review,
        months=months,
        today=date.today(),
        progress=_progress(job) if job["status"] == "running" else [],
        elapsed=int((datetime.now() - started).total_seconds()) if started else 0,
        salvageable=salvageable,
    )


@app.post("/runs/<run_id>/finish")
def finish(run_id: str):
    """Build the calendar from whatever events.json a stopped run left behind."""
    job = _load_job(run_id)
    if job["status"] != "stopped" or not (_out_dir(job) / "events.json").exists():
        abort(409)
    syllabus = run.Syllabus(job["file"], job["course"], job["term_start"], job["term_end"])
    try:
        stats = run.finalize(_out_dir(job), syllabus)
    except Exception as e:
        stats = {"validation_errors": f"{type(e).__name__}: {e}"[:200]}
    if (_out_dir(job) / "out.ics").exists():
        job["status"], job["row"] = "done", stats | {"exit_status": "stopped early"}
        _save_job(run_id, job)
    else:  # e.g. the agent was cut off mid-write and left broken JSON
        flash(f"Couldn't build a calendar from what the agent wrote: {stats['validation_errors']}.", "error")
    return redirect(url_for("results", run_id=run_id))


@app.post("/runs/<run_id>/confirm")
def confirm(run_id: str):
    job = _load_job(run_id)
    if job["status"] != "done":
        abort(409)
    event_file = load_event_file(_out_dir(job) / "events.json")
    dates = {}
    for n, ev in enumerate(event_file.events, 1):
        day = request.form.get(f"date-{n}")
        # A changed date is a correction; an unchanged one counts only if ticked as right.
        if day and ev.confidence == "low" and (day != ev.date or request.form.get(f"ok-{n}")):
            dates[n] = day
    if not dates:
        flash("Nothing to save: change a date or tick “Date is right”.", "error")
        return redirect(url_for("results", run_id=run_id))
    try:
        confirm_dates(_out_dir(job), dates)
    except ValueError as e:
        flash(f"Not saved: {e}.", "error")
    else:
        flash(f"Saved {len(dates)} date(s). Your calendar file is updated.", "success")
    return redirect(url_for("results", run_id=run_id))


@app.get("/runs/<run_id>/<name>")
def download(run_id: str, name: str):
    job = _load_job(run_id)
    if name not in DOWNLOADS:
        abort(404)
    stem = Path(job["file"]).stem
    return send_from_directory(_out_dir(job), name, as_attachment=True, download_name=f"{stem}-{name}")


if __name__ == "__main__":
    app.run(debug=True)
