
## How the pieces connect

```
data/syllabi/*.pdf|html ──► sycal.extract ──► text.txt ─┐
   (Rehan)                    (Guru)                    │
                                                        ▼
                          agent.run (Sid) ── model writes events.json ──► sycal.validate (Guru)
                                ▲                                            │
                                └──────────── FAIL: errors ◄─────────────────┘
                                │ OK
                                ▼
                 finalize: grounding check ──► sycal.to_ics ──► out.ics + review.md
                                │                 (Guru)
                                ▼
                     outputs/<run>/.../events.json ──► eval.score vs data/labels (Rehan)
```

The agent can only run bash, so **each module's command line is its contract**. You can rewrite
everything inside your module, but keep its command, arguments, and output format stable, or
agree on the change with the people who depend on it.

## Ground rules

- **Shared files**: `sycal/schema.py`, `data/labels/sample.json`, and the event schema in
  `README.md`. Changes need a PR approved by all three of us.
- **Placeholders**: files marked `PLACEHOLDER - owner: <name>` are minimal working versions written
  so the pipeline runs end-to-end. The owner replaces them; they are not anyone's finished work.
- **Branches**: one branch per task (`guru/extract-pdftotext`, `rehan/labels-batch1`, ...), PR into
  `main`, one teammate reviews. Your commits are your evidence for the individual progress reports.
- **Tests**: `python -m pytest` must pass before merging. Add a test when you add a check or metric.
- **Run outputs** stay local (`outputs/` is git-ignored). Commit final experiment tables on purpose.

## Sid: agent loop, prompts, model comparison (`agent/`)

**Owns:** `agent/run.py`, `agent/environment.py`, `agent/config.yaml`, `agent/models.yaml`,
`agent/prompts/`, `agent/experiments/`, `outputs/ledger.csv`.

**Provides:** `python -m agent.run --model <profile> --mode baseline|full --syllabus <file>` and
`--experiment <yaml>`. Writes one folder per syllabus run plus a ledger row (cost, tokens, steps).

| Week | Tasks |
|------|-------|
| 4 | - [x] Skeleton: agent loop on mini-swe-agent, bash environment, model profiles, ledger, tests<br>- [ ] Smoke test qwen3:4b and gemma4:e2b on `sample.html`; fix prompt problems<br>- [ ] Update NVIDIA driver so Ollama can use the GPU (currently CPU-only, see `models.yaml`) |
| 5 | - [ ] Baseline runs (both models, `baseline` mode) on Rehan's first labeled syllabi<br>- [ ] Baseline numbers for the midterm presentation; progress report 1 |
| 6–7 | - [ ] Tune the `full` mode retry loop with Guru's validator messages<br>- [ ] Prompting for relative dates ("Week 6 Thursday") and confidence calibration<br>- [ ] Fallback if small models can't follow the bash format: fixed pipeline where the LLM only writes JSON<br>- [ ] Progress report 2 |
| 8 | - [ ] Full experiment grid (models × modes × all syllabi); stronger-model comparison (gpt-6-luna or NRP)<br>- [ ] Budget summary from the ledger |
| 9–10 | - [ ] Harness changes driven by Rehan's error analysis; re-run and compare |

**Depends on:** Guru's validator output format (the agent reads it), Rehan's manifest and labels.

## Guru: extraction, validation, calendar export (`sycal/`)

**Owns:** `sycal/extract.py`, `sycal/validate.py`, `sycal/to_ics.py`, `sycal/cli.py` (to create).

**Provides:**
- `python -m sycal.extract <syllabus> -o text.txt`: text with `=== page N ===` markers
- `python -m sycal.validate events.json --term-start D --term-end D --text text.txt`: prints `OK: ...`
  (exit 0) or `FAIL: N error(s)` + one actionable line per error (exit 1)
- `python -m sycal.to_ics events.json -o out.ics --review review.md`

