# Outbreak Intelligence Agent — Final Plan

Locked scope. Do not reopen without finishing this first.

## The pitch
A single agent that continuously ingests real CDC respiratory surveillance data,
remembers it durably and semantically in CockroachDB, and reasons over that memory
to rank and explain emerging outbreak risk across the US. Not a pandemic predictor —
early anomaly detection through multi-signal memory retrieval.

## Scope
- **Regions:** National + California, Texas, New York (expand to all 50 states on
  Day 7 ONLY if core is fully working — see day plan below)
- **Data sources (3, all real, no more):**
  1. CDC ILINet via Delphi Epidata API — flu-like illness rate — WORKING, tested
  2. CDC RESP-NET via data.cdc.gov — COVID-19 + RSV hospitalization rates — needs
     resource ID confirmed at data.cdc.gov (search "RESP-NET", click API tab)
  3. CDC FluView weekly narrative reports — real written text for genuine vector
     search — URL pattern: cdc.gov/fluview/surveillance/{year}-week-{NN}.html
- **Explicitly cut:** Google Trends (no official API, unreliable), news signals
  (noisy, pollutes vector memory), mortality data (too laggy), multi-country,
  multi-agent infrastructure, ED visits, clinical lab positivity (unless later
  confirmed to be same Delphi API family — 10 min check, not a blocker)

## Architecture
Three CDC sources -> Lambda (4h cron via EventBridge) -> CockroachDB (4 memory types)
-> single agent loop (Bedrock) -> FastAPI -> dashboard.

## CockroachDB — four memory types, two required tools
1. **Time-series** (`health_signals`) — every weekly reading, every region/signal
2. **Semantic** (`health_reports` + vector index) — FluView text + embeddings,
   enables real "has this happened before" queries — satisfies **Distributed
   Vector Indexing** requirement
3. **State** (`alerts` + `alert_state_transitions`) — full lifecycle: new ->
   acknowledged -> resolved, not one-shot notifications
4. **Access** (`audit_log`) — every agent read/write, logged and queryable
   Second required CockroachDB tool: **ccloud CLI** — cluster status, audit log,
   backup checks, run live in the demo video for Production Readiness

## Agent loop (single agent, five real steps)
1. Fetch recent signal history from CockroachDB
2. Compute features in Python — z-score, week-over-week % change (not left to
   the LLM to eyeball)
3. Vector search FluView text for similar historical situations
4. Bedrock reasoning call: computed stats + retrieved history -> decision
5. Act: write alert with full reasoning trace, or transition an existing alert's state

## AWS used
- **Lambda + EventBridge** — 4-hour scheduled ingestion
- **Bedrock** (Titan embeddings + Claude reasoning) — called directly via boto3,
  hand-built agent loop, not the managed Bedrock Agents product (full visibility
  for the demo, lower integration risk)

## API surface (FastAPI)
`/signals/{signal_type}/{region}`, `/rankings` (top anomalous combos by |z-score|),
`/alerts`, `/alerts/{id}/transition`, `/alerts/{id}/history`, `/audit`,
`/trigger/ingest`, `/trigger/agent/{signal_type}/{region}` (manual triggers for demo)

## Dashboard
Live signal trends, ranked risk list, alert feed with state, audit trail. Doesn't
need to be beautiful — needs to make memory and reasoning visible on screen.

## Submission requirements checklist
- [ ] Public GitHub repo with visible MIT/Apache 2.0 license
- [ ] Clear README (setup, architecture, which CockroachDB/AWS tools + how)
- [ ] Functional demo app URL
- [ ] Demo video, under 3 minutes, public on YouTube/Vimeo
- [ ] Optional: architecture diagram (have one)

---

## Day-by-day plan (10 days, deadline Aug 19)

**Day 1 — Infrastructure**
Push starter code to repo (public, MIT license). Create CockroachDB cluster, run
schema.sql. Request Bedrock model access immediately (approval lag risk).

**Day 2 — Real data flowing**
Confirm RESP-NET resource ID + field names. Get ILINet + RESP-NET ingestion both
writing real data into `health_signals` for all 4 regions.

**Day 3 — Real text memory**
Build the FluView narrative scraper. Extract weekly report text, embed via Titan,
store in `health_reports`. This is the piece that makes vector search real.

**Day 4 — Agent loop working**
Full 5-step loop producing a real, sensible alert with a visible reasoning trace.
Alert state transitions working via the API.

**Day 5 — Ranking + production touches**
`/rankings` endpoint live. ccloud CLI commands tested against the real cluster.
Basic retry/error handling in ingest.py.

**Day 6 — Buffer / catch-up**
Fix anything broken from days 1-5. Do not start new features if anything upstream
is still shaky.

**Day 7 — Optional expansion**
ONLY if everything above is solid: widen TARGET_REGIONS toward all 50 states.
Skip entirely if behind schedule — 4 regions is a complete submission on its own.

**Day 8 — Dashboard**
Build the page that shows trends, rankings, alerts, and audit trail on screen.

**Day 9 — Demo video**
Script and record: real data in, alert generated with visible reasoning, ranking
view, ccloud CLI audit-log moment.

**Day 10 — Submission polish**
Finish README, clean commit history, confirm license visible, submit with hours
to spare, not minutes.
