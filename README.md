# SyCal.ai — Group 10, CS 179M

SyCal.ai is a mini-swe-agent that reads a course syllabus (PDF or HTML) and turns every deadline, exam, class meeting, and office hour into a standard iCalendar (`.ics`) file that students can import into Google or Apple Calendar.

## Problem

Students juggle 3–5 classes each quarter, and syllabus week makes it hard to keep track of everything. SyCal pulls every date out of a syllabus and puts it on the student's calendar, so knowing what's due each week takes minimal effort.

## How it works

SyCal uses [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent), so the agent only needs bash. This gives a linear history and actions that run independently.

**Inputs:** a syllabus file (PDF or HTML) and the school term's start and end dates (quarter or semester).

**Pipeline:**

1. **Extract**: pull text from the syllabus with `pdftotext` / `pdfplumber` (PDF) or an HTML parser.
2. **Structure**: the agent pulls events into JSON that follows the [event schema](#event-schema).
3. **Validate**: a validation script checks that:
   - every date falls inside the term,
   - stated weekdays match their dates,
   - there are no duplicate events.

   If validation fails, the agent reruns and corrects its output.
4. **Export**: write a `.ics` file with Python's `icalendar` library, plus a "needs review" summary of low-confidence events flagged `[VERIFY]`.

## Event schema

The schema is locked. Every event the agent produces, and every hand label, must follow this shape:

```json
{
  "course": "CS 179M",
  "title": "Midterm Exam",
  "type": "exam | assignment | class | office_hours | other",
  "date": "2026-10-29",
  "start": "14:00", "end": "15:20",
  "recurrence": null,
  "citation": "p.3: '10/29 — Midterm (in class)'",
  "confidence": "high | low"
}
```

| Field        | Description |
|--------------|-------------|
| `course`     | Course code as written in the syllabus. |
| `title`      | Short event name. |
| `type`       | One of `exam`, `assignment`, `class`, `office_hours`, `other`. |
| `date`       | ISO date, `YYYY-MM-DD`. |
| `start`/`end`| 24-hour `HH:MM` times, or `null` for all-day events or deadlines with no time. |
| `recurrence` | `null` for one-off events; a recurrence rule for repeating events such as lectures and office hours. |
| `citation`   | Page and quoted source text the event came from. |
| `confidence` | `high` or `low`. Low-confidence events go on the "needs review" list. |

## Repository layout

```
data/syllabi/   raw syllabus PDFs / HTML
data/labels/    hand labels, one JSON file per syllabus
sycal/          extraction, validation, and .ics generation
                (extract.py, validate.py, to_ics.py)
agent/          mini-swe-agent config and prompts
eval/           scoring (score.py)
outputs/        generated .ics files and review lists
```

## Evaluation

We will collect about 30 syllabi from UCR classmates and hand-label every event. We then measure:

- **Precision and recall** on extracted events.
- **Exact-date accuracy**: how often the predicted date matches the label.

Small models often misread messy PDF layouts, so we expect the validation and retry steps to show a clear improvement over the baseline pipeline.

## Models and budget

We use small models such as gpt-6-luna, `gemma4:e2b`, and Qwen3, plus a stronger model for comparison. We aim to keep API costs well under the $100 recommended budget.

**Stack:** Python, `pdftotext` / `pdfplumber`, `icalendar`.

## Timeline

| Week   | Goals |
|--------|-------|
| 4      | Collect and label test syllabi; build a basic working pipeline. |
| 5      | Finish labeling, write the scoring script, record baseline scores; midterm presentation. |
| 6–7    | Add validation, retries, relative-date conversion, and `[VERIFY]` flags. |
| 8      | Run all experiments, including the stronger-model comparison. |
| 9      | Error analysis and ethical considerations. |
| 10     | Final report, slides, and demo. |

## Team

| Member | Responsibilities |
|--------|------------------|
| Sid    | Agent loop, prompts, comparing `gemma4:e2b` and Qwen3, harness improvements after error analysis. (`agent/`) |
| Guru   | PDF/HTML extraction, validation scripts, `.ics` generation, the "needs review" list. (`sycal/`) |
| Rehan  | Collecting and labeling syllabi, metrics, error analysis, ethics section, leading the demo. (`data/labels/`, `eval/`) |

## Ethics

A student who trusts a wrong deadline can miss an exam or assignment. SyCal flags dates it isn't sure about instead of silently guessing, and every event cites the syllabus text it came from so students can check it.
