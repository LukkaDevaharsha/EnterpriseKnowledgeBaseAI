"""Authorized search over the current user's private docs and indexed shared docs.

This module preserves the existing search result shape while including only
shared documents whose extraction and embedding pipelines completed.
"""

import hashlib
import heapq
import math

from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import Document, DocumentChunk
from app.services import semantic_search as original
from app.services.embedding_service import EmbeddingError, embedding_model_identity
from app.services.semantic_search import (
    MAX_RESULT_TEXT_LENGTH, SearchDatabaseError, _content_hash,
    _cosine_similarity, _to_result, _validated_vector, validate_limit,
    validate_query,
)


def search_chunks(query, user_id, limit=5, document_id=None):
    query = validate_query(query)
    limit = validate_limit(limit)
    model = __import__("flask").current_app.config["EMBEDDING_MODEL_NAME"]
    dimension = __import__("flask").current_app.config["EMBEDDING_DIMENSION"]
    model_identity = embedding_model_identity(model, dimension)
    try:
        base_query = (
            db.session.query(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(
                or_(Document.uploaded_by == user_id, Document.is_shared.is_(True)),
                Document.status == "PROCESSED",
                DocumentChunk.embedding_status == "PROCESSED",
                DocumentChunk.embedding_model == model_identity,
                DocumentChunk.embedding.isnot(None),
            )
        )
        if document_id is not None:
            base_query = base_query.filter(Document.id == document_id)
        batch_size = 256
        last_id = 0
        candidates = []
        while True:
            batch = (base_query.filter(DocumentChunk.id > last_id)
                     .order_by(DocumentChunk.id.asc()).limit(batch_size).all())
            if not batch:
                break
            if last_id == 0:
                output = original.generate_embeddings([query], model_name=model, dimension=dimension)
                if not isinstance(output, (list, tuple)) or len(output) != 1:
                    raise EmbeddingError("The query embedding service returned invalid output.")
                query_values, query_norm = _validated_vector(output[0], dimension)
            for chunk, document in batch:
                if chunk.embedding_content_hash != _content_hash(chunk.content):
                    continue
                try:
                    score = _cosine_similarity(query_values, query_norm, chunk.embedding, dimension)
                except EmbeddingError:
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
        candidates.sort(key=lambda item: (-item[0], item[2].document_id,
                                          item[2].chunk_index, item[2].id))
        results = []
        for score, _, chunk, document in candidates:
            result = _to_result(chunk, document, score)
            result["page_number"] = chunk.page_number
            results.append(result)
        return results
    except EmbeddingError:
        raise
    except SQLAlchemyError as exc:
        db.session.rollback()
        raise SearchDatabaseError("Could not query the authorized search corpus.") from exc


def install_shared_search():
    original.search_chunks = search_chunks
