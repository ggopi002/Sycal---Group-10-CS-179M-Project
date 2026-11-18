from pathlib import Path

import pytest

from sycal.extract import extract_text
from sycal.schema import load_event_file

REPO = Path(__file__).resolve().parent.parent
SAMPLE_SYLLABUS = REPO / "data" / "syllabi" / "sample.html"
SAMPLE_LABEL = REPO / "data" / "labels" / "sample.json"


@pytest.fixture
def sample_text() -> str:
    return extract_text(SAMPLE_SYLLABUS)


@pytest.fixture
def sample_file():
    return load_event_file(SAMPLE_LABEL)
