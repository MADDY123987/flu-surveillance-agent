# Deployment Plan

Companion to HANDOFF.md, focused specifically on getting this app running on AWS for
submission (functional demo app URL + AWS service requirement). HANDOFF.md stays the
overall source of truth for scope/architecture; this doc tracks deployment steps only.

Scope for this pass: S3 is skipped for now (not required - Lambda + EventBridge already
satisfy the "at least 1 AWS service" requirement, see HANDOFF.md section 5). Analytics/
retrieval work (query construction, relevance threshold, demo alerts, tests - see
HANDOFF.md) is closed; this doc starts fresh from "the app works locally" and moves
toward "the app runs on AWS."

## Step 1 — Prerequisites (already done, see HANDOFF.md section 10)

- CockroachDB Cloud cluster created, `app/schema.sql` applied
- Groq API key obtained, local `sentence-transformers` embeddings need no cloud account
- `.env` filled in and confirmed working against the real Cloud cluster (ingest, agent,
  dashboard, semantic search, alert regeneration all verified end-to-end - see HANDOFF.md)

## Step 2 — Containerize the FastAPI app (this pass)

**Goal:** package `app/main.py` (the FastAPI service - dashboard, rankings, semantic
search, manual trigger endpoints) as a container image that runs identically locally and
on AWS, and prove it against a real (if throwaway) CockroachDB instance before touching
AWS at all.

**Files added:**
- `Dockerfile` - `python:3.11-slim`, installs `requirements.txt`, bakes the
  `BAAI/bge-small-en-v1.5` embedding model into the image at build time (`HF_HOME` set
  before the `pip install`/model-download layers so the runtime lazy-load in
  `app/embeddings.py` just reads local disk instead of hitting Hugging Face on first
  request), copies `app/`, runs `python -m app.init_db` then `uvicorn app.main:app
  --host 0.0.0.0 --port 8080`.
- `app/init_db.py` - new. Applies `app/schema.sql` via the same SQLAlchemy engine
  `app/db.py` already uses. Every statement in `schema.sql` is `CREATE ... IF NOT
  EXISTS`, so this is idempotent and safe to run on every container start. Replaces the
  manual `cockroach sql --insecure -f schema.sql` step from HANDOFF.md section 10, which
  assumed a shell with the `cockroach` CLI - not present in the slim Python app image
  (only in the separate `cockroachdb/cockroach` image used for local compose).
- `docker-compose.yml` - two services:
  - `crdb`: `cockroachdb/cockroach:latest`, single-node, in-memory store (matches the
    local dev setup already documented in HANDOFF.md section 10), with a healthcheck so
    the app doesn't start before it can accept SQL connections.
  - `app`: builds from the `Dockerfile`, loads `GROQ_API_KEY`/`GROQ_MODEL`/
    `EMBEDDING_MODEL_NAME`/`TARGET_REGIONS`/etc. from the real `.env` file, but
    **overrides `DATABASE_URL`** to point at the local `crdb` service (`defaultdb`,
    which always exists on a fresh node - no separate `CREATE DATABASE` step needed)
    instead of the real Cloud cluster. Publishes port 8080.

**Deliberately not automated here:** ingest (`python -m app.ingest`) and report seeding
(`python -m app.seed_reports`) are not run automatically on container start. In the real
AWS deployment these are the scheduled Lambda's job (EventBridge, every 4h - see
HANDOFF.md section 5), decoupled from the always-on API service. Baking them into the
API container's startup would blur that separation and make every container restart do
a slow, network-dependent CDC pull. For this verification pass they're triggered
manually inside the running container (`docker compose exec app ...`) - see Verification
below.

**Verification performed (`docker compose up`, 2026-08-15):**
1. `docker compose build && docker compose up -d` - both services healthy.
2. `docker compose exec app python -m app.ingest --backfill` - real CDC data (ILINet +
   RESP-NET) pulled into the fresh local `crdb`, enough history for real z-scores.
3. `docker compose exec app python -m app.seed_reports` - real FluView narrative
   reports fetched, embedded (using the baked-in model - no download stall observed),
   stored with a working vector index.
4. `GET /dashboard/` - loads, no errors.
5. `GET /rankings` - returns real ranked region/signal combinations from the container's
   own local data.
6. `GET /reports/search?q=...` - real vector search hit, returned real FluView content
   with distances.
7. `POST /trigger/agent/{signal_type}/{region}` - one full agent cycle ran inside the
   container end to end (fetch -> features -> vector search -> Groq reasoning -> alert
   stored), confirmed via `GET /alerts`.

(Exact commands/output captured in the session this was run in - re-run the same six
commands above to reverify after any future change to the Dockerfile/compose file.)

## Step 3 — AWS console setup (not started - see chat for the current recommendation)

Not yet built. Candidates to decide between for running the container (App Runner vs.
ECS Fargate) and for the scheduled ingest Lambda are discussed in HANDOFF.md section 10
step 10 and in conversation, not finalized in this file yet. Do not start AWS console
work from this doc alone until that's confirmed - come back and fill this section in
once decided.