| Week | Tasks |
|------|-------|
| 4 | - [ ] Replace the extract placeholder: `pdftotext -layout` with a pdfplumber fallback; check multi-column PDFs and schedule tables on Rehan's real syllabi<br>- [ ] HTML extraction for course websites / Canvas pages |
| 5 | - [ ] Import `out.ics` into Google Calendar and Apple Calendar; fix anything that shows up wrong (time zones, all-day events, recurrence end dates)<br>- [ ] Progress report 1 |
| 6–7 | - [ ] Harden the validator (more checks, clearer messages) and agree on message wording with Sid<br>- [ ] Citation grounding: make the match tolerant of extraction noise (hyphenation, line breaks) without accepting made-up quotes<br>- [ ] Holidays inside recurring classes (e.g. no lecture on Thanksgiving): propose a schema change or EXDATE handling<br>- [ ] Progress report 2 |
| 8 | - [ ] `python -m sycal.cli run <syllabus> --term A:B --model <profile>`: single command for the demo |
| 9–10 | - [ ] Polish the needs-review list for the demo |

**Depends on:** Rehan's syllabi to test extraction against. **Others depend on:** everything; the
validator's output is what the agent sees, so change its format only together with Sid.

## Rehan: data, labels, metrics, error analysis, ethics, demo (`data/`, `eval/`)

**Owns:** `data/syllabi/` + `manifest.csv`, `data/labels/`, `eval/score.py`, `eval/report.py` (to create),
`docs/ethics.md` (to create).

**Provides:**
- Syllabi listed in `data/syllabi/manifest.csv` (`file,course,term_start,term_end`)
- One label file per syllabus, `data/labels/<syllabus stem>.json`, following `data/labels/README.md`
- `python -m eval.score outputs/<run_id>/<model>-<mode>`: precision, recall, date accuracy,
  flagged-errors rate

| Week | Tasks |
|------|-------|
| 4 | - [ ] Collect syllabi from classmates (ask permission; see the privacy note in `data/syllabi/README.md`)<br>- [ ] Label the first 10; have Sid or Guru double-label 2 to check that the labeling rules are clear |
| 5 | - [ ] Finalize the matching rule in `eval/score.py`; produce the baseline table for the midterm<br>- [ ] Progress report 1 |
| 6 | - [ ] All ~30 syllabi labeled |
| 7 | - [ ] `eval/report.py`: compare runs (baseline vs full, model vs model) in one table<br>- [ ] Progress report 2 |
| 8 | - [ ] Score the full experiment grid |
| 9 | - [ ] Error analysis: categorize wrong/missed events (bad extraction, relative date, wrong year, hallucinated, ...)<br>- [ ] `docs/ethics.md`: risk of trusting a wrong deadline, our mitigation ([VERIFY] + citation grounding), and how well it worked (flagged-errors rate) |
| 10 | - [ ] Lead the demo |

**Depends on:** the event schema. **Others depend on:** labels and the manifest; the baseline can't
be scored until the first labels exist.

## Everyone

| When | What |
|------|------|
| Week 4/5 | Midterm presentation (8 min, everyone presents). Related work: each person reviews one existing project (what it does, design, limitations, how SyCal differs) |
| Weeks 5, 7 | Individual progress reports (~0.5 page each, about your own work) |
| Week 6 | Peer review with another team; submit one discussion summary |
| Week 9/10 | In-class demo |
| Week 11 | Final video, report, code |

## Decisions to confirm at the next meeting

1. **File wrapper**: event files are `{"syllabus", "term_start", "term_end", "events": [...]}`; the
   agent may write a bare list and the harness wraps it.
2. **Recurrence format**: RRULE without the `RRULE:` prefix, e.g. `FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261204`;
   `date` is the first occurrence; `UNTIL` is required.
3. **Matching rule for scoring**: same `type` + title similarity ≥ 0.5; date accuracy compares date
   and start time.
4. **Grounding policy**: an event whose citation isn't found in the text is kept but forced to
   `confidence: low`, which adds `[VERIFY]` in the calendar.
5. **Stronger comparison model**: gpt-6-luna (paid, a few dollars) or NRP (free, if the course gives
   access).

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest
# Local models (https://ollama.com):
ollama pull qwen3:4b
ollama pull gemma4:e2b
python -m agent.run --experiment agent/experiments/smoke.yaml
```

On Windows the agent runs commands through Git Bash; set `SYCAL_BASH` if it isn't at the default path.
