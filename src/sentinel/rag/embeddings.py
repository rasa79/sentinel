# LEARN[12]: why embeddings are provider-independent local models (deep-dive — D2)
#  Why this way: retrieval uses sentence-transformers all-MiniLM-L6-v2 running locally in BOTH LLM
# modes
#   (cloud and local), rather than calling a hosted embeddings API. The pgvector column is fixed at
#    384 dimensions precisely because this model's output size is fixed; RAG is a pure retrieval
#   concern
#   and we keep it identical across providers so retrieval quality and the vector schema never vary.
# Good sides:
#    - works offline and identically in cloud/local modes; no per-token embeddings cost or rate
#   limits
#    - a fixed 384-dim schema lets pgvector index comparisons be stable (no schema drift if
#   providers differ)
#    - the same model embeds the corpus and the query, which is a hard requirement for cosine
#   similarity
# Drawbacks:
#    - the model must be downloaded to a cache at first use and it has a fixed dimension, so
#   changing the
#     model would silently invalidate stored vectors (the real reason for D2)
#   - a small model is weaker than a large hosted encoder for nuanced semantic matching
#   - it burns local CPU/RAM on each embed (fine for a small demo corpus, not for massive ingestion)
#  Concept: an embedding is a dense fixed-length vector that represents the meaning of a text, such
# that
#   similar texts land close together (high cosine similarity). For vector search you need BOTH the
#    corpus AND the query embedded with the SAME model — a vector from model A and a query from
#   model B
#   live in different spaces and are meaningless to compare. That is why D2 pins one local model and
#   fixes the column to 384 dims: pgvector stores a `vector(384)` and compares with cosine distance
#   (`embedding <=> query`), so every stored vector must be produced by the same encoder. If you
#   switched to a hosted 1536-dim model, the stored 384-dim vectors would no longer be comparable —
#    the schema and all prior embeddings would silently break. The `normalize_embeddings=True` call
#   makes
#    vectors unit-length, so cosine distance becomes a simple dot product and `<=>` behaves
#   predictably.
#    For a relational-DB engineer, this is the same shape as "store a derived key and search by a
#   hash",
#   except the "hash" is a learned vector that preserves semantic proximity rather than equality.
# See also: LEARN[13] (retrieval), the runbooks corpus in runbooks/, Task 2.3/2.4 in PLAN.md
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"


def _ensure_cache_dir() -> None:
    """Point HF caches at a repo-local dir (default ~/.cache is read-only)."""
    if not os.environ.get("HF_HOME") and not os.environ.get("TRANSFORMERS_CACHE"):
        repo_root = Path(__file__).resolve().parent.parent.parent
        os.environ.setdefault("HF_HOME", str(repo_root / ".cache" / "huggingface"))


@lru_cache(maxsize=1)
def get_embedder(model_name: str = EMBEDDING_MODEL_NAME) -> SentenceTransformer:
    """Lazily load the cached SentenceTransformer model once per process."""
    _ensure_cache_dir()
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def embed_texts(texts: list[str], model_name: str = EMBEDDING_MODEL_NAME) -> list[list[float]]:
    """Embed a batch of texts to normalized unit-length vectors (cosine-friendly)."""
    model = get_embedder(model_name)
    vectors = model.encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in vectors]
