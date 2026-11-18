# data/labels

Hand labels, one file per syllabus: `<syllabus file stem>.json` (e.g. `cs179m.pdf` → `cs179m.json`).
Owner: Rehan. Format: the event schema in the top-level README, wrapped as in `sample.json`.

Check a label before committing it:

```bash
python -m sycal.extract data/syllabi/cs179m.pdf -o /tmp/cs179m.txt
python -m sycal.validate data/labels/cs179m.json --text /tmp/cs179m.txt
```

## Labeling rules

These decide what counts as a correct answer, so the agent prompt has to follow the same rules.
Change them together.

1. **What to label**: exams, quizzes, assignment/project deadlines, class meetings, labs, discussion
   sections, office hours, no-class days. Skip grading percentages and readings with no due date.
2. **Recurring meetings**: one event per pattern (lectures TuTh = one event), with an RRULE and an
   `UNTIL` date; `date` is the first meeting.
3. **Deadlines**: `start` is the due time, `end` is `null`. No time given → both `null`.
4. **Relative dates** ("Week 6 Thursday"): convert them using the week table (Week 1 = the week that
   contains `term_start`).
5. **Citation**: `p.N: '<exact text>'`, copied from the *extracted* text so the grounding check passes.
6. **Confidence**: labels are always `high`; it's the agent's field.
7. **Ambiguous items** (e.g. "Midterm: TBA"): leave them out and list them under "Notes" in your
   PR, so we can discuss how the agent should handle them.
