# Outbreak Intelligence Agent

An agent that continuously ingests real CDC respiratory surveillance data, remembers it
durably and semantically in CockroachDB, and reasons over that memory to rank and explain
emerging outbreak risk across 11 US regions.

Built for the **CockroachDB × AWS Hackathon — Build with Agentic Memory**.

**Live demo:** `TODO — paste App Runner URL`
**Demo video:** `TODO — paste YouTube link`

---

## Why this exists

Respiratory surveillance signals — influenza-like illness rates, COVID and RSV
hospitalization rates, CDC's weekly narrative analysis — are published continuously but sit
in separate systems with no shared memory. Nobody is continuously watching them,
remembering what previous seasons looked like, and distinguishing a meaningful shift from
ordinary week-to-week noise.

The memory layer is the point. Without durable history there is no baseline, and without a
baseline there is no way to say whether this week matters.

**Currently in memory:** ~2,961 signal readings and 95 embedded CDC narrative reports,
covering 30 Sep 2024 → 8 Aug 2026 (two full respiratory seasons).

---

## What it does

Every 4 hours it ingests real CDC data, stores it in CockroachDB, and runs a five-step
reasoning loop that produces auditable, explained alerts.

**Regions (11):** US National, California, Texas, New York, Colorado, Georgia, Maryland,
Michigan, Minnesota, New Mexico, Tennessee — selected empirically by querying which regions
actually have usable RESP-NET and ILINet coverage, not assumed.

**Signals (3):** influenza-like illness (ILINet), COVID-19 hospitalization and RSV
hospitalization (RESP-NET), plus CDC FluView weekly narrative reports as the text corpus.

---

## Architecture

```
3 CDC sources
  ├── ILINet (CMU Delphi Epidata API)   -> influenza-like illness rate
  ├── RESP-NET (data.cdc.gov Socrata)   -> COVID-19 + RSV hospitalization rates
  └── FluView weekly narrative reports  -> real CDC written analysis (scraped HTML)
        |
   EventBridge Scheduler (4h) -> AWS Lambda -> ingest.py
   EventBridge Rule (weekly)  -> App Runner /trigger/seed -> seed_reports.py
        |
        v
   CockroachDB — four memory types:
     ├── health_signals             (time series, per region/signal/date)
     ├── health_reports + VECTOR    (FluView narrative text + embeddings, semantic search)
     ├── alerts + alert_state_transitions  (full lifecycle: new -> acknowledged -> resolved)
     └── audit_log                  (every agent read/write)
        ^
        |
   agent.py — single agent, 5-step loop:
     1. fetch_recent_signals()      <- CockroachDB
     2. compute_features()          -> z-score + week-over-week % change (real Python math,
                                       not delegated to the LLM)
     3. search_similar_reports()    <- CockroachDB vector search over FluView narratives
     4. reason_and_decide()         -> Groq (llama-3.3-70b-versatile)
     5. insert_alert()              -> CockroachDB
        ^
        |
   main.py (FastAPI) — REST API + dashboard on AWS App Runner
```

Embeddings are generated **locally** with `BAAI/bge-small-en-v1.5` (384 dimensions), baked
into the container image — no embedding API, no per-token cost, no cold-start download.

---

## CockroachDB tools used (2 required)

### 1. Distributed Vector Indexing

`health_reports.embedding` is a `VECTOR(384)` column with a vector index holding 95 embedded
CDC FluView narrative reports. It powers:

- **Semantic search** (`GET /reports/search?q=...`) — free-text search over historical CDC
  narrative analysis, exposed in the dashboard.
- **Historical context in reasoning** — step 3 of the agent loop retrieves semantically
  similar past reports and passes them to the LLM, so decisions are grounded in what
  comparable past periods actually looked like. Retrieved matches are shown in the UI with
  their dates and similarity scores.

**Relevance filtering.** Vector search always returns its top-k even when nothing relevant
exists. Since the corpus is entirely flu narrative text, a COVID or RSV query has no genuine
match available. A relevance threshold (`REPORT_RELEVANCE_MAX_DISTANCE = 0.68`) was derived
empirically by comparing best-match distance distributions across all 33 region×signal
queries:

| Group | n | min | max | mean |
|---|---|---|---|---|
| flu (relevant content exists) | 11 | 0.544 | 0.637 | 0.612 |
| COVID/RSV (no relevant content) | 20 | 0.727 | 0.829 | 0.782 |

Cleanly separable, so the agent returns *"no relevant historical context found"* for
COVID/RSV rather than citing an unrelated flu report as evidence.

### 2. ccloud CLI

Used for cluster lifecycle and operational visibility:

```bash
ccloud cluster list
ccloud cluster describe <cluster-id>
ccloud auditlog list --cluster <cluster-id>
ccloud backup list --cluster <cluster-id>
```

The application's own `audit_log` table is a separate, complementary layer — it records
every read and write *the agent itself* performs. The ccloud audit log is the cluster's own
trail. Both exist deliberately.

**On the Cloud Managed MCP Server:** deliberately not used. It's designed for connecting
developer tools to a cluster, not as a runtime API for a deployed agent's reasoning loop.

