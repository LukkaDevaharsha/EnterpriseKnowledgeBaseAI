"""Add general-knowledge mode while keeping document answers fail-closed."""

import json
import re
from difflib import SequenceMatcher

from flask import current_app

from app.services import rag_service

GENERAL_SYSTEM_PROMPT = """Answer the user's general-knowledge question accurately and concisely.
You have no company documents for this request. Do not claim any answer reflects
the user's employer, company policy, or internal practice. Do not create source
citations. If the question requests an internal company-specific fact, explicitly
say that no company document supports an answer and abstain."""
COMPANY_CONTEXT_RE = re.compile(
    r"\b(company|company's|our|my employer|employees|policy|internal|"
    r"under the .* policy|allowance|grants?)\b|"
    r"\b(?:how many|how much)\b.{0,80}\b(?:annual|sick|parental|vacation)\s+leave\b|"
    r"\b(?:my|our)\s+(?:annual|sick|parental|vacation)\s+leave\b",
    re.IGNORECASE,
)
GENERAL_INTENT_RE = re.compile(
    r"^\s*(?:hi\b|hello\b|hey\b|explain\b|define\b|"
    r"what is\b|what are\b|how does .* work)\b",
    re.IGNORECASE,
)
SOCIAL_GREETING_RE = re.compile(
    r"^\s*(?:(?:hi|hello|hey)(?:\s+there)?"
    r"(?:[,!?.\s]+how are you(?: doing)?(?: today)?)?"
    r"|how are you(?: doing)?(?: today)?|how's it going(?: today)?)"
    r"[!?.,\s]*$",
    re.IGNORECASE,
)


def _general_is_appropriate(question):
    return not COMPANY_CONTEXT_RE.search(question)


def _has_general_intent(question):
    if GENERAL_INTENT_RE.search(question) or SOCIAL_GREETING_RE.fullmatch(question):
        return True
    words = re.findall(r"[a-z]+", question.lower())
    return (
        len(words) >= 3
        and words[1] == "is"
        and SequenceMatcher(None, words[0], "what").ratio() >= 0.75
    )


def _clearly_general(question):
    return _general_is_appropriate(question) and _has_general_intent(question)


def _question_is_directly_present(question, excerpt):
    stop_words = {
        "about", "after", "also", "and", "are", "does", "for", "from",
        "how", "into", "its", "that", "the", "their", "this", "what",
        "when", "where", "which", "with",
    }
    terms = set(re.findall(r"[a-z0-9]+", question.lower())) - stop_words
    excerpt_terms = set(re.findall(r"[a-z0-9]+", excerpt.lower()))
    matches = terms & excerpt_terms
    return len(terms) >= 2 and len(matches) >= max(2, (len(terms) + 1) // 2)


def _general_answer(question):
    if SOCIAL_GREETING_RE.fullmatch(question):
        return {
            "answer": "Hi! I'm here and ready to help. What would you like to know?",
            "citations": [],
            "insufficient_evidence": False,
            "answer_type": "general",
        }

    generation_options = {"model": current_app.config["GENERAL_AI_MODEL"]}
    if current_app.config.get("LLM_PROVIDER") == "gemini":
        generation_options["generation_mode"] = "general"
    raw = rag_service.generate_chat_answer(
        question, "[]", GENERAL_SYSTEM_PROMPT, **generation_options,
    )
    raw = raw[:rag_service.MAX_ANSWER_CHARS].strip()
    if (not raw or rag_service.SOURCE_REFERENCE_RE.search(raw)
            or rag_service.INSUFFICIENT_RESPONSE_RE.search(raw)):
        return {
            "answer": rag_service.INSUFFICIENT_ANSWER,
            "citations": [], "insufficient_evidence": True,
            "answer_type": "insufficient_evidence",
        }
    return {
        "answer": f"General information (not company policy): {raw}",
        "citations": [], "insufficient_evidence": False,
        "answer_type": "general",
    }


def answer_question(question, user_id, top_k=None, document_id=None):
    question = rag_service.validate_question(question)
    if top_k is None:
        top_k = current_app.config["RAG_DEFAULT_TOP_K"]
    top_k = rag_service.validate_top_k(top_k)
    # Clear general-knowledge prompts should not depend on embedding service
    # availability. Ambiguous questions still search first so relevant company
    # evidence can take precedence over a general answer.
    if document_id is None and _clearly_general(question):
        return _general_answer(question)

    # Only company-specific questions need to search the authorized corpus.
    if document_id is None:
        results = rag_service.search_chunks(question, user_id, top_k)
    else:
        results = rag_service.search_chunks(
            question, user_id, top_k, document_id=document_id
        )
    threshold = current_app.config["RAG_MIN_SIMILARITY"]
    relevant = [item for item in results if item["similarity_score"] >= threshold]
    if not relevant:
        if document_id is None and _general_is_appropriate(question):
            return _general_answer(question)
        return {
            "answer": rag_service.INSUFFICIENT_ANSWER,
            "citations": [], "insufficient_evidence": True,
            "answer_type": "insufficient_evidence",
        }

    entries = []
    citation_map = {}
    max_chars = current_app.config["RAG_MAX_CONTEXT_CHARS"]
    for item in relevant:
        source_id = f"S{len(entries) + 1}"
        entry = {
            "source_id": source_id, "document_id": item["document_id"],
            "document_title": item["document_title"], "chunk_id": item["chunk_id"],
            "chunk_index": item["chunk_index"], "page_number": item.get("page_number"),
            "excerpt": item["content"],
        }
        candidate = json.dumps(entries + [entry], ensure_ascii=False)
        if len(candidate) > max_chars:
            continue
        entries.append(entry)
        citation_map[source_id] = {
            **{key: entry[key] for key in (
                "source_id", "document_id", "document_title", "chunk_id",
                "chunk_index",
            )},
            "excerpt": entry["excerpt"][:500],
        }
        if entry["page_number"] is not None:
            citation_map[source_id]["page_number"] = entry["page_number"]
    if not citation_map:
        return {
            "answer": rag_service.INSUFFICIENT_ANSWER,
            "citations": [], "insufficient_evidence": True,
            "answer_type": "insufficient_evidence",
        }
    model_key = (
        "STUDY_PDF_MODEL"
        if document_id is not None else "COMPANY_KNOWLEDGE_MODEL"
    )
    generation_options = {"model": current_app.config[model_key]}
    if current_app.config.get("LLM_PROVIDER") == "gemini":
        generation_options["generation_mode"] = (
            "study" if document_id is not None else "company"
        )
    raw = rag_service.generate_chat_answer(
        question, json.dumps(entries, ensure_ascii=False), rag_service.SYSTEM_PROMPT,
        **generation_options,
    )
    answer, citations, insufficient = rag_service._clean_answer(raw, citation_map)
    # Small local models sometimes return relevant text without the required
    # source marker. For a selected PDF, fall back to the retrieved passage
    # itself rather than surfacing a misleading abstention or uncited prose.
    if (document_id is not None and insufficient
            and _question_is_directly_present(question, entries[0]["excerpt"])):
        source_id = next(iter(citation_map))
        answer = (
            f'Relevant passage from the selected PDF: '
            f'“{entries[0]["excerpt"]}” [{source_id}]'
        )
        citations = [citation_map[source_id]]
        insufficient = False
    return {
        "answer": answer,
        "citations": citations,
        "insufficient_evidence": insufficient,
        "answer_type": "insufficient_evidence" if insufficient else "document_grounded",
    }


def install_rag_extensions():
    from app.services.shared_search import search_chunks as shared_search
    rag_service.search_chunks = shared_search
    rag_service.answer_question = answer_question
