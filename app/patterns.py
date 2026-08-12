"""
Cross-region pattern match: "closest historical match" for a region's current signal
shape, compared against OTHER regions' recent history - reuses the same embedding
infrastructure as app/agent.py and app/seed_reports.py (no new tables, no new
integrations). On-demand only (triggered from the dashboard by a button, not part of
the periodic refresh loop) since it makes several Bedrock embedding calls per request.
"""

import math
from app.agent import embed_text
from app.config import TARGET_REGIONS
from app.db import get_recent_signals, log_audit
from app.features import compute_features

WINDOW = 6  # cap rolling snapshots compared per other region, keeps embed call count small


def _snapshot_text(signal_type: str, region: str, date: str, value: float, z_score) -> str:
    z_part = f"z-score {z_score}" if z_score is not None else "insufficient baseline for a z-score"
    return f"{signal_type} in {region} was {value} on {date} ({z_part})"


def _euclidean(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def find_closest_match(region: str, signal_type: str) -> dict | None:
    """
    Returns None if the target region has no usable history for this signal (e.g. a
    known data gap - see HANDOFF.md section 9) or no other region has a comparable match.
    """
    target_recent = get_recent_signals(signal_type, region)
    target_features = compute_features(target_recent)
    if target_features.get("insufficient_data") or not target_recent:
        return None

    latest = target_recent[-1]
    target_text = _snapshot_text(signal_type, region, latest["date"], latest["value"], target_features.get("z_score"))
    target_embedding = embed_text(target_text)

    best = None
    for other_region in TARGET_REGIONS:
        if other_region == region:
            continue
        other_recent = get_recent_signals(signal_type, other_region)
        if len(other_recent) < 3:
            continue  # not enough points for even one rolling feature window

        window = other_recent[-WINDOW:]
        for i in range(2, len(window)):
            snapshot = window[: i + 1]
            feats = compute_features(snapshot)
            if feats.get("insufficient_data") or feats.get("z_score") is None:
                continue
            point = snapshot[-1]
            snap_text = _snapshot_text(signal_type, other_region, point["date"], point["value"], feats["z_score"])
            snap_embedding = embed_text(snap_text)
            distance = _euclidean(target_embedding, snap_embedding)
            if best is None or distance < best["distance"]:
                best = {
                    "region": other_region,
                    "date": point["date"],
                    "value": point["value"],
                    "z_score": feats["z_score"],
                    "distance": distance,
                }

    log_audit(
        "dashboard_pattern_match",
        "read",
        f"health_signals:{region}:{signal_type}:cross_region_match",
        {"found": best is not None},
    )

    if best is None:
        return None
    return {
        "region": region,
        "signal_type": signal_type,
        "current": {
            "date": latest["date"],
            "value": latest["value"],
            "z_score": target_features.get("z_score"),
        },
        "closest_match": best,
    }
