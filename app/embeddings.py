"""
Local embedding model (BAAI/bge-small-en-v1.5 via sentence-transformers), replacing
Bedrock Titan. Loaded once as a singleton since it's expensive to load - matters for
both the long-running FastAPI process and seed_reports.py's batch runs.
"""

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
