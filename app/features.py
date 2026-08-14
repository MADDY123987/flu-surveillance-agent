"""
Feature engineering: turn raw signal history into derived stats an LLM can reason about
reliably. LLMs are unreliable at doing arithmetic/trend-detection over a raw list of
numbers - so we compute the actual math here in Python, and hand the LLM conclusions
to reason over, not just data to crunch.
"""

import statistics

# Below this, a baseline's stdev reflects reporting noise around a flat signal, not real
# variance - dividing by it inflates ordinary wobbles into z-scores that look alarming.
# Empirically chosen from live CDC data (see HANDOFF.md validation notes): quiet-season
# regional stdevs cluster ~0.06-0.19 across all 3 signal types, while genuine peak-season
# stdevs run ~0.39-1.76. 0.15 sits above typical quiet-season noise without suppressing
# real peak-season movement.
STDEV_FLOOR = 0.15


def compute_features(recent: list[dict]) -> dict:
    """
    recent: list of {"date": ..., "value": ...} ordered oldest -> newest (see db.get_recent_signals)
    Returns derived features describing the current situation vs its own history.
    """
    if len(recent) < 2:
        return {"insufficient_data": True}

    values = [r["value"] for r in recent]
    latest = values[-1]
    previous = values[-2]

    week_over_week_pct_change = (
        ((latest - previous) / previous) * 100 if previous != 0 else None
    )

    baseline = values[:-1]  # everything except the latest point, as the historical baseline
    baseline_mean = statistics.mean(baseline)
    baseline_stdev = statistics.stdev(baseline) if len(baseline) > 1 else 0

    z_score = (latest - baseline_mean) / max(baseline_stdev, STDEV_FLOOR)

    return {
        "latest_value": latest,
        "previous_value": previous,
        "week_over_week_pct_change": round(week_over_week_pct_change, 1) if week_over_week_pct_change is not None else None,
        "baseline_mean": round(baseline_mean, 2),
        "baseline_stdev": round(baseline_stdev, 2),
        "z_score": round(z_score, 2),
        "insufficient_data": False,
    }
