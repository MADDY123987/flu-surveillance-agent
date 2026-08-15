# Flu Surveillance Agent

An agent that continuously ingests real CDC respiratory surveillance data, remembers it
durably and semantically in CockroachDB, and reasons over that memory to rank and explain
emerging outbreak risk across US regions.

Built for the **CockroachDB × AWS Hackathon — Build with Agentic Memory**.

**Live demo:** _TODO: add App Runner URL_
**Demo video:** _TODO: add YouTube link_

---

## Why this exists

Respiratory surveillance signals — influenza-like illness rates, COVID and RSV
hospitalization rates, CDC's weekly narrative analysis — are published continuously but
sit in separate systems with no shared memory. Nobody is continuously watching them,
remembering what previous seasons looked like, and distinguishing a meaningful shift from
ordinary week-to-week noise.

This agent does that. The memory layer is the point: without durable history there is no
baseline, and without a baseline there is no way to say whether this week matters.

---

## What it actually does

Every 4 hours it ingests three real CDC sources, stores them in CockroachDB, and runs a
five-step reasoning loop that produces auditable, explained alerts.

**Regions:** US National + California, Texas, New York, Colorado, Georgia, Maryland,
Michigan, Minnesota, New Mexico, Tennessee (11 total — empirically selected; see
HANDOFF.md section 4 for the RESP-NET/ILINet coverage check behind the list)
**Signals:** influenza-like illness (ILINet), COVID-19 and RSV hospitalization rates
(RESP-NET), plus CDC FluView weekly narrative reports

---

## Architecture

```
3 CDC sources
  ├── ILINet (CMU Delphi Epidata API)      -> influenza-like illness rate
  ├── RESP-NET (data.cdc.gov Socrata)      -> COVID-19 + RSV hospitalization rates
  └── FluView weekly narrative reports     -> real written CDC analysis (scraped HTML)
        |
   EventBridge Scheduler (every 4h)
        |
        v
   ingest.py  --fetch / clean / validate-->  CockroachDB
        |                                      ├── health_signals            (time series)
        |                                      ├── health_reports + VECTOR    (narrative text + embeddings)
        └── raw HTML archived to S3            ├── alerts                     (agent decisions)
                                               ├── alert_state_transitions    (full lifecycle)
                                               └── audit_log                  (every agent read/write)
        ^
        |
   agent.py — single agent, 5-step loop:
     1. fetch_recent_signals()      <- CockroachDB
     2. compute_features()          -> z-score + week-over-week % change (real Python math,
                                       not delegated to the LLM)
     3. search_similar_reports()    <- CockroachDB vector search over FluView narratives
     4. reason_and_decide()         -> Groq (llama-3.3-70b-versatile)
     5. insert_alert() / transition_alert_state()  -> CockroachDB
        ^
        |
   main.py (FastAPI) — REST API + dashboard, plus manual trigger endpoints
```

Embeddings are generated **locally** with `BAAI/bge-small-en-v1.5` (384 dimensions) — no
embedding API calls, no per-token cost, and the model is baked into the container image.

---

## CockroachDB tools used (2 required)

### 1. Distributed Vector Indexing

`health_reports.embedding` is a `VECTOR(384)` column with a vector index, holding embedded
CDC FluView narrative reports. It powers two features:

- **Semantic search** (`GET /reports/search?q=...`) — free-text search over historical CDC
  narrative analysis. Querying "flu increasing rapidly" surfaces genuinely elevated-activity
  reports rather than keyword matches.
- **Historical context in reasoning** — step 3 of the agent loop retrieves semantically
  similar past reports and passes them to the LLM as context, so decisions are grounded in
  what previous comparable periods actually looked like.

This is what makes the memory *semantic* rather than just a time-series table.

### 2. ccloud CLI

Used for cluster lifecycle and operational visibility — cluster status, CockroachDB's own
cluster-level audit trail, and backup verification:

```bash
ccloud cluster list
ccloud cluster describe <cluster-id>
ccloud auditlog list --cluster <cluster-id>
ccloud backup list --cluster <cluster-id>
```

Note the application's own `audit_log` table is a separate, complementary layer: it records
every read and write **the agent itself** performs, at the application level. The ccloud
audit log is the cluster's own trail. Both exist deliberately.

**On the Cloud Managed MCP Server:** deliberately not used. It is designed for connecting
developer tools (Claude Code, Cursor, VS Code) to a cluster, not as a runtime API for a
deployed agent's reasoning loop. Using it that way would stretch its intended purpose and
add integration risk without a scoring benefit over ccloud CLI.

