# ui

Web page for SyCal (owner: Rehan). Upload a syllabus with the term dates, and the agent runs on
it in the background (full mode). The results page then shows:

- **Download calendar (.ics)** and the raw `events.json`
- **Your term**: a month-by-month calendar of exactly what the .ics adds (weekly classes
  expanded, holidays crossed out, dates to check outlined in dashes); ← → flips months
- **Check these**: low-confidence events, each with a date box. Events marked *estimated* have
  no date in the syllabus ("5 in-class quizzes"), so the date shown is the model's guess.
  Change a date, or tick "Date is right", then **Save dates**. The calendar file is rebuilt and
  those events lose their `[VERIFY]` tag (same as `python -m sycal.confirm`).
- **All events**, in date order

Uploads are saved to `outputs/uploads/<run id>/`, results to `outputs/<run id>/` (with a
`job.json` that the page reads), and each run adds a row to `outputs/ledger.csv`.

## Run it

From the repo root, with Ollama running for the local models:

```bash
pip install -e ".[ui]"
python -m ui.app
```

Then open http://127.0.0.1:5000. Stop it with Ctrl+C. A run takes a few minutes on a local
model; the results page refreshes itself and lists the agent's steps so far. If the server is
stopped mid-run, the page offers **Build calendar from what it wrote**, which finalizes the
agent's last events.json instead of starting over. `SYCAL_UI_MODEL=<profile>` picks a
different model from `agent/models.yaml` (default `qwen25-local`).

## Files

```
ui/
  app.py                  the Flask app (upload, background run, results, confirm, downloads)
  templates/base.html     shared head, top bar, footer
  templates/index.html    home page
  templates/results.html  results page
  static/style.css        styles
```
