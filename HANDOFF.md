# Outbreak Intelligence Agent — Full Project Handoff Document

This document is the single source of truth for this project. If you're a future
Claude session (or the developer, re-reading this later), read this fully before
suggesting any scope changes — the scope below was arrived at after extensive
back-and-forth and is intentionally locked.

---

## 1. The Hackathon

**Name:** CockroachDB × AWS Hackathon — Build with Agentic Memory
**Host:** Cockroach Labs, managed via Devpost
**Deadline:** 19 Aug 2026 @ 2:30am GMT+5:30
**Prizes:** $8,750 total — 1st $5,000, 2nd $2,500, 3rd $1,250
**Format:** Solo developer, ~10 days of build time

### Hard requirements
- Build an agentic application using CockroachDB as the persistent memory layer, deployed on AWS
- Use **at least 2** of: CockroachDB Cloud Managed MCP Server, Distributed Vector
  Indexing, ccloud CLI, Agent Skills Repo
- Use **at least 1** AWS service (Bedrock, Lambda, ECS/EKS, S3, SageMaker, Bedrock
  Agents, or other)
- Public open-source GitHub repo with a visible MIT/Apache 2.0 license in the About
  section
- A functional demo app URL
- A video under 3 minutes, public on YouTube/Vimeo, showing the CockroachDB memory
  layer at work
- State which CockroachDB tools and AWS services were used and how
- Optional: architecture diagram; optional: feedback on CockroachDB's AI tooling

### Judging criteria (five, roughly equal weight)
1. **Agentic Memory Design** — is memory used for more than toy queries?
2. **Technical Implementation** — quality of the tool integrations
3. **Real-World Impact** — is the use case meaningful, not just impressive?
4. **Production Readiness** — security, observability, resilience
5. **Creativity & Originality** — genuine insight into agentic systems

---

## 2. The Project

**Pitch:** A single agent that continuously ingests real CDC respiratory
surveillance data, remembers it durably and semantically in CockroachDB, and
reasons over that memory to rank and explain emerging outbreak risk across the US.

**Explicitly NOT:** a pandemic predictor, a patient-data / clinical records system
(no real patient data is legally obtainable for a hackathon — this was an early
idea, correctly abandoned), a multi-country system, a multi-agent distributed
system (deliberately simplified to one agent with rich memory instead).

---

## 3. Decision history — what was considered and rejected, and why

Read this section to avoid re-litigating settled decisions.

- **Clinical Context Agent (real patient records)** — rejected immediately.
  Real hospital patient-data APIs are not obtainable in a hackathon timeframe;
  HIPAA and hospital credentialing make this a non-starter. Pivoted to public,
  aggregate health surveillance data instead (no privacy issue, real APIs exist).
- **Multi-country (US + India + China)** — rejected. India's health data (IDSP)
  is mostly PDF bulletins, not a clean API. China has no meaningful open public
  health API. Only common thread would be WHO FluNet, which is lower-granularity
  and untested — not worth the integration risk in the time available.
- **Managed AWS Bedrock Agents product** — rejected in favor of a hand-built agent
  loop calling Bedrock directly via boto3. Reasoning: full visibility into each
  step for the demo video, lower integration/debugging risk, more learning value.
- **CockroachDB MCP Server as the 2nd required tool** — rejected in favor of
  ccloud CLI. Reasoning: MCP Server is positioned by CockroachDB as a way for dev
  tools (Claude Code, Cursor, VS Code) to connect to a cluster, not as a runtime
  API for a deployed agent's own reasoning loop. Using it that way stretches its
  intended purpose. ccloud CLI (cluster status, audit logs, backups) is lower risk
  and cleanly demoable, and it covers a different judging criterion (Production
  Readiness) than vector indexing does (Agentic Memory Design) — deliberate
  coverage of two criteria with two tools.
- **5+ signals (ED visits, mortality, clinical lab positivity, pediatric deaths,
  LTCF data)** — rejected. Each would be a new, unverified integration. Mortality
  specifically has too much reporting lag to be useful for an "emerging risk"
  agent. Kept to 2 numeric signals from sources already proven to work.
