"""Lazy shared Gemini SDK client; this module does not import ML frameworks."""

from flask import current_app


def get_gemini_client():
    api_key = current_app.config.get("GEMINI_API_KEY", "")
    if not isinstance(api_key, str) or not api_key.strip():
        raise RuntimeError("GEMINI_API_KEY is required for the Gemini provider.")

    cache_key = "gemini_client"
    client = current_app.extensions.get(cache_key)
    if client is not None:
        return client

    try:
        from google import genai
        from google.genai import types

        timeout_ms = int(float(current_app.config.get("GEMINI_TIMEOUT_SECONDS", 60)) * 1000)
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=timeout_ms),
        )
    except ImportError as exc:
        raise RuntimeError("Gemini SDK dependencies are not installed.") from exc
    current_app.extensions[cache_key] = client
    return client
