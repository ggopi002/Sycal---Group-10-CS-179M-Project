"""Score predicted events against hand labels.

PLACEHOLDER - owner: Rehan. Working first version of the matching rule and metrics;
refine the matching (recurrence comparison, title synonyms) and add the error-analysis
categories. Keep the printed metric names stable so experiment tables stay comparable.

Matching: a predicted event matches a label event if they have the same `type` and a
similar title (difflib ratio >= TITLE_THRESHOLD). Each label matches at most one prediction;
same-date candidates are preferred, then the most similar title.

Metrics:
  precision        matched predictions / all predictions
  recall           matched labels / all labels
  date_accuracy    matched pairs with the exact same date and start time / matched pairs
  flagged_errors   wrong predictions (unmatched, or matched with a wrong date/time) that the
                   agent marked confidence=low / all wrong predictions  <- ethics metric

Usage:
    python -m eval.score outputs/<run>/sample/events.json data/labels/sample.json
    python -m eval.score outputs/<run_id> --labels data/labels      # every syllabus in a run
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path

from sycal.schema import Event, load_event_file

TITLE_THRESHOLD = 0.5


@dataclass
class Score:
    syllabus: str
    n_pred: int
    n_label: int
    n_matched: int
    n_exact: int
    n_wrong: int
    n_wrong_flagged: int

    @property
    def precision(self) -> float:
        return self.n_matched / self.n_pred if self.n_pred else 0.0

    @property
    def recall(self) -> float:
        return self.n_matched / self.n_label if self.n_label else 0.0

    @property
    def date_accuracy(self) -> float:
        return self.n_exact / self.n_matched if self.n_matched else 0.0

    @property
    def flagged_errors(self) -> float:
        return self.n_wrong_flagged / self.n_wrong if self.n_wrong else 1.0

    def row(self) -> dict:
        return asdict(self) | {
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "date_accuracy": round(self.date_accuracy, 3),
            "flagged_errors": round(self.flagged_errors, 3),
        }


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def match(pred: list[Event], labels: list[Event]) -> list[tuple[int, int]]:
    """Greedy one-to-one matching. Returns (pred index, label index) pairs."""
    candidates = []
    for i, p in enumerate(pred):
        for j, lab in enumerate(labels):
            sim = _similarity(p.title, lab.title)
            if p.type == lab.type and sim >= TITLE_THRESHOLD:
                candidates.append((p.date == lab.date, sim, i, j))
    candidates.sort(reverse=True)
    used_p, used_l, pairs = set(), set(), []
    for _, _, i, j in candidates:
        if i not in used_p and j not in used_l:
            used_p.add(i)
            used_l.add(j)
            pairs.append((i, j))
    return pairs


def score(pred: list[Event], labels: list[Event], syllabus: str = "") -> Score:
    pairs = match(pred, labels)
    exact = {i for i, j in pairs if (pred[i].date, pred[i].start) == (labels[j].date, labels[j].start)}
    wrong = [i for i in range(len(pred)) if i not in exact]
    return Score(
        syllabus=syllabus,
        n_pred=len(pred),
        n_label=len(labels),
        n_matched=len(pairs),
        n_exact=len(exact),
        n_wrong=len(wrong),
        n_wrong_flagged=sum(pred[i].confidence == "low" for i in wrong),
    )


def total(scores: list[Score]) -> Score:
    fields = ("n_pred", "n_label", "n_matched", "n_exact", "n_wrong", "n_wrong_flagged")
    return Score("TOTAL", *(sum(getattr(s, f) for s in scores) for f in fields))


def score_run(run_dir: Path, labels_dir: Path) -> list[Score]:
    scores = []
    for events_path in sorted(run_dir.glob("*/events.json")):
        label_path = labels_dir / f"{events_path.parent.name}.json"
        if not label_path.exists():
            print(f"skip {events_path.parent.name}: no label at {label_path}", file=sys.stderr)
            continue
        pred, labels = load_event_file(events_path), load_event_file(label_path)
        scores.append(score(pred.events, labels.events, events_path.parent.name))
    return scores


def print_table(scores: list[Score]) -> None:
    cols = ("syllabus", "n_pred", "n_label", "precision", "recall", "date_accuracy", "flagged_errors")
    print("  ".join(f"{c:>14}" for c in cols))
    for s in scores:
        r = s.row()
        print("  ".join(f"{str(r[c]):>14}" for c in cols))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pred", help="predicted events.json, or a run directory")
    parser.add_argument("label", nargs="?", help="label .json (when pred is a file)")
    parser.add_argument("--labels", default="data/labels", help="labels directory (when pred is a run directory)")
    parser.add_argument("--csv", help="also write per-syllabus rows here")
    args = parser.parse_args(argv)

    pred_path = Path(args.pred)
    if pred_path.is_dir():
        scores = score_run(pred_path, Path(args.labels))
    else:
        if not args.label:
            parser.error("label file required when pred is a file")
        scores = [score(load_event_file(pred_path).events, load_event_file(args.label).events, pred_path.parent.name)]
    if not scores:
        print("no scored syllabi")
        return 1
    if len(scores) > 1:
        scores.append(total(scores))
    print_table(scores)
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(scores[0].row()))
            writer.writeheader()
            writer.writerows(s.row() for s in scores)
    return 0


if __name__ == "__main__":
    sys.exit(main())
