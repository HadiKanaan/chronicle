"""Relevance retrieval over an NPC's memories (Day 8 / RAG).

The conversation prompt used to inject an NPC's most RECENT few memories, so as
a character accumulated a life the important-but-old memories fell off the cap
and the injected ones rarely related to what the player just asked. This module
replaces recency selection with RELEVANCE retrieval: hold a large memory store
(behavior.MEMORY_BUFFER_CAP) but rank it against the player's current message
and return only the handful that matter, keeping the prompt small AND on-point.

The retriever is a scikit-learn TF-IDF + cosine ranker, fit over the NPC's own
memories at query time (cheap for ~50 short strings). It is the RAG/ML piece:
lexical relevance ranking. GRACEFUL FALLBACK (house pattern): if scikit-learn is
unavailable, the store is too small to rank, the query is empty, or the query
shares no terms with any memory, it falls back to recency (the last k).

Pure, DB-free: callers pass the memory strings in. Upgrade path (NOT a
dependency now): swap TF-IDF for local embeddings (Ollama ``nomic-embed-text``)
for true semantic recall - that would surface "my brother drowned in the flood"
for a query about *family*, which lexical TF-IDF cannot. The optional
importance weighting (blend cosine with a memory's drama score) hooks the
Witness Memory Tagger, which decides what enters the store; memories arrive as
plain strings today, so ranking is pure similarity.
"""

from __future__ import annotations

try:  # pragma: no cover - exercised by environment, not unit tests
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    _SKLEARN_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import failure means we use recency
    TfidfVectorizer = None  # type: ignore[assignment]
    cosine_similarity = None  # type: ignore[assignment]
    _SKLEARN_AVAILABLE = False


def recall_available() -> bool:
    """True when scikit-learn is importable (else retrieval is recency-only)."""
    return _SKLEARN_AVAILABLE


def recall_relevant(memories: list[str], query: str, k: int = 3) -> list[str]:
    """Return up to ``k`` of ``memories`` most relevant to ``query``.

    Ranked by TF-IDF cosine similarity, most-relevant first. Falls back to the
    most recent ``k`` (recency) when scikit-learn is missing, there are too few
    memories to rank, the query is empty, or nothing overlaps - so the caller
    always gets a sensible handful and never an exception.
    """
    cleaned = [m for m in (memories or []) if isinstance(m, str) and m.strip()]
    if not cleaned:
        return []
    # Nothing to rank against, or not enough to bother: most recent k.
    if not _SKLEARN_AVAILABLE or not (query or "").strip() or len(cleaned) <= k:
        return cleaned[-k:]

    try:
        vectorizer = TfidfVectorizer()
        matrix = vectorizer.fit_transform(cleaned)
        query_vec = vectorizer.transform([query])
        scores = cosine_similarity(query_vec, matrix)[0]
    except Exception:  # noqa: BLE001 - degrade to recency on any sklearn hiccup
        return cleaned[-k:]

    # No term overlap with any memory -> no relevance signal -> recency.
    if float(scores.max()) <= 0.0:
        return cleaned[-k:]

    # Rank by score desc; break ties toward the more recent memory (higher idx).
    order = sorted(range(len(cleaned)), key=lambda i: (float(scores[i]), i), reverse=True)
    return [cleaned[i] for i in order[:k]]
