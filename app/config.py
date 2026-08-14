import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
EMBEDDING_MODEL_NAME = os.environ.get("EMBEDDING_MODEL_NAME", "BAAI/bge-small-en-v1.5")

TARGET_REGIONS = [r.strip() for r in os.environ.get("TARGET_REGIONS", "US,California,Texas,New York").split(",")]
TARGET_SIGNAL = os.environ.get("TARGET_SIGNAL", "flu_like_illness")
