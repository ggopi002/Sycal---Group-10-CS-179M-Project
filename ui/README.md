# ui

Basic home page for SyCal (owner: Rehan). For now it only lets you upload a syllabus
(PDF or HTML). Uploaded files are saved to `outputs/uploads/`. Connecting it to the
pipeline comes later (see the TODO in `app.py`).

## Run it

From the repo root:

```bash
pip install flask
python -m ui.app
```

Then open http://127.0.0.1:5000. Stop it with Ctrl+C.

## Files

```
ui/
  app.py               the Flask app (home page + upload)
  templates/index.html the home page
  static/style.css     styles
```
