# eval

Scoring against hand labels. Owner: Rehan.

```bash
python -m eval.score outputs/<run_id>/<model>-<mode>              # every syllabus in a run
python -m eval.score path/to/events.json data/labels/sample.json  # one file
python -m eval.score outputs/<run_id>/<model>-<mode> --csv results.csv
```

| Metric | Meaning |
|--------|---------|
| precision | matched predictions / predictions |
| recall | matched labels / labels |
| date_accuracy | matched pairs with exactly the right date and start time / matched pairs |
| flagged_errors | wrong predictions the agent marked `confidence: low` / wrong predictions (ethics metric) |

A prediction matches a label when the `type` is the same and the titles are similar (≥ 0.5).
`score.py` is a placeholder; see TEAM.md.
