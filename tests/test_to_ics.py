from icalendar import Calendar

from sycal.to_ics import review_markdown, to_calendar


def test_calendar_parses_and_keeps_recurrence(sample_file):
    cal = Calendar.from_ical(to_calendar(sample_file).to_ical())
    events = cal.walk("VEVENT")
    assert len(events) == len(sample_file.events)
    lecture = events[0]
    assert "BYDAY=TU,TH" in lecture["RRULE"].to_ical().decode()


def test_low_confidence_gets_verify_tag(sample_file):
    sample_file.events[4].confidence = "low"
    summaries = [str(e["SUMMARY"]) for e in to_calendar(sample_file).walk("VEVENT")]
    assert summaries[4] == "[VERIFY] CS 999: Midterm"
    assert "Midterm" in review_markdown(sample_file)


def test_estimated_date_is_explained(sample_file):
    ev = sample_file.events[2]
    ev.citation, ev.confidence = "p.2: 'There will be 2 homework assignments.'", "low"
    review = review_markdown(sample_file)
    assert "event 3: **HW1 due**" in review and "estimate" in review
    assert "estimate" in str(to_calendar(sample_file).walk("VEVENT")[2]["DESCRIPTION"])
