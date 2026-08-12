from sqlalchemy import create_engine, text
from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def log_audit(actor: str, action: str, resource: str, details: dict | None = None):
    """Write an audit trail row. Call this around every meaningful read/write."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO audit_log (actor, action, resource, details)
                VALUES (:actor, :action, :resource, :details)
                """
            ),
            {
                "actor": actor,
                "action": action,
                "resource": resource,
                "details": details or {},
            },
        )


def upsert_signal(source: str, signal_type: str, region: str, observed_date: str, value: float):
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO health_signals (source, signal_type, region, observed_date, value)
                VALUES (:source, :signal_type, :region, :observed_date, :value)
                ON CONFLICT (source, signal_type, region, observed_date)
                DO UPDATE SET value = excluded.value, ingested_at = now()
                """
            ),
            {
                "source": source,
                "signal_type": signal_type,
                "region": region,
                "observed_date": observed_date,
                "value": value,
            },
        )
    log_audit("ingest_job", "write", f"health_signals:{region}:{signal_type}", {"value": value})


def get_recent_signals(signal_type: str, region: str, limit: int = 12) -> list[dict]:
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT observed_date, value FROM health_signals
                WHERE signal_type = :signal_type AND region = :region
                ORDER BY observed_date DESC
                LIMIT :limit
                """
            ),
            {"signal_type": signal_type, "region": region, "limit": limit},
        ).fetchall()
    log_audit("agent", "read", f"health_signals:{region}:{signal_type}", {"rows": len(rows)})
    return [{"date": str(r[0]), "value": r[1]} for r in rows][::-1]  # oldest -> newest


def insert_report(source: str, title: str, content: str, region: str, published_date: str, embedding: list[float]):
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO health_reports (source, title, content, region, published_date, embedding)
                VALUES (:source, :title, :content, :region, :published_date, :embedding)
                """
            ),
            {
                "source": source,
                "title": title,
                "content": content,
                "region": region,
                "published_date": published_date,
                "embedding": embedding,
            },
        )


def search_similar_reports(embedding: list[float], limit: int = 3) -> list[dict]:
    """Vector similarity search over past reports - the 'has this happened before' query."""
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT title, content, published_date
                FROM health_reports
                ORDER BY embedding <-> :embedding
                LIMIT :limit
                """
            ),
            {"embedding": embedding, "limit": limit},
        ).fetchall()
    log_audit("agent", "read", "health_reports:vector_search", {"results": len(rows)})
    return [{"title": r[0], "content": r[1], "published_date": str(r[2])} for r in rows]


def insert_alert(signal_type: str, region: str, severity: str, message: str, reasoning: dict) -> str:
    """Create a new alert in the 'new' state and record that as its first transition."""
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO alerts (signal_type, region, severity, message, agent_reasoning, state)
                VALUES (:signal_type, :region, :severity, :message, :reasoning, 'new')
                RETURNING id
                """
            ),
            {
                "signal_type": signal_type,
                "region": region,
                "severity": severity,
                "message": message,
                "reasoning": reasoning,
            },
        ).fetchone()
        alert_id = str(row[0])
        conn.execute(
            text(
                """
                INSERT INTO alert_state_transitions (alert_id, from_state, to_state, reason)
                VALUES (:alert_id, 'none', 'new', 'agent generated alert')
                """
            ),
            {"alert_id": alert_id},
        )
    log_audit("agent", "alert_generated", f"alerts:{region}:{signal_type}", {"severity": severity, "alert_id": alert_id})
    return alert_id


def transition_alert_state(alert_id: str, to_state: str, reason: str, actor: str = "api_user"):
    """Move an alert through its lifecycle (new -> acknowledged -> resolved), keeping full history."""
    with engine.begin() as conn:
        current = conn.execute(text("SELECT state FROM alerts WHERE id = :id"), {"id": alert_id}).fetchone()
        if current is None:
            raise ValueError(f"No alert with id {alert_id}")
        from_state = current[0]

        conn.execute(
            text("UPDATE alerts SET state = :to_state, updated_at = now() WHERE id = :id"),
            {"to_state": to_state, "id": alert_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO alert_state_transitions (alert_id, from_state, to_state, reason)
                VALUES (:alert_id, :from_state, :to_state, :reason)
                """
            ),
            {"alert_id": alert_id, "from_state": from_state, "to_state": to_state, "reason": reason},
        )
    log_audit(actor, "alert_state_change", f"alerts:{alert_id}", {"from": from_state, "to": to_state})