- **Google Trends symptom search data** — rejected. No official API exists;
  unofficial wrappers are unreliable and get rate-limited. Also very noisy
  (allergies, unrelated illness, and news coverage itself all drive search
  volume), which would hurt signal-to-noise rather than help it.
- **News/bulletin text as a signal** — rejected. Risk of polluting the vector
  memory with irrelevant articles that happen to mention a disease name, which
  would undermine the one feature (real semantic search) this project needs to
  get right.
- **All 50 states from day one** — rejected as a starting scope, but NOT rejected
  entirely. Because CDC APIs already accept any state as a parameter, widening
  from 4 regions to 50 states is low-risk (no new integration, just a longer
  region list) and is kept as a Day 7 stretch goal, attempted only if the 4-region
  core is fully working first.
- **True multi-agent architecture** (separate deployed services, agent-to-agent
  messaging) — rejected. Would add real infrastructure risk for a solo 10-day
  build. Kept the existing single-agent 5-step loop, which already functionally
  separates concerns (fetch / features / search / reason / act) without needing
  new infrastructure.
- **Raw numeric-only vector embeddings** ("California flu rate is 1.6") —
  identified as a real flaw partway through: embedding bare numbers gives
  semantic search almost nothing meaningful to retrieve. Fixed by finding CDC's
  actual weekly narrative text reports (FluView) as a real text source instead.

**Pattern to watch for:** across this project's planning, the same "should I
expand scope" question was reopened roughly six times with slightly different
framing each time (more diseases, more countries, more signals, different
domains entirely). Every reopening cost time without improving the plan. If this
happens again, the answer is: re-read this document, don't re-derive it.

---

## 4. Final locked scope

- **Regions:** US National + California + Texas + New York (all 50 states is an
  optional Day 7 stretch goal only, see day plan)
- **Data sources (3):**
  1. **CDC ILINet** via the CMU Delphi Epidata API — flu-like illness rate.
     Endpoint: `https://api.delphi.cmu.edu/epidata/fluview/`
     Example: `?regions=ca&epiweeks=202620-202632`
     No API key required. Confirmed working with real data during development
     (see verified sample response in section 8).
  2. **CDC RESP-NET** via data.cdc.gov (Socrata) — COVID-19 + RSV hospitalization
     rates. Dataset: "Rates of Laboratory-Confirmed RSV, COVID-19, and Flu
     Hospitalizations from RESP-NET." **Status: resource ID and exact field names
     not yet confirmed** — go to data.cdc.gov, search "RESP-NET," open the
     dataset, click the "API" button to get the real resource ID (format
     `xxxx-xxxx`) and confirm field names (surveillance network, region, week
     ending date, rate).
  3. **CDC FluView weekly narrative reports** — real written analysis from CDC's
     Influenza Division (not just numbers). URL pattern:
     `https://www.cdc.gov/fluview/surveillance/{year}-week-{NN}.html`
     **Status: URL pattern found, scraper not yet built.** This is not a JSON
     API — requires fetching the HTML page and extracting the narrative text
     (e.g. via BeautifulSoup). Verify the exact week-numbering convention against
     a live page before building. This text is what gets embedded for real
     vector/semantic search — without it, vector search has nothing meaningful to
     retrieve.

---

## 5. Architecture

```
3 CDC sources (ILINet, RESP-NET, FluView text)
        |
   EventBridge (4h schedule) -> Lambda -> ingest.py (fetch, clean, store)
        |
        v
   CockroachDB — four memory types:
     - health_signals            (time series, per region/signal/date)
     - health_reports + vector    (FluView text + embeddings, semantic search)
     - alerts + alert_state_transitions  (full lifecycle: new -> acknowledged -> resolved)
     - audit_log                 (every agent read/write)
        ^
        |
   agent.py — single agent, 5-step loop (hand-built, calls Groq directly via its
   SDK, NOT the managed Bedrock Agents product):
     1. fetch_recent_signals()       <- CockroachDB
     2. compute_features()            -> z-score, week-over-week % change (real
                                          Python math, not left to the LLM)
     3. search_similar_reports()      <- CockroachDB vector search over FluView text
     4. reason_and_decide()           -> app/embeddings.py (local BAAI/bge-small-en-v1.5
                                          embed) + Groq (llama-3.3-70b-versatile reason)
     5. insert_alert() / transition_alert_state()  -> CockroachDB
        ^
        |
   main.py (FastAPI) — exposes everything, plus manual /trigger endpoints so you
   don't have to wait 4 real hours to demo
        ^
        |
   Dashboard (not yet built) — shows trends, rankings, alerts, audit trail
```

