"""
The agent, built by hand (not AWS's managed Bedrock Agents product) so every step is
visible and controllable - useful both for learning and for the demo video.

Loop: fetch recent signal history -> embed a query describing the current situation ->
vector-search past reports for similar situations -> ask the reasoning model to compare
and decide -> store the alert (or not) with its full reasoning trace.
"""

import json
from groq import Groq
from app.config import GROQ_API_KEY, GROQ_MODEL, TARGET_REGIONS, TARGET_SIGNAL
from app.db import get_recent_signals, search_similar_reports, insert_alert, filter_relevant
from app.embeddings import embed_text
from app.features import compute_features, is_stale, MIN_BASELINE_OBSERVATIONS

client = Groq(api_key=GROQ_API_KEY)

# Severity is decided here, deterministically, from the z-score computed by
# app.features.compute_features - not by the LLM. Groq's job is to explain and
# contextualize a severity that's already been decided, not to choose it (see
# HANDOFF.md validation notes: leaving severity to the model's free-text judgment
# produced internally inconsistent output, e.g. meaningful_change=true paired with
# severity="info" on a real threshold-crossing z-score).
#
# Severity is also directional: a large |z| only becomes watch/alert when the signal
# is rising. A large negative z (activity falling away from an elevated baseline) is
# not an outbreak signal just because the magnitude is big - it gets reported as
# declining activity instead (see HANDOFF.md validation notes on the Texas/US flu
# decline that was previously misread as alert-worthy).
ALERT_Z_THRESHOLD = 2
WATCH_Z_THRESHOLD = 1


def determine_direction(z_score: float | None) -> str:
    if z_score is None:
        return "neutral"
    if z_score > 0:
        return "rising"
    if z_score < 0:
        return "falling"
    return "neutral"


def determine_severity(z_score: float | None, direction: str) -> tuple[str, str]:
    """Returns (severity, rule_fired) - rule_fired is a human-readable audit trail of why."""
    if z_score is None:
        return "info", "no z-score available (insufficient baseline history)"
    az = abs(z_score)
    if direction != "rising":
        if az >= WATCH_Z_THRESHOLD:
            return "info", f"|z_score|={az:.2f} but direction={direction} -> declining/neutral activity, not an outbreak alert"
        return "info", f"|z_score|={az:.2f} < {WATCH_Z_THRESHOLD} -> info"
    if az >= ALERT_Z_THRESHOLD:
        return "alert", f"direction=rising, |z_score|={az:.2f} >= {ALERT_Z_THRESHOLD} -> alert"
    if az >= WATCH_Z_THRESHOLD:
        return "watch", f"direction=rising, |z_score|={az:.2f} >= {WATCH_Z_THRESHOLD} -> watch"
    return "info", f"direction=rising, |z_score|={az:.2f} < {WATCH_Z_THRESHOLD} -> info"


REPORT_SNIPPET_CHARS = 400  # keep the prompt within Groq's TPM limits - full text already
                             # did its job in the vector search step; only a snippet is
                             # needed here for the model to write 1-2 sentences of context

# Human-readable phrasing for each signal_type, used to build the retrieval query below.
SIGNAL_DESCRIPTIONS = {
    "flu_like_illness": "influenza-like illness activity",
    "covid19_hospitalization": "COVID-19 hospitalization rate",
    "rsv_hospitalization": "RSV hospitalization rate",
}


def build_situation_text(signal_type: str, region: str, latest: dict, features: dict, direction: str) -> str:
    """
    Builds the text that gets embedded to query health_reports for similar past situations.

    Previously this was a bare numeric statement ("flu_like_illness in California was 1.6
    as of 2026-08-01") - semantically close to nothing, since health_reports holds CDC
    narrative prose (see a real excerpt in app/seed_reports.py/HANDOFF.md), not numbers.
    This instead writes a short surveillance-style sentence - the same register FluView's
    narrative reports use - so a genuinely relevant flu report has a real chance to be the
    nearest neighbor instead of winning only because everything else is equally far away.
    """
    signal_label = SIGNAL_DESCRIPTIONS.get(signal_type, signal_type.replace("_", " "))
    wow = features.get("week_over_week_pct_change")
    z = features.get("z_score")
    trend = f"{direction} relative to its recent baseline" if direction != "neutral" else "steady relative to its recent baseline"
    detail = f" (week-over-week change {wow}%, z-score {z})" if wow is not None and z is not None else ""
    return (
        f"Surveillance update: {signal_label} in {region} is {trend}, "
        f"currently at {latest['value']} as of {latest['date']}{detail}."
    )