---

## AWS services used

- **AWS App Runner** — hosts the containerized FastAPI app and dashboard; serves the public
  demo URL. 0.5 vCPU / 1 GB (measured peak usage: 426 MB).
- **AWS Lambda** — runs the 4-hourly numeric ingestion (`ingest.py`) as a lightweight zip
  package.
- **Amazon EventBridge** — Scheduler drives the 4-hour Lambda ingest; a Rule + API
  destination drives weekly FluView report seeding against App Runner, authenticated with a
  shared-secret header.

Ingestion and report-seeding are split deliberately: numeric ingest has no ML dependencies
and fits a zip Lambda, while report seeding needs the embedding model and therefore runs in
the already-deployed container.

---

## Data quality and calibration

The analytics were validated against real data rather than assumed correct. What that
surfaced:

- **Minimum baseline window.** Z-scores are only emitted with at least 8 historical
  observations. Cold-start windows previously produced extreme scores (z ≈ −6) against a
  near-empty baseline — mathematically valid, operationally meaningless.
- **Standard deviation floor.** Quiet-season baselines have near-zero variance, which turns
  trivial fluctuations into large z-scores. The denominator is floored.
- **Directional severity.** Severity is computed deterministically in Python from the
  z-score and carries direction. Rising activity drives watch/alert; declining activity is
  reported as declining, not treated as an equivalent outbreak signal merely because `|z|`
  is large. The LLM explains the computed severity rather than choosing it.
- **Freshness guard (42 days).** New York's ILINet feed stopped reporting on 22 Sep 2025.
  Without a freshness check the agent generated a fully-audited, mathematically-correct
  "current" alert from an 11-month-old observation. Stale signals are now excluded from
  reasoning and surfaced as data gaps.
- **A real multi-state reporting gap.** Connecticut, New York, Oregon and Utah all stopped
  ILINet reporting at the same epiweek (202539). Discovered by the coverage check, not
  assumed — and the reason those states were excluded from the region list.
- **Known gaps, shown honestly.** Texas is not a RESP-NET catchment state and carries only a
  flu signal. Both it and New York's stale feed are labeled in the dashboard rather than
  rendering as misleading empty charts.

---

## API

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness check |
| `GET /regions` | Live region list |
| `GET /memory/summary` | Row counts and date coverage of the memory layer |
| `GET /signals/{signal_type}/{region}` | Recent time series |
| `GET /rankings` | All region/signal combos ranked, rising first |
| `GET /reports/search?q=` | Semantic search over CDC narratives (vector search) |
| `GET /regions/{region}/closest-match` | Cross-region pattern matching |
| `GET /alerts` | Recent alerts |
| `POST /alerts/{alert_id}/transition` | Move an alert through its lifecycle |
| `GET /alerts/{alert_id}/history` | State-transition history |
| `GET /audit` | Memory access log |
| `POST /trigger/ingest` | Manual ingest cycle (authenticated) |
| `POST /trigger/agent/{signal_type}/{region}` | Manual agent cycle, returns full trace (authenticated) |
| `POST /trigger/seed` | Manual report seeding (authenticated) |
| `GET /dashboard` | Web dashboard |

Trigger endpoints require an `X-Trigger-Secret` header matching `TRIGGER_SECRET`.

---

## Running it

### 1. CockroachDB

Create a free cluster at [cockroachlabs.cloud](https://cockroachlabs.cloud), then:

```bash
psql "$DATABASE_URL" -f app/schema.sql
```

### 2. Groq

Free API key at [console.groq.com](https://console.groq.com).

### 3. Environment

```bash
cp .env.example .env
```

```
DATABASE_URL=postgresql://...
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
EMBEDDING_MODEL_NAME=BAAI/bge-small-en-v1.5
TRIGGER_SECRET=<random string>
```

### 4. Run

```bash
pip install -r requirements.txt
python -m app.ingest           # fetch real CDC data
python -m app.seed_reports     # scrape + embed FluView narratives
python -m app.agent            # run one reasoning cycle
uvicorn app.main:app --reload  # http://localhost:8000/dashboard
```

### Local stack with Docker

```bash
docker compose up
```

Runs the app alongside a local single-node CockroachDB — full stack, no cloud account
needed.

### Tests

```bash
python -m pytest tests/ -v
```

9 tests: relevance-filter behavior and query construction (no DB required), plus an
integration test that re-derives the empirical distance separation against the live cluster.

---

## Deploying

```bash
# Build for x86_64 (App Runner) even on an ARM Mac
docker build --platform linux/amd64 -t outbreak-intelligence .

aws ecr create-repository --repository-name outbreak-intelligence --region <REGION>
aws ecr get-login-password --region <REGION> \
  | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com
docker tag outbreak-intelligence:latest \
  <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/outbreak-intelligence:latest
docker push <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/outbreak-intelligence:latest
```

Then create an App Runner service from that image: port 8080, 0.5 vCPU / 1 GB, health check
`/health`, and the environment variables above.

Full step-by-step console instructions are in `DEPLOY_PLAN.md`.

---

## License

MIT