### CockroachDB tools used (2 required, both deliberate choices)
1. **Distributed Vector Indexing** — `health_reports.embedding` column, vector
   index, searched for semantic similarity — satisfies "Agentic Memory Design"
2. **ccloud CLI** — cluster status, audit log export, backup checks, run live in
   the demo video — satisfies "Production Readiness." Example commands (verify
   exact current syntax with `ccloud --help`):
   ```
   ccloud cluster list
   ccloud cluster describe <cluster-id>
   ccloud auditlog list --cluster <cluster-id>
   ccloud backup list --cluster <cluster-id>
   ```

### AWS services used
- **AWS Lambda** — runs the ingestion job on a schedule
- **Amazon EventBridge Scheduler** — triggers Lambda every 4 hours (`rate(4 hours)`)

### LLM / embedding provider
- **Local embeddings** — `BAAI/bge-small-en-v1.5` via `sentence-transformers`
  (`app/embeddings.py`), run in-process, no cloud account needed. Replaces
  Bedrock Titan Embeddings (see migration note below).
- **Groq** — `llama-3.3-70b-versatile` via the official `groq` SDK, called
  directly in `app/agent.py`'s `reason_and_decide()`. Replaces Bedrock's Claude
  model for the reasoning/decision step.

---

## 6. Database schema (CockroachDB)

```sql
-- Time series of raw signal readings
CREATE TABLE health_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source STRING NOT NULL,
    signal_type STRING NOT NULL,
    region STRING NOT NULL,
    observed_date DATE NOT NULL,
    value FLOAT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, signal_type, region, observed_date)
);

-- Text reports, embedded for semantic search
CREATE TABLE health_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source STRING NOT NULL,
    title STRING NOT NULL,
    content STRING NOT NULL,
    region STRING,
    published_date DATE,
    embedding VECTOR(384),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE VECTOR INDEX idx_reports_embedding ON health_reports (embedding);

-- Alerts with full lifecycle
CREATE TABLE alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_type STRING NOT NULL,
    region STRING NOT NULL,
    severity STRING NOT NULL,
    message STRING NOT NULL,
    state STRING NOT NULL DEFAULT 'new',
    agent_reasoning JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE alert_state_transitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id UUID NOT NULL REFERENCES alerts(id),
    from_state STRING NOT NULL,
    to_state STRING NOT NULL,
    reason STRING,
    transitioned_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Every agent read/write
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor STRING NOT NULL,
    action STRING NOT NULL,
    resource STRING NOT NULL,
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

(Full file: `app/schema.sql` in the project)

---

## 7. API surface (FastAPI, `app/main.py`)

- `GET /health` — liveness check
- `GET /` — redirects to `/dashboard/`
- `GET /dashboard/` — static dashboard (`app/static/index.html`)
- `GET /signals/{signal_type}/{region}` — recent time series for one signal/region
- `GET /rankings` — every region/signal combo ranked by |z-score|, most anomalous
  first — the "top emerging risks" view
- `GET /reports/search?q=<text>` — semantic search over `health_reports` via
  CockroachDB vector index; returns top-k matches with distance/similarity
- `GET /regions/{region}/closest-match?signal_type=<type>` — cross-region pattern
  match: closest historical snapshot among the other regions, by embedding
  distance (on-demand, not part of periodic refresh — see section 12)
- `GET /alerts` — recent alerts, including `state` and the full `agent_reasoning`
  trace
- `POST /alerts/{alert_id}/transition` — move an alert through its lifecycle
- `GET /alerts/{alert_id}/history` — full state-transition history for one alert
- `GET /audit` — recent audit log entries
- `POST /trigger/ingest` — manually run one ingest cycle (for demoing without
  waiting 4 hours)
- `POST /trigger/agent/{signal_type}/{region}` — manually run one agent reasoning
  cycle, returns the full step-by-step trace

---

## 8. Verified working example (real data, captured during development)

Confirmed real response from the Delphi Epidata API (California, weeks 202620-202632):
```
curl "https://api.delphi.cmu.edu/epidata/fluview/?regions=ca&epiweeks=202620-202632"
```
Returns real weekly `wili`/`ili` (weighted/unweighted influenza-like-illness
percentage) values along with `num_patients`, `num_providers`, `epiweek`. This
confirms the ILINet ingestion path works end to end against the live API.

---

## 9. Current build status

_Updated 2026-08-13 after (a) a pass through setup steps 3-8, 11 that didn't need
CockroachDB Cloud / AWS console / GitHub access, then (b) standing up a **local**
CockroachDB via Docker (not Cloud) to actually run the ingest job and API end-to-end
against real data. No scope was changed; section 3's decision history is untouched._

**Already built and compiling cleanly:**
- Project structure, `requirements.txt` (now includes `sqlalchemy-cockroachdb` and
  `beautifulsoup4`, see fixes below), `.env.example` (was referenced but missing —
  created; documents the `cockroachdb+psycopg://` URL scheme requirement)
