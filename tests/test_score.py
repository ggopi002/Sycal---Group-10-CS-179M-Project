import copy

from eval.score import score


def test_perfect_prediction(sample_file):
    s = score(sample_file.events, sample_file.events)
    assert (s.precision, s.recall, s.date_accuracy) == (1.0, 1.0, 1.0)


def test_missing_and_wrong_date(sample_file):
    pred = copy.deepcopy(sample_file.events[:-1])  # drop the final exam
    pred[4].date = "2026-10-27"  # midterm on the wrong day
    pred[4].confidence = "low"  # ...but flagged
    s = score(pred, sample_file.events)
    assert s.recall == 0.9
    assert s.precision == 1.0
    assert s.date_accuracy == 8 / 9
    assert s.flagged_errors == 1.0
