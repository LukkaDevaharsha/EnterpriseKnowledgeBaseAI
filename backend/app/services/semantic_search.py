"""Cosine-similarity retrieval over the existing PostgreSQL float arrays."""

import hashlib
import heapq
import math

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import Document, DocumentChunk
from app.services.embedding_service import EmbeddingError, generate_embeddings


DEFAULT_LIMIT = 5
MAX_LIMIT = 20
MAX_QUERY_LENGTH = 2000
MAX_RESULT_TEXT_LENGTH = 1200


class SearchError(RuntimeError):
    """Base error for request search failures."""


class SearchDatabaseError(SearchError):
    """Raised when the authorized search corpus cannot be queried."""


def validate_query(query):
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")
    if len(query) > MAX_QUERY_LENGTH:
        raise ValueError(f"query must not exceed {MAX_QUERY_LENGTH} characters")
    return query


def validate_limit(limit):
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    return limit


def _validated_vector(vector, dimension):
    try:
        values = [float(value) for value in vector]
    except (TypeError, ValueError, OverflowError) as exc:
        raise EmbeddingError("Embedding vector contains invalid numeric values.") from exc
    if len(values) != dimension:
        raise EmbeddingError(
            f"Embedding dimension mismatch: expected {dimension}, received {len(values)}."
        )
    if not all(math.isfinite(value) for value in values):
        raise EmbeddingError("Embedding vector contains non-finite values.")
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0 or not math.isfinite(norm):
        raise EmbeddingError("Embedding vector has zero or invalid length.")
    return values, norm


def _cosine_similarity(query_values, query_norm, stored_vector, dimension):
    stored_values, stored_norm = _validated_vector(stored_vector, dimension)
    score = sum(a * b for a, b in zip(query_values, stored_values)) / (
        query_norm * stored_norm
    )
    if not math.isfinite(score):
        return None
    # Floating point rounding can produce values just outside the cosine range.
    return max(-1.0, min(1.0, score))


def _content_hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _to_result(chunk, document, score):
    content = chunk.content
    if len(content) > MAX_RESULT_TEXT_LENGTH:
        content = content[:MAX_RESULT_TEXT_LENGTH].rstrip() + "…"
    return {
        "chunk_id": chunk.id,
        "document_id": document.id,
        "document_title": document.title,
        "document_type": document.file_type,
        "chunk_index": chunk.chunk_index,
        "content": content,
        "similarity_score": score,
    }


def search_chunks(query, user_id, limit=DEFAULT_LIMIT):
    """Return authorized chunks ordered by cosine similarity descending.

    Cosine similarity ranges from -1 to 1; it is a geometric similarity score,
    not a probability. Since the stored type is PostgreSQL ``double precision[]``
    rather than pgvector, matching authorized rows are scored in Python. The
    database applies ownership, status, and model filters before returning rows.
    """
    query = validate_query(query)
    limit = validate_limit(limit)
    model_name = current_app.config["EMBEDDING_MODEL_NAME"]
    dimension = current_app.config["EMBEDDING_DIMENSION"]

    try:
        base_query = (
            db.session.query(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(
                Document.uploaded_by == user_id,
                DocumentChunk.embedding_status == "PROCESSED",
                DocumentChunk.embedding_model == model_name,
                DocumentChunk.embedding.isnot(None),
            )
        )
        # Keyset batches avoid both a large result list and long-lived server
        # cursors while ensuring ownership is filtered in the database.
        batch_size = 256
        last_id = 0
        batch = (
            base_query.filter(DocumentChunk.id > last_id)
            .order_by(DocumentChunk.id.asc())
            .limit(batch_size)
            .all()
        )
        if not batch:
            return []
        query_output = generate_embeddings(
            [query], model_name=model_name, dimension=dimension
        )
        if not isinstance(query_output, (list, tuple)) or len(query_output) != 1:
            raise EmbeddingError("The query embedding service returned invalid output.")
        query_values, query_norm = _validated_vector(query_output[0], dimension)

        # Keep only the best `limit` results in memory while fetching rows in
        # bounded keyset batches.
        candidates = []
        while batch:
            for chunk, document in batch:
                if chunk.embedding_content_hash != _content_hash(chunk.content):
                    continue
                try:
                    score = _cosine_similarity(
                        query_values, query_norm, chunk.embedding, dimension
                    )
                except EmbeddingError:
                    # One malformed legacy row should not fail valid results.
                    continue
                if score is None:
                    continue
                stable = (document.id, chunk.chunk_index, chunk.id)
                item = (score, tuple(-part for part in stable), chunk, document)
                if len(candidates) < limit:
                    heapq.heappush(candidates, item)
                elif item[:2] > candidates[0][:2]:
                    heapq.heapreplace(candidates, item)
            last_id = batch[-1][0].id
            batch = (
                base_query.filter(DocumentChunk.id > last_id)
                .order_by(DocumentChunk.id.asc())
                .limit(batch_size)
                .all()
            )

        candidates.sort(key=lambda item: (-item[0], item[2].document_id,
                                          item[2].chunk_index, item[2].id))
        return [_to_result(chunk, document, score)
                for score, _, chunk, document in candidates]
    except EmbeddingError:
        raise
    except SQLAlchemyError as exc:
        db.session.rollback()
        raise SearchDatabaseError("Could not query the authorized search corpus.") from exc