- `app/schema.sql` — full schema as above
- `app/config.py` — env var loading; `TARGET_REGIONS` default now covers all 4 locked
  regions (was just "California")
- `app/db.py` — all CockroachDB read/write functions, including audit logging on
  every read/write, and alert state transition logic
- `app/features.py` — z-score and week-over-week % change computation
- `app/ingest.py` — real, working ILINet fetch (`fetch_cdc_data`) for all 4 regions
  (`nat`/`ca`/`tx`/`ny`, all confirmed live); RESP-NET fetch fully wired to the real
  resource ID (`kvib-3txy`) and confirmed field names
- `app/fluview.py` — **new.** FluView weekly narrative scraper, confirmed working
  against the live site
- `app/seed_reports.py` — **new.** Seeds `health_reports` from recent FluView reports
  + Bedrock embeddings (idempotent re-runs)
- `app/agent.py` — full 5-step agent loop, calls Bedrock directly via boto3
- `app/main.py` — all API endpoints listed above, including `/rankings`, plus a
  `/dashboard` static mount and `/` redirect
- `app/static/index.html` — **new.** Dashboard: stat tiles, rankings bar chart, signal
  trend line chart, alerts table (with ack/resolve actions), audit trail
- `lambda_handler.py` — Lambda entrypoint for scheduled ingestion

**Bugs found and fixed during this pass (not scope changes — the code didn't match
its own documented design):**
- `app/agent.py` — `run_agent_cycle()` never called `compute_features()` and called
  `reason_and_decide()` with one fewer argument than its signature. The agent would
  have crashed on first real run. Fixed: features are now computed and passed through.
- `app/db.py` — `insert_report()` / `search_similar_reports()` passed a raw Python
  list as the `VECTOR` bind parameter; CockroachDB's VECTOR type requires a string
  literal (`'[1.0,2.0,...]'`). Fixed with a `_vector_literal()` helper.
- `app/db.py` — `log_audit()` / `insert_alert()` passed a raw Python `dict` as a
  `JSONB` bind parameter; psycopg3 can't auto-adapt that. Found by actually running
  `app/ingest.py` against a real DB (every ingested row logs an audit entry, so this
  broke on the very first insert). Fixed with `json.dumps(...)` +
  `CAST(:param AS JSONB)` — note plain `:param::JSONB` doesn't work either, since
  SQLAlchemy's `text()` bind-param parser trips on a `::` immediately following a
  named param.
- `requirements.txt` was missing `sqlalchemy-cockroachdb` (needed for the
  `cockroachdb://` dialect) and `beautifulsoup4` (needed for the FluView scraper).

