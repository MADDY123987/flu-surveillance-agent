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


BACKFILL_START_EPIWEEK = 202440  # matches app.ingest.BACKFILL_START_EPIWEEK - continuous, no gaps
MAX_CONSECUTIVE_ERRORS = 15  # real network/parse errors (not 404s) in a row - abort rather than
                              # hammer a broken endpoint; keeps whatever was already inserted


def _epiweek_year_week_pairs(start_epiweek: int, end_epiweek: int) -> list[tuple[int, int]]:
    """
    Enumerate (year, week) pairs from start_epiweek to end_epiweek inclusive
    (e.g. 202440 -> 202440, 202441, ..., 202452, 202501, ...). Approximate like the
    rest of this codebase's epiweek handling (see app/ingest.py) - CDC's own report
    week numbering can drift from this anyway (see app/fluview.py), so exactness
    isn't required here: fetch_fluview_report() 404s gracefully on any week that
    doesn't exist under a given number.
    """
    pairs = []
    year = start_epiweek // 100
    week = start_epiweek % 100
    while year * 100 + week <= end_epiweek:
        pairs.append((year, week))
        week += 1
        if week > 52:
            week = 1
            year += 1
    return pairs


def run_backfill_seed(epiweek_start: int = BACKFILL_START_EPIWEEK, epiweek_end: int | None = None):
    """
    One-off backfill of FluView narrative reports across a continuous historical
    range (default: BACKFILL_START_EPIWEEK through today) - not the regular rolling
    "most recent N weeks" seed. This is a genuinely separate path from the numeric
    ILINet/RESP-NET backfill in app/ingest.py: it scrapes one HTML page per week
    rather than querying a JSON API range, so failures are handled per-week here
    rather than per-request. A missing/never-published week 404s and is skipped
    (expected, not an error). A real fetch/parse error is also skipped rather than
    crashing the whole run, since the scraper's HTML-structure assumptions were only
    verified against current pages - older ones could differ. Reports are inserted
    incrementally as they're fetched (not batched at the end) so that if this run is
    aborted partway, everything fetched so far is already persisted.
    """
    if epiweek_end is None:
        from app.ingest import _current_epiweek
        epiweek_end = _current_epiweek()

    pairs = _epiweek_year_week_pairs(epiweek_start, epiweek_end)

    results = {"inserted": 0, "skipped": 0}
    pages_fetched = 0
    pages_skipped_404 = 0
    pages_skipped_error = 0
    consecutive_errors = 0
    aborted = False

    for year, week in pairs:
        try:
            report = fetch_fluview_report(year, week)
        except Exception as e:
            pages_skipped_error += 1
            consecutive_errors += 1
            print(f"[seed] backfill: error fetching {year}-week-{week:02d}: {e!r} - skipping")
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(f"[seed] backfill: {consecutive_errors} consecutive errors - aborting, keeping what's inserted so far")
                aborted = True
                break
            continue

        consecutive_errors = 0
        if report is None:
            pages_skipped_404 += 1
            continue

        pages_fetched += 1
        _insert_reports([report], results)

    log_audit("seed_job", "write", "health_reports:backfill_seed", {**results, "pages_fetched": pages_fetched})
    result = {
        "weeks_probed": len(pairs),
        "pages_fetched": pages_fetched,
        "pages_skipped_404": pages_skipped_404,
        "pages_skipped_error": pages_skipped_error,
        "aborted": aborted,
        **results,
    }
    print(f"[seed] Backfill done: {result}")
    return result


if __name__ == "__main__":
    import sys
    if "--backfill" in sys.argv:
        run_backfill_seed()
    else:
        run_seed()
