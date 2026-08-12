# Public Health Surveillance Agent

An agent that ingests real public health surveillance data (CDC public feeds) every 4 hours,
stores it as durable memory in CockroachDB, and reasons over that memory with a self-built
agent loop (Bedrock LLM calls, not managed Bedrock Agents) to detect meaningful trend shifts
and generate plain-English alerts.

## Why this exists

Public health signals (flu-like illness rates, wastewater viral levels, etc.) are published
constantly but scattered. Nobody has a system that continuously watches them, remembers
history, and flags when something actually matters vs. normal noise. That's what this agent
does.

## Architecture

```
CDC public data feed
        |
   (every 4h, EventBridge -> Lambda)
        v
  ingest.py  --clean/validate-->  CockroachDB
                                     |-- health_signals   (time series)
                                     |-- health_reports   (text + vector embeddings)
                                     |-- alerts           (agent decisions)
                                     |-- audit_log        (every agent read/write)
        ^
        |
   agent.py (your own loop, not managed Bedrock Agents):
     1. fetch_recent_signals()      -> query CockroachDB
     2. search_historical_context() -> vector search over health_reports
     3. compare_and_reason()        -> Bedrock LLM call w/ both as context
     4. decide_and_act()            -> write alert + audit_log row if warranted
        ^
        |
   main.py (FastAPI) - exposes it all as an API + lets you trigger the loop manually
```

## CockroachDB tools used (need 2+)

1. **Distributed Vector Indexing** - `health_reports.embedding` column, searched for
   semantic similarity to find past reports/advisories like the current situation. This
   is what satisfies "Agentic Memory Design."
2. **ccloud CLI (Agent-Ready)** - used for cluster lifecycle and operational visibility:
   creating/checking the cluster, pulling audit logs, and checking backup status. This is
   what satisfies "Production Readiness" - it's a separate judging criterion from memory
   design, so covering both with distinct tools is deliberate.

   Example commands to run and capture for your demo video (check `ccloud --help` for the
   exact current syntax, since CLI commands can change):
   ```
   ccloud cluster list
   ccloud cluster describe <cluster-id>
   ccloud auditlog list --cluster <cluster-id>
   ccloud backup list --cluster <cluster-id>
   ```

   Note: the app's own `audit_log` table (see `app/db.py`) is a separate, complementary
   thing - it logs every read/write *the agent itself* performs, at the application level.
   The ccloud CLI audit log is CockroachDB's own cluster-level audit trail. Showing both in
   your demo is a stronger "Production Readiness" story than either alone.

We deliberately do NOT use the Cloud Managed MCP Server here - it's designed for
connecting dev tools (Claude Code, Cursor, VS Code) to a cluster, not as a runtime API for
a deployed agent's own reasoning loop. Using it that way would be a stretch of its intended
purpose and adds integration risk without a clear scoring benefit over ccloud CLI.

## AWS services used (need 1+)

- **AWS Lambda** - runs `lambda_handler.py` on an EventBridge 4-hour schedule, doing the
  ingest step.
- **Amazon Bedrock** - `agent.py` calls Bedrock directly (Titan embeddings for the vector
  index, a Claude model on Bedrock for the reasoning/decision steps). This is a hand-built
  agent loop, not the managed Bedrock Agents product - that's intentional, for both learning
  value and full visibility into each step for the demo video.

## Setup

1. **CockroachDB**: create a free cluster at cockroachlabs.cloud, grab the connection string,
   run `app/schema.sql` against it.
2. **AWS**: make sure you have Bedrock model access enabled (Titan Embeddings + a Claude
   model) in your target region, and an IAM role/credentials with `bedrock:InvokeModel`.
3. Copy `.env.example` to `.env` and fill in `DATABASE_URL` and AWS region/model IDs.
4. `pip install -r requirements.txt`
5. Run locally: `uvicorn app.main:app --reload`
6. Run one ingest cycle manually: `python -m app.ingest`
7. Run one agent reasoning cycle manually: `python -m app.agent`

## Deploying the cron ingestion

Package `app/` + `lambda_handler.py` as a Lambda deployment (or container image), and create
an EventBridge Scheduler rule with a `rate(4 hours)` expression pointing at it. Keep the
FastAPI app running separately (ECS/EC2/App Runner) for the interactive querying + demo UI.

## Data source note

CDC publishes several public APIs/datasets (e.g. FluView, COVID Data Tracker) via
data.cdc.gov (Socrata). `app/ingest.py` has a placeholder `fetch_cdc_data()` - swap in the
specific dataset endpoint you choose once you've picked your exact signal (see README TODO
in that file). Keep it to ONE signal and 2-3 regions for the hackathon scope.

# flu-surveillance-agent
An agent that ingests CDC flu surveillance data, remembers historical patterns in CockroachDB, and generates auditable alerts using Bedrock reasoning
 3c0be781d5651c2a7fc01e51bbc839d008d47250
