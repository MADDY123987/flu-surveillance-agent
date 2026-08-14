"""
One-time (or periodic) seed script: pulls several recent weeks of CDC FluView
narrative reports, embeds each locally (BAAI/bge-small-en-v1.5), and stores them
in health_reports.

Without this, health_reports starts empty and search_similar_reports() (the vector
search step in app/agent.py) has nothing to find - this is what gives the agent
actual historical context to reason over instead of an empty result every time.

Run: python -m app.seed_reports
Requires: DATABASE_URL set (CockroachDB). No cloud credentials needed - embeddings
run locally via app/embeddings.py.
"""

from sqlalchemy import text
from app.db import engine, insert_report, log_audit
from app.fluview import fetch_recent_reports, fetch_fluview_report
from app.embeddings import embed_text

REPORT_COUNT = 8  # ~2 months of weekly reports - enough for vector search to be meaningful


def _already_seeded(source: str, title: str) -> bool:
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT 1 FROM health_reports WHERE source = :source AND title = :title LIMIT 1"),
            {"source": source, "title": title},
        ).fetchone()
    return row is not None


def _insert_reports(reports: list[dict], results: dict):
    for report in reports:
        if _already_seeded(report["source"], report["title"]):
            results["skipped"] += 1
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
        results["inserted"] += 1
        print(f"[seed] Inserted: {report['title']}")


def run_seed():
    reports = fetch_recent_reports(REPORT_COUNT)
    if not reports:
        print("[seed] No FluView reports found - check app/fluview.py against the live site")
        return {"reports_found": 0, "inserted": 0, "skipped": 0}

    results = {"inserted": 0, "skipped": 0}
    _insert_reports(reports, results)

    log_audit("seed_job", "write", "health_reports:bulk_seed", results)
    result = {"reports_found": len(reports), **results}
    print(f"[seed] Done: {result}")
    return result


def run_backfill_seed(year: int = 2026, weeks: range = range(1, 16)):
    """
    One-off backfill of specific historical FluView weeks (e.g. peak season, for
    validation) - not the regular rolling "most recent N weeks" seed. CDC's report
    week numbering can drift/lag from ISO weeks (see app/fluview.py) so this probes
    each week directly rather than assuming a formula; missing weeks 404 and are
    skipped, which is expected.
    """
    reports = []
    for week in weeks:
        report = fetch_fluview_report(year, week)
        if report is not None:
            reports.append(report)

    if not reports:
        print(f"[seed] No FluView reports found for {year} weeks {list(weeks)}")
        return {"reports_found": 0, "inserted": 0, "skipped": 0}

    results = {"inserted": 0, "skipped": 0}
    _insert_reports(reports, results)

    log_audit("seed_job", "write", "health_reports:backfill_seed", results)
    result = {"reports_found": len(reports), **results}
    print(f"[seed] Backfill done: {result}")
    return result


if __name__ == "__main__":
    import sys
    if "--backfill" in sys.argv:
        run_backfill_seed()
    else:
        run_seed()
