from fastapi import FastAPI
from sqlalchemy import text
from app.db import engine, get_recent_signals, transition_alert_state
from app.features import compute_features
from app.config import TARGET_REGIONS
from app.agent import run_agent_cycle
from app.ingest import run_ingest

app = FastAPI(title="Public Health Surveillance Agent")


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
    most concerning first. This is the 'top outbreak signals' view for the dashboard -
    turns raw memory into a genuinely useful prioritized view.
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
            ranked.append(
                {
                    "region": region,
                    "signal_type": signal_type,
                    "z_score": z,
                    "latest_value": features["latest_value"],
                    "week_over_week_pct_change": features["week_over_week_pct_change"],
                }
            )
    ranked.sort(key=lambda r: abs(r["z_score"]), reverse=True)
    return ranked


@app.get("/alerts")
def alerts(limit: int = 20):
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, signal_type, region, severity, message, created_at
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
            "created_at": str(r[5]),
        }
        for r in rows
    ]


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
