"""
Integration test: validates the empirical claim behind REPORT_RELEVANCE_MAX_DISTANCE
(see app/config.py) against the real health_reports table - that flu queries have a
genuinely closer match available than covid/rsv queries do, and that the configured
threshold actually separates them. Needs a real DATABASE_URL (loads the local sentence-
transformers embedding model too, so it's slower than the unit tests). Skipped if no
database is configured.
"""
import os
import pytest

from app.config import TARGET_REGIONS, REPORT_RELEVANCE_MAX_DISTANCE
from app.db import get_recent_signals, search_similar_reports, filter_relevant
from app.embeddings import embed_text
from app.features import compute_features
from app.agent import build_situation_text, determine_direction

pytestmark = pytest.mark.skipif(
    "DATABASE_URL" not in os.environ and not os.path.exists(".env"),
    reason="no DATABASE_URL configured",
)

SIGNAL_TYPES = ["flu_like_illness", "covid19_hospitalization", "rsv_hospitalization"]


def _best_distance(signal_type: str, region: str) -> float | None:
    recent = get_recent_signals(signal_type, region)
    if len(recent) < 2:
        return None
    features = compute_features(recent)
    if features.get("insufficient_data"):
        return None
    latest = recent[-1]
    direction = determine_direction(features.get("z_score"))
    situation_text = build_situation_text(signal_type, region, latest, features, direction)
    matches = search_similar_reports(embed_text(situation_text), limit=10, actor="test")
    return matches[0]["distance"] if matches else None


def test_flu_queries_have_a_relevant_match_within_the_threshold():
    flu_distances = [d for d in (_best_distance("flu_like_illness", r) for r in TARGET_REGIONS) if d is not None]
    assert flu_distances, "expected at least one region with enough flu history to query"
    # Not every region is guaranteed to clear the bar (e.g. a thin baseline could still
    # produce a weak match), but the large majority should, since real FluView content
    # about flu exists in health_reports.
    within_threshold = [d for d in flu_distances if d <= REPORT_RELEVANCE_MAX_DISTANCE]
    assert len(within_threshold) / len(flu_distances) >= 0.8


def test_covid_and_rsv_queries_have_no_relevant_match_and_get_filtered_out():
    other_distances = []
    for signal_type in ("covid19_hospitalization", "rsv_hospitalization"):
        for region in TARGET_REGIONS:
            d = _best_distance(signal_type, region)
            if d is not None:
                other_distances.append(d)
    assert other_distances, "expected at least one region with covid/rsv history to query"
    # health_reports has zero covid/rsv content - every one of these "best matches" is
    # really just the least-irrelevant flu report, and should be filtered out.
    still_relevant = [d for d in other_distances if d <= REPORT_RELEVANCE_MAX_DISTANCE]
    assert still_relevant == []


def test_filter_relevant_applied_end_to_end_matches_the_raw_distance_check():
    latest_signals = get_recent_signals("covid19_hospitalization", "US")
    if len(latest_signals) < 2:
        pytest.skip("no covid19_hospitalization history for US")
    features = compute_features(latest_signals)
    if features.get("insufficient_data"):
        pytest.skip("insufficient baseline for US covid19_hospitalization")
    latest = latest_signals[-1]
    direction = determine_direction(features.get("z_score"))
    situation_text = build_situation_text("covid19_hospitalization", "US", latest, features, direction)
    raw_matches = search_similar_reports(embed_text(situation_text), limit=10, actor="test")
    assert filter_relevant(raw_matches) == []
