"""
One-time (or periodic) seed script: pulls several recent weeks of CDC FluView
narrative reports, embeds each with Bedrock Titan, and stores them in health_reports.

Without this, health_reports starts empty and search_similar_reports() (the vector
search step in app/agent.py) has nothing to find - this is what gives the agent
actual historical context to reason over instead of an empty result every time.

Run: python -m app.seed_reports
Requires: DATABASE_URL set (CockroachDB) and AWS Bedrock model access enabled for
the embedding model in app/config.py (BEDROCK_EMBEDDING_MODEL_ID).
"""

from sqlalchemy import text
from app.db import engine, insert_report, log_audit
from app.fluview import fetch_recent_reports
from app.agent import embed_text

REPORT_COUNT = 8  # ~2 months of weekly reports - enough for vector search to be meaningful


def _already_seeded(source: str, title: str) -> bool:
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT 1 FROM health_reports WHERE source = :source AND title = :title LIMIT 1"),
            {"source": source, "title": title},
        ).fetchone()
    return row is not None


def run_seed():
    reports = fetch_recent_reports(REPORT_COUNT)
    if not reports:
        print("[seed] No FluView reports found - check app/fluview.py against the live site")
        return {"reports_found": 0, "inserted": 0, "skipped": 0}

    inserted = 0
    skipped = 0
    for report in reports:
        if _already_seeded(report["source"], report["title"]):
            skipped += 1
            continue

        embedding = embed_text(report["content"])
        insert_report(
            source=report["source"],
            title=report["title"],
            content=report["content"],
            region=report["region"],
            published_date=report["published_date"],
            embedding=embedding,
        )
        inserted += 1
        print(f"[seed] Inserted: {report['title']}")

    log_audit("seed_job", "write", "health_reports:bulk_seed", {"inserted": inserted, "skipped": skipped})
    result = {"reports_found": len(reports), "inserted": inserted, "skipped": skipped}
    print(f"[seed] Done: {result}")
    return result


if __name__ == "__main__":
    run_seed()
