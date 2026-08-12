# Next Steps — Frontend polish + memory-showcase features

Append this as a new section in HANDOFF.md (e.g. "## 12. Frontend & feature
additions") once done, so the doc stays the single source of truth. Everything
here is inside the locked scope from section 3 — no new data sources, no new
regions, no new cloud dependencies beyond Bedrock (already required). Do not
reopen the scope questions already settled in section 3.

Context: the dashboard (`app/static/index.html` + `/dashboard` mount in
`main.py`) already exists and was verified serving correctly-shaped real data
from a local CockroachDB instance. This is a polish + feature pass on top of
that, not a rebuild.

## 1. Dashboard polish (do first, cheap, removes demo-day surprises)

- Visually verify `/dashboard/` in an actual browser against real local data
  (chart rendering, table layout, narrow-window behavior).
- Add a small "data gap" badge per region/signal where coverage is known to be
  incomplete: New York currently has no recent ILINet flu signal (Delphi's
  last NY data point is ~Sept 2025); Texas is not a RESP-NET catchment state
  so it will only ever show a flu signal, never COVID/RSV hospitalization.
  Surface these as visible, labeled product behavior — not something a judge
  discovers as an apparent bug on camera.
- Make `agent_reasoning` (JSONB) legible in the alerts table: expand-on-click
  showing the step-by-step trace — which signal, which z-score, which
  historical report it matched via vector search, and why. This is the
  clearest way to demonstrate the "Agentic Memory Design" judging criterion
  on screen.
- Add basic loading/error states to the dashboard's fetch calls.

## 2. New feature: semantic search box (highest priority new feature)

Add a search input on the dashboard — "search past reports" — backed by a new
endpoint:

`GET /reports/search?q=<text>` — embeds the query text the same way
`health_reports.embedding` was built, runs a vector similarity search against
`health_reports`, returns top-k matches with a similarity score.

This lets a judge type something in and watch the memory layer respond live —
a much stronger demo moment than a static rankings table. Use the
`MOCK_BEDROCK` flag for local dev; use real Bedrock for the actual demo
recording.

## 3. Optional stretch feature: cross-region pattern match

On a region detail view, surface "closest historical match" — compare the
current region's recent signal shape (already computed via z-score / WoW %
change) against other regions' past snapshots using the same vector
infrastructure already built, e.g. "Texas's current trend most resembles
California in week 28." Reuses existing infrastructure, no new integrations.
Only attempt this after 1 and 2 are solid — it directly targets the
Creativity & Originality criterion but is not required for a working demo.

## Suggested order given limited time before deadline

1. Dashboard polish + data-gap badges (section 1)
2. Legible agent_reasoning trace (section 1)
3. Semantic search box (section 2)
4. Cross-region pattern match only if time remains (section 3)

Do not start on CockroachDB Cloud / AWS Bedrock / Lambda deployment work in
this pass — that's tracked separately in HANDOFF.md section 10 and is
blocked on external account access.
