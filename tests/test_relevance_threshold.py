"""
Fast, no-DB unit tests for the relevance-filtering logic in app.db.filter_relevant and
the query text built by app.agent.build_situation_text. These don't touch CockroachDB or
Groq - they exercise pure functions with fixture data.
"""
from app.db import filter_relevant
from app.agent import build_situation_text, determine_direction
from app.config import REPORT_RELEVANCE_MAX_DISTANCE


def _match(title, distance):
    return {"title": title, "content": "...", "published_date": "2026-01-01", "distance": distance}


def test_filter_relevant_keeps_matches_at_or_below_threshold():
    matches = [_match("close", 0.1), _match("at_cutoff", 0.68), _match("far", 0.9)]
    kept = filter_relevant(matches, max_distance=0.68)
    assert [m["title"] for m in kept] == ["close", "at_cutoff"]


def test_filter_relevant_drops_everything_when_nothing_is_relevant():
    matches = [_match("least_bad", 0.78), _match("worse", 0.85)]
    kept = filter_relevant(matches, max_distance=0.68)
    assert kept == []


def test_filter_relevant_empty_input():
    assert filter_relevant([], max_distance=0.68) == []


def test_filter_relevant_uses_configured_default_threshold():
    # Regression guard: REPORT_RELEVANCE_MAX_DISTANCE was empirically derived (see
    # app/config.py) from a flu distribution of max=0.637 and a covid/rsv distribution
    # of min=0.727. If this default ever drifts outside that measured gap, the empirical
    # basis for it no longer holds and it should be re-derived, not silently trusted.
    assert 0.637 < REPORT_RELEVANCE_MAX_DISTANCE < 0.727

    flu_like_best_match = _match("flu report", 0.60)
    covid_like_best_match = _match("flu report", 0.78)
    assert filter_relevant([flu_like_best_match]) == [flu_like_best_match]
    assert filter_relevant([covid_like_best_match]) == []


def test_build_situation_text_reads_as_a_surveillance_sentence_not_a_bare_number():
    features = {"week_over_week_pct_change": 12.3, "z_score": 2.1}
    latest = {"value": 5.79, "date": "2026-01-26"}
    direction = determine_direction(features["z_score"])

    text = build_situation_text("flu_like_illness", "California", latest, features, direction)

    assert "influenza-like illness activity" in text
    assert "California" in text
    assert "5.79" in text
    assert "rising" in text
    # The old format this replaces was purely numeric: "flu_like_illness in California
    # was 5.79 as of 2026-01-26" - assert we're not just re-emitting that.
    assert text != "flu_like_illness in California was 5.79 as of 2026-01-26"


def test_build_situation_text_maps_all_three_signal_types_to_readable_labels():
    features = {"week_over_week_pct_change": 0.0, "z_score": 0.0}
    latest = {"value": 1.0, "date": "2026-01-01"}
    direction = determine_direction(features["z_score"])

    for signal_type, expected_phrase in [
        ("flu_like_illness", "influenza-like illness"),
        ("covid19_hospitalization", "COVID-19 hospitalization"),
        ("rsv_hospitalization", "RSV hospitalization"),
    ]:
        text = build_situation_text(signal_type, "Texas", latest, features, direction)
        assert expected_phrase in text