def reason_and_decide(region: str, signal_type: str, recent: list[dict], features: dict, similar_reports: list[dict]) -> dict:
    """Step: severity/direction are already decided (see determine_severity) - ask the
    reasoning model only to explain/contextualize it against history, not to choose it."""
    direction = determine_direction(features.get("z_score"))
    severity, rule_fired = determine_severity(features.get("z_score"), direction)
    meaningful_change = severity != "info"

    report_snippets = [
        {"title": r["title"], "published_date": r["published_date"], "excerpt": r["content"][:REPORT_SNIPPET_CHARS]}
        for r in similar_reports
    ]

    prompt = f"""You are a public health surveillance analyst. A surveillance system has
already computed the statistics below and, from a deterministic rule on the z-score and
its direction, has already classified this reading as severity "{severity}" ({rule_fired}).
The signal's current direction relative to its own recent baseline is "{direction}". Your
job is NOT to choose or restate a severity - it's to write a one or two sentence plain-English
explanation of why this reading does or doesn't look concerning given its direction,
referencing the computed statistics and any similar historical reports below. If direction is
"falling", describe it as declining activity rather than framing it as an outbreak concern.

Computed statistics for {signal_type} in {region}:
{json.dumps(features, indent=2)}

Raw recent readings (oldest to newest), for context only:
{json.dumps(recent, indent=2)}

Similar past reports/advisories found in memory (excerpts):
{json.dumps(report_snippets, indent=2)}

Respond ONLY with JSON in this exact shape, no other text:
{{
  "message": "one or two plain-English sentences explaining the situation and referencing history if relevant"
}}"""

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": "You are a public health surveillance analyst."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    raw_text = response.choices[0].message.content
    groq_context = json.loads(raw_text).get("message", "")

    return {
        "meaningful_change": meaningful_change,
        "severity": severity,
        "direction": direction,
        "rule_fired": rule_fired,
        "message": groq_context,
    }


def run_agent_cycle(region: str, signal_type: str, as_of_date: str | None = None):
    """
    as_of_date (optional, 'YYYY-MM-DD'): reason against data as it stood on this date
    instead of the newest available - for historical/demo runs over real past periods
    (e.g. a documented peak week). Freshness is judged relative to as_of_date in that
    case, not the wall-clock date this happens to run on. Omit for the regular live cycle.
    """
    trace = {"region": region, "signal_type": signal_type, "as_of_date": as_of_date, "steps": []}

    # Step 1: fetch recent signal history from CockroachDB
    recent = get_recent_signals(signal_type, region, as_of_date=as_of_date)
    trace["steps"].append({"step": "fetch_recent_signals", "count": len(recent)})
    if len(recent) < 2:
        print(f"[agent] Not enough history yet for {region}/{signal_type}, skipping")
        return trace

    # Step 2: compute derived statistics (z-score, week-over-week % change)
    features = compute_features(recent)
    trace["steps"].append({"step": "compute_features", "features": features})
    if features.get("insufficient_data"):
        print(f"[agent] Fewer than {MIN_BASELINE_OBSERVATIONS} baseline observations for {region}/{signal_type}, skipping")
        return trace

    # Step 2b: freshness guard - a stale "latest" isn't treated as current and doesn't
    # drive an alert, no matter what its z-score says (see HANDOFF.md validation notes
    # on the NY flu z=2.72 alert generated from an 11-month-stale data point).
    latest = recent[-1]
    if is_stale(latest["date"], as_of_date=as_of_date):
        trace["steps"].append({"step": "freshness_check", "stale": True, "latest_date": latest["date"]})
        print(f"[agent] Latest observation for {region}/{signal_type} ({latest['date']}) is stale, skipping")
        return trace
    trace["steps"].append({"step": "freshness_check", "stale": False, "latest_date": latest["date"]})

    # Step 3: describe the situation and embed it
    direction = determine_direction(features.get("z_score"))
    situation_text = build_situation_text(signal_type, region, latest, features, direction)
    embedding = embed_text(situation_text)
    trace["steps"].append({"step": "embed_situation", "text": situation_text})

    # Step 4: search memory for similar past situations, then drop anything that isn't
    # actually relevant (see REPORT_RELEVANCE_MAX_DISTANCE in app/config.py) - health_reports
    # only contains flu narrative text, so a covid/rsv query has no genuine match available
    # and should come back empty rather than citing the least-bad flu report as if relevant.
    raw_matches = search_similar_reports(embedding)
    similar_reports = filter_relevant(raw_matches)
    trace["steps"].append({
        "step": "search_historical_context",
        "matches": len(similar_reports),
        "candidates_considered": len(raw_matches),
        "matched_reports": [
            {"title": r["title"], "published_date": r["published_date"], "distance": r["distance"]}
            for r in similar_reports
        ],
    })

    # Step 5: reason and decide
    decision = reason_and_decide(region, signal_type, recent, features, similar_reports)
    trace["steps"].append({"step": "reason_and_decide", "decision": decision})

    # Step 6: act - store the alert if warranted
    if decision.get("meaningful_change"):
        insert_alert(
            signal_type=signal_type,
            region=region,
            severity=decision.get("severity", "info"),
            message=decision.get("message", ""),
            reasoning=trace,
            observed_date=latest["date"],
        )
        trace["steps"].append({"step": "alert_stored"})

    return trace


def run_all(as_of_date: str | None = None):
    for region in TARGET_REGIONS:
        trace = run_agent_cycle(region, TARGET_SIGNAL, as_of_date=as_of_date)
        print(json.dumps(trace, indent=2))


if __name__ == "__main__":
    run_all()
