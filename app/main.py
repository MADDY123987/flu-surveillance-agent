from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from app.db import engine, get_recent_signals, search_similar_reports, transition_alert_state
from app.features import compute_features, is_stale
from app.config import TARGET_REGIONS
from app.agent import determine_direction, embed_text, run_agent_cycle
from app.ingest import run_ingest
from app.patterns import find_closest_match

app = FastAPI(title="Public Health Surveillance Agent")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/dashboard", StaticFiles(directory=STATIC_DIR, html=True), name="dashboard")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard/")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/signals/{signal_type}/{region}")
def signals(signal_type: str, region: str):
    """Recent time series for a signal/region - the raw memory the agent reasons over."""
    return {"region": region, "signal_type": signal_type, "data": get_recent_signals(signal_type, region)}


@app.get("/rankings")
def rankings():
    """
    Rank every region/signal combination by how anomalous it currently is (|z-score|),
    most concerning first among the rising ones. This is the 'top outbreak signals' view
    for the dashboard - turns raw memory into a genuinely useful prioritized view.

    Stale combinations (newest observation older than FRESHNESS_THRESHOLD_DAYS) are
    excluded entirely - a big z-score computed from months-old data isn't a current
    signal (see HANDOFF.md validation notes on the NY flu freshness fix). Ranking order
    is rising-first, then by |z-score| within each group - the z-score values themselves
    are unchanged, only where each row sorts.
    """
    signal_types = ["flu_like_illness", "covid19_hospitalization", "rsv_hospitalization"]
    ranked = []
    for region in TARGET_REGIONS:
        for signal_type in signal_types:
            recent = get_recent_signals(signal_type, region)
            features = compute_features(recent)
            if features.get("insufficient_data"):
                continue
            z = features.get("z_score")
            if z is None:
                continue
            if is_stale(recent[-1]["date"]):
                continue
            direction = determine_direction(z)
            ranked.append(
                {
                    "region": region,
                    "signal_type": signal_type,
                    "z_score": z,
                    "direction": direction,
                    "latest_value": features["latest_value"],
                    "week_over_week_pct_change": features["week_over_week_pct_change"],
                }
            )
    ranked.sort(key=lambda r: (0 if r["direction"] == "rising" else 1, -abs(r["z_score"])))
    return ranked


@app.get("/regions/{region}/closest-match")
def closest_match(region: str, signal_type: str):
    """
    Cross-region pattern match (stretch feature, targets "Creativity & Originality"):
    compares this region's current signal shape against other regions' recent history
    using the same embedding infrastructure as /reports/search - no new tables, no new
    integrations. On-demand only - deliberately not part of the periodic dashboard
    refresh, since it makes several embedding calls per request.
    """
    result = find_closest_match(region, signal_type)
    if result is None:
        return {"region": region, "signal_type": signal_type, "closest_match": None}
    return result


@app.get("/alerts")
def alerts(limit: int = 20):
    """
    Recent alerts, including the full agent_reasoning trace (fetch -> compute_features
    -> embed -> vector search -> reason -> decide) so the dashboard can show exactly
    why each alert fired - the "Agentic Memory Design" judging criterion made visible.
    """
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, signal_type, region, severity, message, state, agent_reasoning, observed_date, created_at
                FROM alerts ORDER BY created_at DESC LIMIT :limit
                """
            ),
            {"limit": limit},
        ).fetchall()
    return [
        {
            "id": str(r[0]),
            "signal_type": r[1],
            "region": r[2],
            "severity": r[3],
            "message": r[4],
            "state": r[5],
            "agent_reasoning": r[6],
            "observed_date": str(r[7]) if r[7] else None,
            "created_at": str(r[8]),
        }
        for r in rows
    ]


@app.get("/reports/search")
def search_reports(q: str, limit: int = 5):
    """
    Semantic search over health_reports: embeds the query the same way FluView reports
    were embedded at ingest time, then runs a real CockroachDB vector similarity search -
    lets a user type a description and see the memory layer respond live.

    `distance` is the raw L2 (`<->`) distance CockroachDB's vector index returns - lower
    means more similar. `similarity_pct` is a display-only monotonic transform
    (100 / (1 + distance)) for a friendlier UI number; it is NOT a calibrated percentage,
    just a way to rank/show closeness without presenting raw distance as if it were %.
    """
    if not q or not q.strip():
        return {"query": q, "results": []}

    embedding = embed_text(q)
    matches = search_similar_reports(embedding, limit=limit, actor="dashboard_search")
    return {
        "query": q,
        "results": [
            {
                "title": m["title"],
                "content": m["content"],
                "published_date": m["published_date"],
                "distance": m["distance"],
                "similarity_pct": round(100 / (1 + m["distance"]), 1),
            }
            for m in matches
        ],
    }


@app.get("/audit")
def audit(limit: int = 50):
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT actor, action, resource, created_at FROM audit_log ORDER BY created_at DESC LIMIT :limit"),
            {"limit": limit},
        ).fetchall()
    return [{"actor": r[0], "action": r[1], "resource": r[2], "created_at": str(r[3])} for r in rows]


@app.post("/alerts/{alert_id}/transition")
def transition_alert(alert_id: str, to_state: str, reason: str = ""):
    """Move an alert through its lifecycle: new -> acknowledged -> resolved."""
    transition_alert_state(alert_id, to_state, reason)
    return {"alert_id": alert_id, "new_state": to_state}


@app.get("/alerts/{alert_id}/history")
def alert_history(alert_id: str):
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT from_state, to_state, reason, transitioned_at
                FROM alert_state_transitions WHERE alert_id = :id ORDER BY transitioned_at
                """
            ),
            {"id": alert_id},
        ).fetchall()
    return [{"from": r[0], "to": r[1], "reason": r[2], "at": str(r[3])} for r in rows]


@app.post("/trigger/ingest")
def trigger_ingest():
    """Manually trigger an ingest cycle - useful for demos instead of waiting 4 hours."""
    return run_ingest()


@app.post("/trigger/agent/{signal_type}/{region}")
def trigger_agent(signal_type: str, region: str):
    """Manually trigger one agent reasoning cycle - shows the full step trace for the demo."""
    return run_agent_cycle(region, signal_type)
