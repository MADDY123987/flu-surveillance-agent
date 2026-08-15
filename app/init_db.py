"""
Applies app/schema.sql against DATABASE_URL. Every statement in schema.sql is
CREATE ... IF NOT EXISTS, so this is idempotent - safe to run on every container start
(see the Dockerfile CMD) instead of requiring a separate manual `cockroach sql -f
schema.sql` step, which assumed a shell with the cockroach CLI available. That CLI isn't
present in the app image (only in the cockroachdb/cockroach image used for the local
compose database), so this reimplements the same statement-by-statement apply in Python
via the same SQLAlchemy engine the rest of the app already uses.
"""
from pathlib import Path
from sqlalchemy import text
from app.db import engine

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def apply_schema():
    raw = SCHEMA_PATH.read_text()
    with engine.begin() as conn:
        for stmt in raw.split(";"):
            # Skip chunks that are empty once "--" line comments are stripped (the file's
            # leading header comment, and the trailing empty chunk after the last ";").
            # Real statements are executed with their comments intact - CockroachDB's own
            # SQL parser handles "--" line comments natively.
            code_lines = [line for line in stmt.splitlines() if not line.strip().startswith("--")]
            if not "".join(code_lines).strip():
                continue
            conn.execute(text(stmt))
    print("[init_db] schema applied")


if __name__ == "__main__":
    apply_schema()
