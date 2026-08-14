import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
EMBEDDING_MODEL_NAME = os.environ.get("EMBEDDING_MODEL_NAME", "BAAI/bge-small-en-v1.5")

TARGET_REGIONS = [r.strip() for r in os.environ.get("TARGET_REGIONS", "US,California,Texas,New York").split(",")]
TARGET_SIGNAL = os.environ.get("TARGET_SIGNAL", "flu_like_illness")

# A region/signal's newest observation older than this is not treated as "current" and
# does not drive alert generation - surfaced as a stale/data-gap state instead. Chosen
# above normal ILINet reporting lag (~19 days observed) and well below NY flu's ~327-day
# gap (see HANDOFF.md validation notes on the NY z=2.72 false alert this was added to fix).
FRESHNESS_THRESHOLD_DAYS = int(os.environ.get("FRESHNESS_THRESHOLD_DAYS", "42"))
