"""
The agent, built by hand (not AWS's managed Bedrock Agents product) so every step is
visible and controllable - useful both for learning and for the demo video.

Loop: fetch recent signal history -> embed a query describing the current situation ->
vector-search past reports for similar situations -> ask the reasoning model to compare
and decide -> store the alert (or not) with its full reasoning trace.
"""

import json
import boto3
from app.config import AWS_REGION, BEDROCK_EMBEDDING_MODEL_ID, BEDROCK_REASONING_MODEL_ID, TARGET_REGIONS, TARGET_SIGNAL
from app.db import get_recent_signals, search_similar_reports, insert_alert
from app.features import compute_features

bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)


def embed_text(text: str) -> list[float]:
    """Step: turn a description of the current situation into a vector for similarity search."""
    resp = bedrock.invoke_model(
        modelId=BEDROCK_EMBEDDING_MODEL_ID,
        body=json.dumps({"inputText": text}),
    )
    body = json.loads(resp["body"].read())
    return body["embedding"]


def reason_and_decide(region: str, signal_type: str, recent: list[dict], features: dict, similar_reports: list[dict]) -> dict:
    """Step: ask the reasoning model to compare current data against memory and decide."""
    prompt = f"""You are a public health surveillance analyst. Review the computed statistics
and historical context below, then decide if this warrants an alert. The statistics have
already been calculated for you - trust them rather than recomputing from the raw data.

Computed statistics for {signal_type} in {region}:
{json.dumps(features, indent=2)}
(z_score measures how many standard deviations the latest value is from its own recent
baseline - a z_score above ~2 or below ~-2 is generally notable.)

Raw recent readings (oldest to newest), for context only:
{json.dumps(recent, indent=2)}

Similar past reports/advisories found in memory:
{json.dumps(similar_reports, indent=2)}

Respond ONLY with JSON in this exact shape, no other text:
{{
  "meaningful_change": true or false,
  "severity": "info" or "watch" or "alert",
  "message": "one or two plain-English sentences explaining the situation and referencing history if relevant"
}}"""

    resp = bedrock.invoke_model(
        modelId=BEDROCK_REASONING_MODEL_ID,
        body=json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}],
            }
        ),
    )
    body = json.loads(resp["body"].read())
    raw_text = body["content"][0]["text"]
    return json.loads(raw_text)


def run_agent_cycle(region: str, signal_type: str):
    trace = {"region": region, "signal_type": signal_type, "steps": []}

    # Step 1: fetch recent signal history from CockroachDB
    recent = get_recent_signals(signal_type, region)
    trace["steps"].append({"step": "fetch_recent_signals", "count": len(recent)})
    if len(recent) < 2:
        print(f"[agent] Not enough history yet for {region}/{signal_type}, skipping")
        return trace

    # Step 2: compute derived statistics (z-score, week-over-week % change)
    features = compute_features(recent)
    trace["steps"].append({"step": "compute_features", "features": features})

    # Step 3: describe the current situation and embed it
    latest = recent[-1]
    situation_text = f"{signal_type} in {region} is currently {latest['value']} as of {latest['date']}"
    embedding = embed_text(situation_text)
    trace["steps"].append({"step": "embed_situation", "text": situation_text})

    # Step 4: search memory for similar past situations
    similar_reports = search_similar_reports(embedding)
    trace["steps"].append({"step": "search_historical_context", "matches": len(similar_reports)})

    # Step 5: reason and decide
    decision = reason_and_decide(region, signal_type, recent, features, similar_reports)
    trace["steps"].append({"step": "reason_and_decide", "decision": decision})

    # Step 5: act - store the alert if warranted
    if decision.get("meaningful_change"):
        insert_alert(
            signal_type=signal_type,
            region=region,
            severity=decision.get("severity", "info"),
            message=decision.get("message", ""),
            reasoning=trace,
        )
        trace["steps"].append({"step": "alert_stored"})

    return trace


def run_all():
    for region in TARGET_REGIONS:
        trace = run_agent_cycle(region, TARGET_SIGNAL)
        print(json.dumps(trace, indent=2))


if __name__ == "__main__":
    run_all()
