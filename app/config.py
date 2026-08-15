import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
EMBEDDING_MODEL_NAME = os.environ.get("EMBEDDING_MODEL_NAME", "BAAI/bge-small-en-v1.5")

# 11 regions: the original 4 (US/California/Texas/New York - kept including the two
# with known data issues, Texas RESP-NET and New York ILINet, since they're the only
# live demonstrations that the data-gap and freshness-guard handling work on real data)
# plus 7 states added via an empirical selection (RESP-NET catchment as the binding
# constraint, then filtered again by actual per-state ILINet freshness - see HANDOFF.md
# section 4 for the coverage table and section 9 for the epiweek 202539 finding).
TARGET_REGIONS = [r.strip() for r in os.environ.get(
    "TARGET_REGIONS",
    "US,California,Texas,New York,Colorado,Georgia,Maryland,Michigan,Minnesota,New Mexico,Tennessee",
).split(",")]
TARGET_SIGNAL = os.environ.get("TARGET_SIGNAL", "flu_like_illness")

# A region/signal's newest observation older than this is not treated as "current" and
# does not drive alert generation - surfaced as a stale/data-gap state instead. Chosen
# above normal ILINet reporting lag (~19 days observed) and well below NY flu's ~327-day
# gap (see HANDOFF.md validation notes on the NY z=2.72 false alert this was added to fix).
FRESHNESS_THRESHOLD_DAYS = int(os.environ.get("FRESHNESS_THRESHOLD_DAYS", "42"))

# Vector search over health_reports (see app.db.search_similar_reports) always returns
# its top-k nearest neighbors, even when nothing in memory is a genuine match. Since
# health_reports only holds CDC FluView narrative text (flu), a covid/rsv query has no
# relevant content available at all - "top match" there just means "least irrelevant."
# This cutoff (L2 distance on normalized 384-dim embeddings, so range [0, 2]; lower =
# more similar) separates the two cases. Derived empirically (2026-08-15) by embedding
# the real current situation-query text (app.agent.build_situation_text) for every one
# of the 11 live TARGET_REGIONS x 3 signal types, running an unfiltered top-10 vector
# search, and taking each query's best (smallest) distance:
#   flu_like_illness (relevant content exists):     n=11, min=0.544, max=0.637, mean=0.612
#   covid19/rsv_hospitalization (no relevant content): n=20, min=0.727, max=0.829, mean=0.782
# The two distributions are cleanly separable (flu max 0.637 < covid/rsv min 0.727, a
# ~0.09 gap) - 0.68 sits in the middle of that gap, ~0.04 of margin on each side.
# CAVEAT: this is corpus-specific, not a general relevance threshold - health_reports is
# 100% flu text, so part of the gap may be flu-query/flu-corpus vocabulary overlap rather
# than relevance per se. Re-derive if covid/rsv narrative content is ever added to the
# corpus (see HANDOFF.md, "Caveat: 0.68 is corpus-specific" section, for the full case).
# app.db.filter_relevant() drops any match above this before it reaches the agent's
# reasoning prompt or the /reports/search dashboard results.
REPORT_RELEVANCE_MAX_DISTANCE = float(os.environ.get("REPORT_RELEVANCE_MAX_DISTANCE", "0.68"))
