"""Deterministic lexical checks for a small, versioned RAG benchmark."""

import re


SOURCE_REFERENCE_RE = re.compile(r"\[S(\d+)\]")
INSUFFICIENT_RE = re.compile(
    r"\b(?:not enough (?:relevant )?(?:information|evidence)|"
    r"insufficient (?:information|evidence)|"
    r"(?:cannot|can't|unable to) answer|"
    r"(?:do not|don't) contain enough|"
    r"(?:does not|doesn't|did not|didn't) (?:explicitly )?(?:specify|state|mention|provide)|"
    r"(?:is|are|was|were) not (?:explicitly )?(?:specified|stated|mentioned|provided))\b",
    re.IGNORECASE,
)


def _normalize(value):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _matches_locator(result, locator):
    content = locator["content_contains"].casefold()
    expected_filename = locator.get("document_filename")
    if expected_filename:
        # Match the source filename from stored document metadata exactly.
        # A display title can be edited independently of the original filename.
        document_matches = (
            result.get("original_filename", "").casefold()
            == expected_filename.casefold()
        )
    else:
        expected_title = locator.get("document_title", "")
        document_matches = (
            bool(expected_title)
            and result.get("document_title", "").casefold()
            == expected_title.casefold()
        )
    return (
        document_matches
        and content in result.get("content", "").casefold()
    )


def _answer_sentences(answer):
    """Split claims on sentence punctuation and attach trailing citation tokens."""
    parts = re.split(r"(?<=[.!?])\s+", answer.strip()) if answer.strip() else []
    sentences = []
    for part in parts:
        leading_refs = re.match(r"^((?:\[S\d+\]\s*)+)(.*)$", part, re.DOTALL)
        if leading_refs and sentences:
            sentences[-1] = f"{sentences[-1]} {leading_refs.group(1).strip()}".strip()
            remainder = leading_refs.group(2).strip()
            if remainder:
                sentences.append(remainder)
        else:
            sentences.append(part)
    return sentences


def evaluate_retrieval_case(case, results, top_k, min_similarity):
    """Score expected content locators against one ranked search result list."""
    results = results[:top_k]
    support_checks = []
    for locator in case["supporting_chunks"]:
        match = next((result for result in results if _matches_locator(result, locator)), None)
        support_checks.append({
            "document_filename": locator.get("document_filename"),
            "document_title": locator.get("document_title"),
            "content_contains": locator["content_contains"],
            "retrieved": match is not None,
            "matched_document_title": match.get("document_title") if match else None,
            "matched_document_filename": match.get("original_filename") if match else None,
            "document_id": match.get("document_id") if match else None,
            "chunk_id": match.get("chunk_id") if match else None,
            "similarity_score": match.get("similarity_score") if match else None,
        })

    hits = sum(check["retrieved"] for check in support_checks)
    expected_count = len(support_checks)
    matched_chunk_keys = {
        (check["document_id"], check["chunk_id"])
        for check in support_checks
        if check["retrieved"]
    }
    return {
        "case_id": case["id"],
        "answerable": case["answerable"],
        "top_k": top_k,
        "retrieved_count": len(results),
        "retrieved_chunks": [
            {
                "document_id": result.get("document_id"),
                "document_title": result.get("document_title"),
                "chunk_id": result.get("chunk_id"),
                "chunk_index": result.get("chunk_index"),
                "similarity_score": result.get("similarity_score"),
            }
            for result in results
        ],
        "retrieved_above_threshold": sum(
            result.get("similarity_score", -1) >= min_similarity
            for result in results
        ),
        "supporting_chunks_found": hits,
        "supporting_chunks_expected": expected_count,
        "precision_at_k": hits / top_k if expected_count else None,
        "precision_at_returned": (
            len(matched_chunk_keys) / len(results)
            if results and expected_count else None
        ),
        "recall_at_k": hits / expected_count if expected_count else None,
        "support_checks": support_checks,
    }


def evaluate_retrieval(cases, retrieve, top_k, min_similarity):
    """Evaluate search cases; ``retrieve(question, top_k)`` returns ranked hits."""
    case_results = [
        evaluate_retrieval_case(
            case, retrieve(case["question"], top_k), top_k, min_similarity
        )
        for case in cases
    ]
    answerable = [result for result in case_results if result["answerable"]]
    expected_total = sum(
        result["supporting_chunks_expected"] for result in answerable
    )
    found_total = sum(
        result["supporting_chunks_found"] for result in answerable
    )
    precision_values = [
        result["precision_at_k"] for result in answerable
        if result["precision_at_k"] is not None
    ]
    returned_precision_values = [
        result["precision_at_returned"] for result in answerable
        if result["precision_at_returned"] is not None
    ]
    return {
        "top_k": top_k,
        "answerable_cases": len(answerable),
        "unanswerable_cases": len(case_results) - len(answerable),
        "supporting_chunks_found": found_total,
        "supporting_chunks_expected": expected_total,
        "recall_at_k": found_total / expected_total if expected_total else None,
        "mean_precision_at_k": (
            sum(precision_values) / len(precision_values)
            if precision_values else None
        ),
        "mean_precision_at_returned": (
            sum(returned_precision_values) / len(returned_precision_values)
            if returned_precision_values else None
        ),
        "cases": case_results,
    }