---

## AWS services used (1+ required)

- **Amazon S3** — archives the raw FluView HTML for every report the agent ingests, keyed
  by year and week. This is provenance: an auditable record of exactly what text the agent
  read on a given day, linked from `health_reports`.
- **AWS App Runner** — hosts the containerized FastAPI application and serves the public
  demo URL.
- **Amazon EventBridge Scheduler** — drives ingestion on a `rate(4 hours)` schedule via an
  authenticated API destination.

---

## Data quality and calibration

The analytics were validated against real data rather than assumed correct. Some findings
that shaped the implementation:

- **Minimum baseline window.** Z-scores are only emitted when at least 8 historical
  observations exist. Early cold-start windows previously produced extreme scores
  (z ≈ −6) computed against a near-empty baseline — mathematically valid, operationally
  meaningless. These are now represented as insufficient history.
- **Standard deviation floor.** Quiet-season baselines can have near-zero variance, which
  turns epidemiologically trivial fluctuations into large z-scores. The denominator is
  floored to prevent noise amplification.
- **Directional severity.** Severity is computed deterministically in Python from the
  z-score — not left to LLM discretion — and carries direction. Rising activity drives
  watch/alert severity; declining activity is reported as declining rather than being
  treated as an equivalent outbreak signal merely because `|z|` is large. The LLM's role is
  to explain and contextualize the computed severity, not to override it.
- **Known coverage gaps, handled explicitly.** Texas is not a RESP-NET catchment state, so
  it will only ever carry a flu signal. New York currently has no recent ILINet data. Both
  are surfaced in the dashboard as labeled data-gap states rather than rendering as
  misleading empty charts.

---

## API

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness check |
| `GET /signals/{signal_type}/{region}` | Recent time series for one signal/region |
| `GET /rankings` | All region/signal combinations ranked by anomaly magnitude |
| `GET /reports/search?q=` | Semantic search over CDC narrative reports (vector search) |
| `GET /regions/{region}/closest-match` | Cross-region pattern matching |
| `GET /alerts` | Recent alerts |
| `POST /alerts/{alert_id}/transition` | Move an alert through its lifecycle |
| `GET /alerts/{alert_id}/history` | Full state-transition history for one alert |
| `GET /audit` | Recent audit log entries |
| `POST /trigger/ingest` | Run one ingest cycle manually (authenticated) |
| `POST /trigger/agent/{signal_type}/{region}` | Run one agent cycle, returns full trace (authenticated) |
| `GET /dashboard` | Web dashboard |

---

## Setup

### 1. CockroachDB

Create a free cluster at [cockroachlabs.cloud](https://cockroachlabs.cloud), then:

```bash
psql "$DATABASE_URL" -f app/schema.sql
```

### 2. Groq

Get a free API key at [console.groq.com](https://console.groq.com). No approval wait, no
credit card.

### 3. AWS

Create an S3 bucket (block public access enabled) and an IAM user with `s3:PutObject` and
`s3:GetObject` scoped to that bucket only.

### 4. Environment

```bash
cp .env.example .env
```

Fill in:

```
DATABASE_URL=postgresql://...
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
EMBEDDING_MODEL_NAME=BAAI/bge-small-en-v1.5
S3_BUCKET=your-bucket
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
TRIGGER_SECRET=...
```

### 5. Run

```bash
pip install -r requirements.txt
python -m app.ingest          # fetch real CDC data
python -m app.seed_reports    # embed FluView narratives
python -m app.agent           # run one reasoning cycle
uvicorn app.main:app --reload # http://localhost:8000/dashboard
```

### Local development with Docker

```bash
docker compose up
```

Starts the application alongside a local single-node CockroachDB, so the full stack runs
without a cloud cluster.

---

## Deployment

The application is a single container image serving both the API and the dashboard.

1. Build and push the image to ECR.
2. Create an App Runner service from that image (port 8080, ≥2 GB memory — the embedding
   model needs headroom), with the environment variables above and an instance role
   carrying the scoped S3 permissions.
3. Create an EventBridge Scheduler schedule on `rate(4 hours)` targeting an API destination
   pointed at `POST /trigger/ingest`, with the `TRIGGER_SECRET` header attached.

AWS Lambda was evaluated and not used: local embedding inference requires
`sentence-transformers` and `torch`, which exceed the zip-packaged Lambda size limit. Rather
than maintain a second container-image deploy artifact alongside the API container, ingestion
is triggered on the already-deployed service.

---

## License

MIT