**Data-availability gaps discovered (not bugs — real constraints of the sources,
found by actually running the ingest job against live APIs):**
- RESP-NET's catchment is a subset of states. Texas is **not** a COVID-NET/RSV-NET
  site — of the 4 locked regions, only US/California/New York have RESP-NET data;
  Texas will only ever have the ILINet flu signal. Handled gracefully in
  `fetch_respnet_data()` (returns `[]` for unmapped regions rather than erroring).
- As of 2026-08-13, Delphi/ILINet's most recent data point for New York is epiweek
  202539 (~Sept 2025) — New York currently has **no recent flu_like_illness signal**
  via ILINet (last confirmed real ingest run: 0 flu rows for NY, vs 6 each for
  US/California/Texas). New York's RESP-NET (COVID/RSV) data is fine and current.
  This may resolve on its own as CDC catches up reporting, or may not before the
  deadline — worth knowing before recording the demo video so New York isn't shown
  as the "everything's flat" example. `app/ingest.py` already handles it gracefully
  (logs "no results", doesn't crash, doesn't drop other regions).

**Verified against a real local CockroachDB (Docker, single-node, NOT Cloud — see
new "Local development" note in section 10):**
- `app/schema.sql` applies cleanly, all 5 tables + the vector index created
- `python -m app.ingest` run for real against live Delphi + RESP-NET APIs: 90 rows
  stored, 90 matching audit_log rows (confirms audit-on-every-write is real, not
  just documented)
- `GET /rankings`, `GET /signals/{signal}/{region}`, `GET /audit`, `GET /alerts`,
  `GET /dashboard/` all confirmed returning real correctly-shaped data through
  `uvicorn` — the dashboard's fetch calls match the live API response shapes exactly
- Still unverified: `app/agent.py` and `app/seed_reports.py` (both need real AWS
  Bedrock access), and the dashboard in an actual browser (no browser tool available
  this session — only curl-level verification so far)

**Not yet built / needs an external account (see section 10 for exact steps):**
- CockroachDB **Cloud** cluster (a local Docker instance now exists for dev — see
  section 10 — but the Cloud cluster is still required for deployment/submission)
- AWS Bedrock model access (needs to be enabled in the AWS console)
- Running `app/seed_reports.py` and `python -m app.agent` for real — both need
  Bedrock; code is written and import-clean but genuinely untested end-to-end
- Viewing `app/static/index.html` in an actual browser against real data (verified
  it serves correctly and degrades gracefully with no DB; a live look with real
  rankings/alerts data is still worth doing once data exists)
- ccloud CLI install/auth against the real cluster
- Lambda deployment + EventBridge schedule (local code exists, not yet deployed)
- Demo video
- Push to the public GitHub repo, Devpost submission

---

## 10. Setup steps (for whoever picks this up)

### Local development (no CockroachDB Cloud / AWS account needed)

Everything except real Bedrock calls (embeddings + agent reasoning) can be developed
and tested against a **local, single-node CockroachDB in Docker** — not a substitute
for the Cloud cluster required at submission time, but lets you iterate on schema/
ingest/API/dashboard work immediately:

```
docker run -d --name crdb-local -p 26257:26257 -p 8080:8080 \
  cockroachdb/cockroach:latest start-single-node --insecure --store=type=mem,size=0.25
docker exec crdb-local ./cockroach sql --insecure -e "CREATE DATABASE IF NOT EXISTS outbreak;"
docker cp app/schema.sql crdb-local:/schema.sql
docker exec crdb-local ./cockroach sql --insecure --database=outbreak -f /schema.sql
```

Then set `DATABASE_URL=cockroachdb+psycopg://root@localhost:26257/outbreak?sslmode=disable`
in `.env` (already done in the current `.env` in this checkout). `python -m app.ingest`
and the FastAPI app/dashboard all work fully against this — confirmed 2026-08-13 (see
section 9). Swap `DATABASE_URL` for the real Cloud connection string before deploying.

1. Create a free CockroachDB Cloud cluster (cockroachlabs.cloud), AWS as provider.
   Run `app/schema.sql` against it.
