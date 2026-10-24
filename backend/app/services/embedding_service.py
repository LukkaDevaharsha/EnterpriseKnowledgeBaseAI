"""Local, lazily loaded text embedding generation and validation."""

import math
import threading

from flask import current_app, has_app_context


DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_DIMENSION = 384

_models = {}
_model_lock = threading.Lock()


class EmbeddingError(RuntimeError):
    """Raised when model loading or embedding generation fails."""


def _load_model(model_name):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise EmbeddingError(
            "Embedding dependencies are missing. Install backend requirements "
            "and download the configured model before retrying."
        ) from exc

    try:
        return SentenceTransformer(model_name)
    except Exception as exc:
        raise EmbeddingError(
            f"Could not load embedding model '{model_name}'. Check network/cache "
            "access and the configured model identifier."
        ) from exc


def _get_model(model_name):
    with _model_lock:
        if model_name not in _models:
            _models[model_name] = _load_model(model_name)
        return _models[model_name]


def _configuration(model_name, dimension):
    if has_app_context():
        model_name = model_name or current_app.config.get(
            "EMBEDDING_MODEL_NAME", DEFAULT_MODEL
        )
        dimension = dimension or current_app.config.get(
            "EMBEDDING_DIMENSION", DEFAULT_DIMENSION
        )
    else:
        model_name = model_name or DEFAULT_MODEL
        dimension = dimension or DEFAULT_DIMENSION
    if not isinstance(model_name, str) or not model_name.strip():
        raise EmbeddingError("EMBEDDING_MODEL_NAME must be a non-empty string.")
    if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
        raise EmbeddingError("Embedding dimension must be a positive integer.")
    return model_name.strip(), dimension


def _validate_vector(vector, dimension):
    try:
        values = [float(value) for value in vector]
    except (TypeError, ValueError, OverflowError) as exc:
        raise EmbeddingError("The embedding model returned invalid numeric data.") from exc

    if len(values) != dimension:
        raise EmbeddingError(
            f"Embedding dimension mismatch: expected {dimension}, received {len(values)}."
        )
    if not all(math.isfinite(value) for value in values):
        raise EmbeddingError("The embedding model returned non-finite values.")

    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0 or not math.isfinite(norm):
        raise EmbeddingError("The embedding model returned a zero or invalid vector.")
    return [value / norm for value in values]


def generate_embeddings(texts, model_name=None, dimension=None):
    """Generate normalized finite vectors for a batch of non-empty texts."""
    model_name, dimension = _configuration(model_name, dimension)
    if isinstance(texts, str):
        texts = [texts]
    try:
        normalized_texts = [" ".join(text.split()) for text in texts]
    except (TypeError, AttributeError) as exc:
        raise EmbeddingError("Embedding input must be text or a sequence of text.") from exc
    if not normalized_texts:
        return []
    if any(not text for text in normalized_texts):
        raise EmbeddingError("Empty or whitespace-only text cannot be embedded.")

    model = _get_model(model_name)
    try:
        output = model.encode(
            normalized_texts,
            batch_size=32,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
    except Exception as exc:
        raise EmbeddingError("Embedding model inference failed.") from exc

    try:
        vectors = output.tolist() if hasattr(output, "tolist") else list(output)
        if len(normalized_texts) == 1 and vectors and isinstance(vectors[0], (int, float)):
            vectors = [vectors]
        if len(vectors) != len(normalized_texts):
            raise EmbeddingError("The embedding model returned an unexpected batch size.")
        return [_validate_vector(vector, dimension) for vector in vectors]
    except EmbeddingError:
        raise
    except Exception as exc:
        raise EmbeddingError("The embedding model returned an invalid result.") from exc

