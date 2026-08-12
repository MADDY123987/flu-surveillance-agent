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
   agent.py — single agent, 5-step loop (hand-built, calls Bedrock via boto3
   directly, NOT the managed Bedrock Agents product):
     1. fetch_recent_signals()       <- CockroachDB
     2. compute_features()            -> z-score, week-over-week % change (real
                                          Python math, not left to the LLM)
     3. search_similar_reports()      <- CockroachDB vector search over FluView text
     4. reason_and_decide()           -> Bedrock (Titan embed + Claude reason)
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
- **Amazon Bedrock** — Titan Embeddings (`amazon.titan-embed-text-v2:0`) for
  vectorizing text, and a Claude model for reasoning/decision steps, called
  directly via boto3's `invoke_model`

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
    embedding VECTOR(1024),
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
- `GET /signals/{signal_type}/{region}` — recent time series for one signal/region
- `GET /rankings` — every region/signal combo ranked by |z-score|, most anomalous
  first — the "top emerging risks" view
- `GET /alerts` — recent alerts
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

**Already built and compiling cleanly:**
- Project structure, `requirements.txt`, `.env.example`
- `app/schema.sql` — full schema as above
- `app/config.py` — env var loading
- `app/db.py` — all CockroachDB read/write functions, including audit logging on
  every read/write, and alert state transition logic
- `app/features.py` — z-score and week-over-week % change computation
- `app/ingest.py` — real, working ILINet fetch (`fetch_cdc_data`); RESP-NET fetch
  scaffolded but needs the real resource ID filled in
  (`RESPNET_RESOURCE_ID = "REPLACE_ME"`)
- `app/agent.py` — full 5-step agent loop, calls Bedrock directly via boto3
- `app/main.py` — all API endpoints listed above, including `/rankings`
- `lambda_handler.py` — Lambda entrypoint for scheduled ingestion

**Not yet built:**
- RESP-NET real resource ID + field name confirmation
- FluView narrative text scraper (HTML fetch + text extraction + embedding)
- CockroachDB cluster (needs to be created in the Cloud Console)
- AWS Bedrock model access (needs to be enabled in the AWS console — do this
  early, approval can lag)
- Lambda deployment + EventBridge schedule (local code exists, not yet deployed)
- Dashboard / frontend
- Demo video
- Seed script for initial historical report embeddings (needed before vector
  search has anything to find)

---

## 10. Setup steps (for whoever picks this up)

1. Create a free CockroachDB Cloud cluster (cockroachlabs.cloud), AWS as provider.
   Run `app/schema.sql` against it.
2. In AWS, enable Bedrock model access for Titan Embeddings + a Claude model.
   Set up IAM credentials with `bedrock:InvokeModel`.
3. Copy `.env.example` to `.env`, fill in `DATABASE_URL` and AWS config.
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