2. Create a free Groq API key at console.groq.com. Local embeddings
   (`sentence-transformers`) need no cloud account at all.
3. Copy `.env.example` to `.env`, fill in `DATABASE_URL` and `GROQ_API_KEY`.
4. `pip install -r requirements.txt`
5. Confirm the RESP-NET resource ID (see section 4, source #2) and fill it into
   `app/ingest.py`.
6. Build the FluView scraper (see section 4, source #3).
7. Run locally: `uvicorn app.main:app --reload`
8. Test manually: `python -m app.ingest`, then `python -m app.agent`
9. Install/configure the ccloud CLI, test cluster/audit/backup commands against
   the real cluster
10. Deploy `ingest.py` + `lambda_handler.py` to Lambda, set an EventBridge rule
    on a `rate(4 hours)` schedule
11. Build the dashboard against the FastAPI endpoints
12. Record the demo video, finish the README, push to the public repo (MIT/Apache
    2.0 license visible), submit on Devpost before 19 Aug 2026, 2:30am GMT+5:30

---

## 11. Repo name

`flu-surveillance-agent` (created on GitHub, MIT license, public) — chosen over
more generic names to stay honest about current scope (flu is the most complete
signal; COVID/RSV/text are in progress). Description used: an agent that ingests
CDC flu surveillance data, remembers historical patterns in CockroachDB, and
generates auditable alerts using Bedrock reasoning.

---

## 12. Frontend & feature additions

_Completed 2026-08-13, implementing `NEXT_STEPS.md` in order. Everything here is
inside the locked scope from section 3 — no new data sources, no new regions, no
new cloud dependencies beyond Bedrock (already required). Nothing in section 3
was reopened._

**`MOCK_BEDROCK` flag (`app/config.py`, `app/agent.py`) — built first since
everything else depended on it:** when `MOCK_BEDROCK=true`, `embed_text()` returns
a deterministic hash-seeded vector and `reason_and_decide()` applies the same
z-score thresholds a human analyst would, instead of calling AWS. This let the
*entire* pipeline — ingest → agent reasoning → vector search → alert storage →
dashboard — be exercised locally and verified against real CockroachDB data,
without AWS credentials. Real Bedrock is required for actual semantic quality;
mock vectors carry no real meaning (documented in code). Confirmed working:
`python -m app.agent` and `python -m app.seed_reports` both ran end-to-end
locally, producing real alerts with real vector-search matches.

**One more real bug found during full-pipeline reruns:** `db.insert_report()` never
called `log_audit()`, unlike every other write function in `db.py` — silently
breaking the project's own stated design ("audit_log: every agent read/write").
`seed_reports.py`'s writes were going completely unaudited except for its own
job-level summary line. Fixed: `insert_report()` now logs a per-row audit entry
(actor `seed_job`), verified by actor-grouped count after a full clean rerun.

**Dashboard polish (section 1 of NEXT_STEPS.md):**
- Data-gap badges: the two known gaps (Texas has no RESP-NET COVID/RSV data; New
  York has no recent ILINet flu data) now show as a labeled amber "data gap"
  note when that region/signal combo is selected in the trend chart, not a bare
  "no data" state.
- `agent_reasoning` is now returned by `GET /alerts` (previously omitted from the
  SELECT) and rendered as an expandable per-alert trace in the dashboard: signal
  history count, computed z-score/WoW change, the embedded situation text, which
  historical report(s) vector search matched (title + published date + distance —
  `app/agent.py`'s trace previously only recorded a match *count*, not which
  reports; fixed so this is actually showable), and the decision. Expanded rows
  survive the dashboard's 30s auto-refresh (tracked in a JS `Set`) so an open
  trace doesn't snap shut mid-demo.
- Alerts table now also shows each alert's lifecycle `state` and only offers
  the Ack/Resolve actions that are valid from that state (previously always
  showed both regardless of current state).
- Loading states added to all dashboard fetch calls (previously only had error
  states).

**Semantic search box (section 2, highest-priority new feature):**
- `GET /reports/search?q=<text>` (`app/main.py`) — embeds the query, runs a real
  CockroachDB vector search over `health_reports`, returns top-k matches with
  `distance` (raw L2 `<->` distance) and `similarity_pct` (a display-only
  monotonic transform, not a calibrated percentage — documented as such in code).
  `db.search_similar_reports()` now also returns `distance` and takes an `actor`
  param so dashboard-triggered searches log as `dashboard_search` in the audit
  trail, distinct from the agent's own internal searches.
- Dashboard: a full-width search box at the top of the page, wired to the new
  endpoint, showing title/date/similarity/snippet per result.

**Cross-region pattern match (section 3, optional stretch — implemented since
Titan embedding calls are inexpensive, not the cost concern originally assumed):**
- `GET /regions/{region}/closest-match?signal_type=<type>` (`app/patterns.py`,
  new file) — compares a region's current signal snapshot against a rolling
  window of every *other* region's recent snapshots (embedding each on the fly,
  no new table), returns the closest match by embedding distance. On-demand only
  (a dashboard button, not part of the periodic refresh) since it makes several
  Bedrock calls per request. Correctly returns `closest_match: null` for regions
  with a known data gap rather than erroring (verified: Texas/COVID and
  New York/flu both return null; Texas/flu correctly found a real match).

**Verification done without a real cluster/AWS, using the local Docker
CockroachDB from section 10:**
- Full pipeline re-run end-to-end with `MOCK_BEDROCK=true`: ingest → agent →
  alerts → dashboard, all against real CockroachDB data
- Every new/changed endpoint hit directly and confirmed 200 with correctly
  shaped data: `/reports/search`, `/regions/{region}/closest-match`, updated
  `/alerts` (now includes `state` + `agent_reasoning`)
- `app/static/index.html` statically verified: JS syntax check, HTML tag-balance
  check, and a cross-check that every `getElementById` call resolves to a
  declared element — all clean
- **Not verified:** an actual browser render. No browser tool was available this
  session (declined earlier in the conversation). Chart rendering, layout at
  narrow widths, and interaction polish (hover tooltips, expand/collapse
  animation) should still get one real look in a browser before the demo
  recording — the static checks above catch structural bugs, not visual ones.



# Migration: AWS Bedrock -> Groq + local embeddings

Scope: ONLY the LLM/embedding provider changes. Do not touch anything else —
no S3, no /upload or /chat endpoints, no Vercel frontend, no schema tables
beyond the vector dimension fix below. Everything in HANDOFF.md section 3
(locked scope) and section 4 (regions/data sources) stays exactly as-is. This
was confirmed explicitly: "only we are shifting from aws bedrock to groq,
that's it."

Why this is safe to do: it actually reduces risk. Bedrock model access was
the single biggest schedule risk (approval can lag days). Groq's API key is
instant, and local embeddings need no cloud account at all. The MOCK_BEDROCK
flag can be removed entirely once this is done — nothing left needs mocking,
since neither Groq nor local embeddings require waiting on approval.

## 1. requirements.txt

- Remove `boto3` if nothing else in the app calls AWS APIs directly (Lambda
  itself doesn't need boto3 to be invoked — only code that calls S3/Bedrock/etc.
  needs it as a dependency). Check ingest.py / agent.py for other boto3 uses
  before removing.
- Add `groq` (official Groq Python SDK)
- Add `sentence-transformers` (for BAAI/bge-small-en-v1.5)

Note for later: sentence-transformers pulls in torch, which is large. This is
fine for local dev and for the FastAPI app process. It becomes relevant again
at Lambda deployment time (see note at the bottom) — not a concern today.

## 2. app/config.py

- Remove: BEDROCK_REGION, Bedrock model ID(s), MOCK_BEDROCK
- Add:
  - `GROQ_API_KEY` (from env, no default — fail loudly if missing)
  - `GROQ_MODEL` (default `"llama-3.3-70b-versatile"`)
  - `EMBEDDING_MODEL_NAME` (default `"BAAI/bge-small-en-v1.5"`)

## 3. New file: app/embeddings.py

Single shared function so the model is loaded once (singleton), not reloaded
on every call — this matters for the FastAPI process and for seed_reports.py
performance.

```python
from sentence_transformers import SentenceTransformer
from app.config import EMBEDDING_MODEL_NAME

_model = None

def get_embedding_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model

def embed_text(text: str) -> list[float]:
    model = get_embedding_model()
    return model.encode(text, normalize_embeddings=True).tolist()
```

Replace every place that currently calls Bedrock's Titan embed (in
seed_reports.py, ingest.py / fluview.py if it embeds at insert time, and
wherever search_similar_reports() builds a query embedding in agent.py) with
`embed_text(...)` from this module.

