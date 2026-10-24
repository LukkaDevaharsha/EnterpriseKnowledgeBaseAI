"""Transactional persistence and safe retry logic for chunk embeddings."""

import hashlib

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import DocumentChunk
from app.services.embedding_service import EmbeddingError, generate_embeddings


def _content_hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _needs_embedding(chunk, model_name):
    return not (
        chunk.embedding_status == "PROCESSED"
        and chunk.embedding is not None
        and chunk.embedding_model == model_name
        and chunk.embedding_content_hash == _content_hash(chunk.content)
    )


def process_document_embeddings(document_id, allow_model_change=False):
    """Embed missing/stale chunks; preserve chunks if inference fails.

    Returns True when all document chunks have a valid embedding for the
    configured model. A different model already present in the dataset blocks
    implicit model switching; callers must use the explicit re-embedding path.
    """
    model_name = current_app.config["EMBEDDING_MODEL_NAME"]
    try:
        chunks = (
            DocumentChunk.query.filter_by(document_id=document_id)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )
        all_model_ids = {
            model_id
            for (model_id,) in db.session.query(DocumentChunk.embedding_model)
            .filter(DocumentChunk.embedding_model.isnot(None))
            .distinct()
            .all()
        }
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception(
            "Could not inspect chunk embedding state; saved chunks are retained."
        )
        return False
    if not chunks:
        return False

    incompatible = all_model_ids - {model_name}
    if incompatible and not allow_model_change:
        current_app.logger.error(
            "Embedding model change blocked. Existing embeddings use another model; "
            "run the explicit re-embedding workflow first."
        )
        return False

    needing = [chunk for chunk in chunks if _needs_embedding(chunk, model_name)]
    if not needing:
        return True

    try:
        for chunk in needing:
            chunk.embedding_status = "PROCESSING"
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not mark chunks for embedding processing.")
        return False

    try:
        vectors = generate_embeddings(
            [chunk.content for chunk in needing],
            model_name=model_name,
            dimension=current_app.config["EMBEDDING_DIMENSION"],
        )
        if len(vectors) != len(needing):
            raise EmbeddingError("Embedding result count did not match chunk count.")

        # Persist the complete batch atomically. Old vectors remain untouched
        # until every replacement vector has been generated successfully.
        for chunk, vector in zip(needing, vectors):
            chunk.embedding = vector
            chunk.embedding_model = model_name
            chunk.embedding_content_hash = _content_hash(chunk.content)
            chunk.embedding_status = "PROCESSED"
        db.session.commit()
        return True
    except EmbeddingError:
        db.session.rollback()
        _mark_failed([chunk.id for chunk in needing])
        current_app.logger.exception(
            "Embedding generation failed; saved document chunks are retained."
        )
        return False
    except SQLAlchemyError:
        db.session.rollback()
        _mark_failed([chunk.id for chunk in needing])
        current_app.logger.exception(
            "Embedding persistence failed; saved document chunks are retained."
        )
        return False


def _mark_failed(chunk_ids):
    try:
        DocumentChunk.query.filter(DocumentChunk.id.in_(chunk_ids)).update(
            {DocumentChunk.embedding_status: "FAILED"},
            synchronize_session=False,
        )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not record failed embedding status.")


def reembed_all_chunks():
    """Explicitly re-embed the dataset for the configured model.

    Invoke from a maintenance command after changing EMBEDDING_MODEL_NAME.
    Rows are updated in document-sized atomic batches; a failed batch retains
    its previous vectors and is marked FAILED for a later retry.
    """
    document_ids = [row[0] for row in db.session.query(
        DocumentChunk.document_id
    ).distinct().order_by(DocumentChunk.document_id).all()]
    success = True
    for document_id in document_ids:
        success = process_document_embeddings(
            document_id, allow_model_change=True
        ) and success
    return success
