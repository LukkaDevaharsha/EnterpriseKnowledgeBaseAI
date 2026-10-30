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


def embedding_provider():
    if has_app_context():
        return current_app.config.get("EMBEDDING_PROVIDER", "sentence_transformers")
    return "sentence_transformers"


def embedding_model_identity(model_name=None, dimension=None):
    """Return a persisted identity that cannot mix distinct vector spaces."""
    model_name, dimension = _configuration(model_name, dimension)
    provider = embedding_provider()
    if provider == "gemini":
        return f"gemini:{model_name}:{dimension}"
    return model_name


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



def _generate_gemini_embeddings(texts, model_name, dimension):
    try:
        from google.genai import types
        from app.services.gemini_client import get_gemini_client

        client = get_gemini_client()
        vectors = []

        for offset in range(0, len(texts), 32):
            batch = texts[offset:offset + 32]

            # Each Content object represents one independent embedding.
            contents = [
                types.Content(
                    parts=[types.Part.from_text(text=text)]
                )
                for text in batch
            ]

            response = client.models.embed_content(
                model=model_name,
                contents=contents,
                config={
                    "output_dimensionality": dimension
                },
            )

            embeddings = getattr(response, "embeddings", None)

            if not isinstance(embeddings, (list, tuple)):
                raise EmbeddingError(
                    "Gemini returned an invalid embedding response."
                )

            if len(embeddings) != len(batch):
                raise EmbeddingError(
                    f"Expected {len(batch)} embeddings, "
                    f"received {len(embeddings)}."
                )

            for embedding in embeddings:
                values = (
                    embedding.get("values")
                    if isinstance(embedding, dict)
                    else getattr(embedding, "values", None)
                )

                vectors.append(values)

        if len(vectors) != len(texts):
            raise EmbeddingError(
                "Gemini returned an unexpected batch size."
            )

        return vectors

    except EmbeddingError:
        raise
    except Exception:
        raise EmbeddingError(
            "Gemini embedding request failed."
        ) from None