## 4. app/agent.py — reason_and_decide()

Replace the boto3 `bedrock-runtime.invoke_model(...)` call with:

```python
from groq import Groq
from app.config import GROQ_API_KEY, GROQ_MODEL

client = Groq(api_key=GROQ_API_KEY)

def reason_and_decide(signal_context, similar_reports, features):
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": "<same system prompt as before>"},
            {"role": "user", "content": "<same prompt construction as before, using signal_context / similar_reports / features>"},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content
```

Keep the existing prompt construction and existing return-value handling
(whatever agent.py currently does with the model's output — e.g. parsing
JSON, deciding severity, etc.) — only the client/call changes, not the logic
around it.

## 5. app/schema.sql

```sql
embedding VECTOR(1024)   -- Titan dimension, old
```
becomes
```sql
embedding VECTOR(384)    -- BAAI/bge-small-en-v1.5 dimension
```

Since this is still local-only (no CockroachDB Cloud cluster created yet),
just drop and recreate `health_reports` (and its vector index) against the
local Docker instance — no real data to preserve.

## 6. .env.example

- Remove Bedrock-specific vars if AWS creds aren't needed for anything else
  right now (Lambda/EventBridge deployment will need AWS creds again later,
  but that's a separate, later step — don't remove AWS entirely from the
  project, just from the LLM/embedding path)
