# agent

The SyCal agent loop on top of [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent). Owner: Sid.

```bash
python -m agent.run --model qwen-local --mode full --syllabus sample.html
python -m agent.run --experiment agent/experiments/smoke.yaml
python -m eval.score outputs/<run_id>/qwen-local-full
```

| File | Purpose |
|------|---------|
| `run.py` | Runs the agent per syllabus × model × mode, finalizes events (grounding check → `.ics`), appends to `outputs/ledger.csv` |
| `environment.py` | Runs every command through bash (mini-swe-agent's default is cmd.exe on Windows) |
| `config.yaml` | Step/cost/time limits, per-mode overrides, observation and format-error templates |
| `models.yaml` | Model profiles (`qwen-local`, `gemma-local`, `luna`, `nrp-strong`) |
| `prompts/` | `system.j2` and `instance.j2` (Jinja; `mode` switches the validator step on/off) |
| `experiments/` | Experiment grids: lists of models, modes, syllabi |

**Modes**
- `baseline`: extract → write events.json → submit. No validator.
- `full`: same, but the agent must run `sycal.validate` and fix errors until it prints OK.

**Budget**: `cost_limit` per run in `config.yaml`; `--max-total-cost` (default $20) stops a batch
when the ledger total reaches it. Local Ollama runs cost $0.
