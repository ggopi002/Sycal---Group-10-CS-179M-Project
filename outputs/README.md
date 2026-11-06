# outputs

Run results (git-ignored except this file). Layout:

```
outputs/
  ledger.csv                        one row per syllabus run: model, mode, cost, tokens, steps, ...
  <run_id>/<model>-<mode>/<syllabus>/
    text.txt  events.agent.json  events.json  out.ics  review.md  trajectory.json
```

Commit final experiment tables deliberately (`git add -f`), not every run.