- Add `GROQ_API_KEY=` (get a free key at console.groq.com)

## 7. HANDOFF.md updates

- Section 5 (architecture): reasoning step now calls Groq directly, not
  Bedrock; embeddings are generated locally via BAAI/bge-small-en-v1.5, not
  Titan.
- Section 10 (setup steps): remove "enable AWS Bedrock model access" — replace
  with "create a free Groq API key at console.groq.com."
- AWS service requirement (hackathon needs at least 1): still satisfied via
  Lambda + EventBridge for scheduled ingestion — Bedrock was never the only
  AWS service in the plan, so dropping it doesn't put you below the
  requirement.
- Note explicitly in a new subsection that MOCK_BEDROCK was removed and why
  (no longer needed — Groq + local embeddings need no cloud approval).

## 8. Verify

Recreate the local schema, rerun `seed_reports.py`, `ingest.py`, and
`agent.py` end to end against the local Docker CockroachDB — this is now a
REAL run, not a mock, since neither Groq nor local embeddings need mocking.
Confirm the dashboard, semantic search, and cross-region match still work
with 384-dim vectors.

## 9. MOCK_BEDROCK removed

The `MOCK_BEDROCK` flag (`app/config.py`, previously used throughout
`app/agent.py`) has been deleted entirely, along with its mock embedding and
mock reasoning code paths. It existed solely to let the pipeline be exercised
without AWS Bedrock model-access approval, which could lag days. Neither Groq
(instant API key) nor local `sentence-transformers` embeddings (no cloud
account at all) have that approval-lag problem, so there is nothing left to
mock — every code path now makes a real call.

---

**Heads-up for later, not now:** when you get to deploying the ingestion
Lambda (HANDOFF.md section 10, step 10), if `ingest.py`/`fluview.py` generates
embeddings inline (rather than only at seed time), the Lambda package will
need to include `sentence-transformers` + `torch`, which likely exceeds a
plain zip-based Lambda's size limit. At that point you'll probably want a
container-image Lambda instead of a zip package. Not a blocker today — just
don't be surprised by it during the deploy step.