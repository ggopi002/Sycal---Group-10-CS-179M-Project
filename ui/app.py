"""SyCal home page (basic UI skeleton). Owner: Rehan.

Right now this page only lets a student upload a syllabus (PDF or HTML).
The file is saved to outputs/uploads/. Later we'll connect it to the pipeline.

Run from the repo root:
    pip install flask
    python -m ui.app
Then open http://127.0.0.1:5000
"""

from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

REPO = Path(__file__).resolve().parent.parent
UPLOAD_DIR = REPO / "outputs" / "uploads"  # outputs/ is already git-ignored
ALLOWED_EXTENSIONS = {".pdf", ".html", ".htm"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB max upload
app.secret_key = "sycal-dev-only"  # needed for flash messages


@app.get("/")
def home():
    return render_template("index.html")


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

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file.save(UPLOAD_DIR / filename)
    # TODO: send the file to the pipeline (extract -> agent -> validate -> .ics)
    flash(f"Got it! {filename} was uploaded.", "success")
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)
