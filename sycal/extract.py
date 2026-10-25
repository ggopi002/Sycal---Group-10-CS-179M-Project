"""Syllabus (PDF / HTML / text) -> plain text with page markers.

PLACEHOLDER - owner: Guru. Minimal working version so the pipeline runs end-to-end;
replace with the real extractor (pdftotext layout mode, tables, multi-column handling).

Output format (the agent and the citation check depend on it):

    === page 1 ===
    ...text...
    === page 2 ===
    ...

Usage:
    python -m sycal.extract data/syllabi/sample.html -o outputs/run/text.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def page_marker(n: int) -> str:
    return f"=== page {n} ==="


def extract_pages(path: str | Path) -> list[str]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            return [page.extract_text() or "" for page in pdf.pages]
    if suffix in (".html", ".htm"):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        lines = (line.strip() for line in soup.get_text("\n").splitlines())
        return ["\n".join(line for line in lines if line)]
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
