import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_EMBEDDING_MODEL_ID = os.environ.get(
    "BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0"
)
BEDROCK_REASONING_MODEL_ID = os.environ.get(
    "BEDROCK_REASONING_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"
)

TARGET_REGIONS = [r.strip() for r in os.environ.get("TARGET_REGIONS", "US,California,Texas,New York").split(",")]
TARGET_SIGNAL = os.environ.get("TARGET_SIGNAL", "flu_like_illness")

# When true, app.agent's Bedrock calls (embedding + reasoning) return deterministic
# mock output instead of calling AWS - lets the full pipeline (ingest -> agent ->
# alerts -> dashboard) be exercised locally without AWS credentials. Mock embeddings
# are NOT semantically meaningful (see app/agent.py), so real Bedrock is required to
# judge actual search/reasoning quality - this is for wiring/plumbing tests only.
MOCK_BEDROCK = os.environ.get("MOCK_BEDROCK", "false").strip().lower() in ("1", "true", "yes")
