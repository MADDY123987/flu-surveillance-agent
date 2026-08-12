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

TARGET_REGIONS = [r.strip() for r in os.environ.get("TARGET_REGIONS", "California").split(",")]
TARGET_SIGNAL = os.environ.get("TARGET_SIGNAL", "flu_like_illness")
