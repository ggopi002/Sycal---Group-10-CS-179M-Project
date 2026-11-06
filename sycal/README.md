# sycal

Extraction, validation, and calendar export. Owner: Guru (except `schema.py`, which is shared).
The agent calls these as bash commands, so keep the command lines and output formats stable.

| Module | Command | Output |
|--------|---------|--------|
| `schema.py` | (library) | `Event`, `EventFile`, `check_event`, `load_event_file`, `dump_event_file` |
| `extract.py` | `python -m sycal.extract <syllabus> -o text.txt` | text with `=== page N ===` markers |
| `validate.py` | `python -m sycal.validate events.json --term-start D --term-end D --text text.txt` | `OK: ...` (exit 0) or `FAIL: N error(s)` + one line per error (exit 1); exit 2 if unreadable |
| `to_ics.py` | `python -m sycal.to_ics events.json -o out.ics --review review.md` | `.ics` (low-confidence events prefixed `[VERIFY]`) + needs-review list |

`extract.py`, `validate.py`, and `to_ics.py` are placeholders; see TEAM.md.
