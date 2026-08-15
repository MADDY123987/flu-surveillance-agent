FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.cache/huggingface

COPY requirements.txt .

# Install the CPU-only torch build first, from PyTorch's own CPU wheel index - this
# container never has a GPU (local compose or AWS Fargate/App Runner alike), and the
# default PyPI torch wheel bundles CUDA, which is ~5x the download/image size for
# nothing this app can use. Installed before requirements.txt so sentence-transformers'
# torch dependency is already satisfied and pip doesn't pull the CUDA build instead.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image at build time so the first real request after
# deploy doesn't stall on a Hugging Face download - app/embeddings.py loads this same
# model name (BAAI/bge-small-en-v1.5, see EMBEDDING_MODEL_NAME in app/config.py) lazily
# at first use; this warms HF_HOME's cache during the build instead, so that lazy load
# just reads local disk at runtime.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

COPY app app

EXPOSE 8080

# init_db applies app/schema.sql (idempotent - CREATE ... IF NOT EXISTS throughout) before
# the API starts serving, so a fresh CockroachDB target doesn't need a separate manual
# schema step. See app/init_db.py.
CMD ["sh", "-c", "python -m app.init_db && uvicorn app.main:app --host 0.0.0.0 --port 8080"]
