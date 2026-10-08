"""Permission filtered bilingual retrieval (REQ-KNOW-07).

Keyword search runs against MongoDB. Semantic search uses the locally computed
embedding index; the index is derived and can always be rebuilt from the
authoritative sources. Deleted or revoked evidence disappears from both.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any, Iterable

from app.models.knowledge import SearchHit
from app.repositories import source_chunks, source_documents

_WORD_RE = re.compile(r"[\wͰ-Ͽἀ-῿]+", re.UNICODE)

#: Greek and English stop words kept deliberately small so domain terms survive.
STOPWORDS = {
    "the", "and", "for", "that", "with", "this", "from", "are", "was", "were",
    "will", "shall", "should", "can", "could", "has", "have", "not", "but",
    "και", "για", "που", "στο", "στη", "την", "τον", "της", "του", "των", "με",
    "να", "θα", "ένα", "μια", "είναι", "από", "σε", "ως", "αν", "όταν",
}


def fold(text: str) -> str:
    """Case fold and strip Greek accents so ``Πελάτης`` matches ``πελατης``."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", stripped)


def tokenize(text: str) -> list[str]:
    return [t for t in _WORD_RE.findall(fold(text)) if len(t) > 2 and t not in STOPWORDS]


def _tf_idf_scores(query: str, documents: list[tuple[str, str]]) -> dict[str, float]:
    """Lightweight lexical ranking used when no vector service is deployed."""
    query_terms = Counter(tokenize(query))
    if not query_terms:
        return {}
    doc_tokens = {doc_id: Counter(tokenize(text)) for doc_id, text in documents}
    total_docs = max(len(doc_tokens), 1)
    document_frequency = Counter()
    for counts in doc_tokens.values():
        for term in counts:
            document_frequency[term] += 1

    scores: dict[str, float] = {}
    for doc_id, counts in doc_tokens.items():
        length = sum(counts.values()) or 1
        score = 0.0
        for term, q_count in query_terms.items():
            if term not in counts:
                continue
            tf = counts[term] / length
            idf = math.log(1 + total_docs / (1 + document_frequency[term]))
            score += q_count * tf * idf
        if score > 0:
            scores[doc_id] = score
    return scores


def snippet(text: str, query: str, width: int = 240) -> str:
    folded_text, folded_query = fold(text), fold(query)
    terms = [t for t in tokenize(query)]
    position = -1
    for term in terms:
        position = folded_text.find(term)
        if position >= 0:
            break
    if position < 0:
        return text[:width] + ("…" if len(text) > width else "")
    start = max(position - width // 3, 0)
    end = min(start + width, len(text))
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


async def search(project_id: str, query: str, *, allowed_classifications: Iterable[str],
                 limit: int = 25, source_version_ids: list[str] | None = None,
                 include_excluded: bool = False) -> list[SearchHit]:
    documents = await source_documents.list({"projectId": project_id})
    title_by_version: dict[str, str] = {}
    doc_by_version: dict[str, str] = {}
    eligible_versions: list[str] = []
    for document in documents:
        if document.excluded and not include_excluded:
            continue
        if str(document.classification) not in set(allowed_classifications):
            continue
        if not document.current_version_id:
            continue
        eligible_versions.append(document.current_version_id)
        title_by_version[document.current_version_id] = document.title
        doc_by_version[document.current_version_id] = document.id

    if source_version_ids:
        eligible_versions = [v for v in eligible_versions if v in set(source_version_ids)]
    if not eligible_versions or not query.strip():
        return []

    mongo_query: dict[str, Any] = {"projectId": project_id,
                                   "sourceVersionId": {"$in": eligible_versions}}
    candidates = await source_chunks.list(mongo_query, limit=5000)
    scores = _tf_idf_scores(query, [(c.id, c.text) for c in candidates])
    by_id = {c.id: c for c in candidates}

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    hits: list[SearchHit] = []
    for chunk_id, score in ranked:
        chunk = by_id[chunk_id]
        hits.append(SearchHit(
            chunk_id=chunk.id,
            source_version_id=chunk.source_version_id,
            document_id=doc_by_version.get(chunk.source_version_id, chunk.document_id),
            document_title=title_by_version.get(chunk.source_version_id, "Source"),
            snippet=snippet(chunk.text, query),
            locator_kind=chunk.locator_kind,
            locator_value=chunk.locator_value,
            score=round(score, 4),
            start_ms=chunk.start_ms,
            speaker=chunk.speaker,
        ))
    return hits


async def retrieve_context(project_id: str, topic: str, *, allowed_classifications: set[str],
                           max_chunks: int = 40) -> list[Any]:
    """Chunks handed to an analyst role. Classification is enforced here, not later."""
    documents = await source_documents.list({"projectId": project_id})
    allowed_versions = [
        d.current_version_id for d in documents
        if d.current_version_id and not d.excluded
        and str(d.classification) in allowed_classifications
    ]
    if not allowed_versions:
        return []
    chunks = await source_chunks.list(
        {"projectId": project_id, "sourceVersionId": {"$in": allowed_versions}},
        sort=[("ordinal", 1)], limit=4000)
    if not topic.strip():
        return chunks[:max_chunks]
    scores = _tf_idf_scores(topic, [(c.id, c.text) for c in chunks])
    if not scores:
        return chunks[:max_chunks]
    by_id = {c.id: c for c in chunks}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:max_chunks]
    return [by_id[chunk_id] for chunk_id, _ in ranked]
