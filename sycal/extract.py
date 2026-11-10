"""Syllabus (PDF / HTML / text) -> plain text with page markers.

Owner: Guru. Layout-aware in the spirit of LlamaParse, but local (no syllabus leaves the machine):
  * words are split with a tight x_tolerance, so tightly kerned PDFs (Google Docs exports)
    don't come out as "Thefinalexamwillbe..."
  * real tables (schedule grids, section lists) become Markdown tables in reading order,
    so "Week 4 / F / exam1" stay in the same row instead of being scattered across lines

Output format (the agent and the citation check depend on it):

    === page 1 ===
    ...text...
    | Week | 1 (1.6-1.12) | ... |
    | --- | --- | ... |
    === page 2 ===
    ...

Usage:
    python -m sycal.extract data/syllabi/sample.html -o outputs/run/text.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# pdfplumber's default (3) glues words together in tightly kerned PDFs; 1.5 keeps real spaces.
X_TOLERANCE = 1.5


def page_marker(n: int) -> str:
    return f"=== page {n} ==="


def markdown_table(rows: list[list[str | None]]) -> str:
    cells = [[" ".join((c or "").split()).replace("|", "/") for c in row] for row in rows]
    if len(cells) == 2:
        # Header + one row (section lists, office-hour grids): each column is one item, so
        # "Section 002: Ethan Nowaski Tuesday 10:00 AM-10:50 AM" keeps the label with its details.
        return "\n".join(f"{head}: {value}" for head, value in zip(*cells) if value)
    lines = ["| " + " | ".join(cells[0]) + " |", "|" + " --- |" * len(cells[0])]
    lines += ["| " + " | ".join(row) + " |" for row in cells[1:]]
    return "\n".join(lines)


def _real_tables(page) -> list:
    """Ruled tables only. Highlighted text boxes are also detected as 'tables', but those
    always have missing (None) cells; real grids have every cell, even if it is empty."""
    tables = []
    for table in page.find_tables():
        rows = table.extract(x_tolerance=X_TOLERANCE)
        if len(rows) >= 2 and len(rows[0]) >= 2 and all(c is not None for row in rows for c in row):
            tables.append((table.bbox, rows))
    return sorted(tables, key=lambda t: t[0][1])


def _pdf_page_text(page) -> str:
    """Text above, between, and below the tables, with each table as Markdown in its place."""
    parts, top = [], 0
    for (x0, t_top, x1, t_bottom), rows in _real_tables(page):
        if t_top > top:
            parts.append(page.crop((0, top, page.width, t_top)).extract_text(x_tolerance=X_TOLERANCE))
        parts.append(markdown_table(rows))
        top = max(top, t_bottom)
    if top < page.height:
        parts.append(page.crop((0, top, page.width, page.height)).extract_text(x_tolerance=X_TOLERANCE))
    return "\n".join(p.strip() for p in parts if p and p.strip())


def _html_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for table in soup.find_all("table"):
        rows = [[cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"])] for tr in table.find_all("tr")]
        rows = [row for row in rows if row]
        if len(rows) >= 2:
            width = max(len(row) for row in rows)
            table.replace_with("\n" + markdown_table([row + [""] * (width - len(row)) for row in rows]) + "\n")
    lines = (line.strip() for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)


def extract_pages(path: str | Path) -> list[str]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            return [_pdf_page_text(page) for page in pdf.pages]
    if suffix in (".html", ".htm"):
        return [_html_text(path.read_text(encoding="utf-8", errors="replace"))]
    if suffix in (".txt", ".md"):
        return [path.read_text(encoding="utf-8", errors="replace")]
    raise ValueError(f"unsupported syllabus format: {suffix}")


def extract_text(path: str | Path) -> str:
    return "\n".join(f"{page_marker(i)}\n{text.strip()}" for i, text in enumerate(extract_pages(path), 1)) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("syllabus")
    parser.add_argument("-o", "--output", help="write text here instead of stdout")
    args = parser.parse_args(argv)

    text = extract_text(args.syllabus)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
        n_pages = text.count("=== page ")
        print(f"wrote {n_pages} page(s), {len(text.splitlines())} lines to {args.output}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