def evaluate_answer(case, answer, citations, retrieved_results, min_similarity):
    """Check answer facts against evidence and the sources cited for each fact.

    This intentionally small evaluator checks benchmark facts by normalized
    phrase matching. It is reproducible, but is not a semantic entailment model.
    """
    answer = answer if isinstance(answer, str) else ""
    citations = citations if isinstance(citations, list) else []
    relevant = [
        result for result in retrieved_results
        if result.get("similarity_score", -1) >= min_similarity
    ]
    source_results = {f"S{index + 1}": result for index, result in enumerate(relevant)}
    answer_ids = [f"S{match}" for match in SOURCE_REFERENCE_RE.findall(answer)]
    citation_records = [
        item.get("source_id") for item in citations if isinstance(item, dict)
    ]
    all_ids = answer_ids + [item for item in citation_records if isinstance(item, str)]
    invalid_source_ids = sorted({source_id for source_id in all_ids if source_id not in source_results})

    normalized_answer = _normalize(answer)
    present_facts = [
        fact for fact in case["expected_facts"]
        if _normalize(fact) in normalized_answer
    ]
    absent_facts = [fact for fact in case["expected_facts"] if fact not in present_facts]

    records_by_source = {}
    invalid_citations = []
    for record in citations:
        if not isinstance(record, dict):
            continue
        source_id = record.get("source_id")
        source = source_results.get(source_id)
        if source is None:
            continue
        mismatched_fields = [
            field for field in ("document_id", "chunk_id", "chunk_index")
            if record.get(field) is not None and record.get(field) != source.get(field)
        ]
        if mismatched_fields:
            invalid_citations.append({
                "source_id": source_id,
                "mismatched_fields": mismatched_fields,
            })
        else:
            records_by_source[source_id] = record

    # A citation must appear in the raw answer and have a matching returned
    # citation record. API fallback citations alone cannot make a raw answer
    # appear cited during evaluation.
    sentences = _answer_sentences(answer)
    missing_fact_citation = False

    unsupported_facts = []
    unsupported_citation_facts = []
    for fact in present_facts:
        normalized_fact = _normalize(fact)
        claim_sentences = [
            sentence for sentence in sentences
            if normalized_fact in _normalize(sentence)
        ]
        supported_by_evidence = any(
            normalized_fact in _normalize(result.get("content", ""))
            for result in relevant
        )
        if not supported_by_evidence:
            unsupported_facts.append(fact)
        citation_support_failed = False
        for sentence in claim_sentences:
            sentence_ids = {
                f"S{match}" for match in SOURCE_REFERENCE_RE.findall(sentence)
            }
            cited_sources = sentence_ids & set(records_by_source) & set(source_results)
            if not cited_sources:
                missing_fact_citation = True
            elif not any(
                normalized_fact in _normalize(source_results[source_id].get("content", ""))
                for source_id in cited_sources
            ):
                citation_support_failed = True
        if citation_support_failed:
            unsupported_citation_facts.append(fact)

    missing_citation = bool(case["answerable"] and missing_fact_citation)

    if case["answerable"]:
        unsupported_answer = bool(absent_facts or unsupported_facts or unsupported_citation_facts)
    else:
        # A model may cite the retrieved excerpt while explicitly stating that
        # it does not contain the requested fact. That is still an abstention;
        # fabricated source IDs and mismatched citation records remain errors.
        correct_abstention = (
            bool(INSUFFICIENT_RE.search(answer))
            and not invalid_source_ids
            and not invalid_citations
        )
        unsupported_answer = not correct_abstention

    if case["answerable"]:
        correct_abstention = None

    return {
        "case_id": case["id"],
        "answerable": case["answerable"],
        "missing_citation": missing_citation,
        "invalid_source_ids": invalid_source_ids,
        "invalid_citations": invalid_citations,
        "expected_facts_found": len(present_facts),
        "expected_facts_total": len(case["expected_facts"]),
        "expected_facts_absent": absent_facts,
        "unsupported_facts": unsupported_facts,
        "unsupported_citation_facts": unsupported_citation_facts,
        "correct_abstention": correct_abstention,
        "unsupported_answer": unsupported_answer,
    }


def summarize_answer_checks(checks):
    """Aggregate deterministic answer and citation checks."""
    total = len(checks)
    return {
        "cases": total,
        "missing_citations": sum(check["missing_citation"] for check in checks),
        "cases_with_invalid_source_ids": sum(bool(check["invalid_source_ids"]) for check in checks),
        "cases_with_invalid_citations": sum(bool(check.get("invalid_citations")) for check in checks),
        "cases_with_absent_expected_facts": sum(bool(check.get("expected_facts_absent")) for check in checks),
        "unsupported_answers": sum(check["unsupported_answer"] for check in checks),
        "correct_abstentions": sum(check.get("correct_abstention") is True for check in checks),
        "checks": checks,
    }
