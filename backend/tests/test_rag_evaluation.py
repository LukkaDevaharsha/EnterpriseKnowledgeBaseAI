import json
from pathlib import Path

import pytest

from app.rag.evaluation import (
    evaluate_answer,
    evaluate_retrieval,
    evaluate_retrieval_case,
    summarize_answer_checks,
)
from app.services.rag_service import INSUFFICIENT_ANSWER
from evaluate_rag import _answer_diagnostic


DATASET_PATH = Path(__file__).parents[1] / "evaluation" / "rag_cases.json"


def load_cases():
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))["cases"]


def leave_result(content=None, score=0.91):
    return {
        "chunk_id": 42,
        "document_id": 7,
        "document_title": "Leave policy",
        "original_filename": "leave_policy.txt",
        "chunk_index": 0,
        "content": content or (
            "Employees may take annual leave and sick leave under the company leave policy."
        ),
        "similarity_score": score,
    }


def test_dataset_contains_answerable_and_unanswerable_leave_cases():
    cases = load_cases()
    leave_case = next(case for case in cases if case["id"] == "leave-types")

    assert any(case["answerable"] for case in cases)
    assert any(not case["answerable"] for case in cases)
    assert leave_case["supporting_chunks"][0]["content_contains"] == (
        "Employees may take annual leave and sick leave under the company leave policy."
    )
    assert leave_case["supporting_chunks"][0]["document_filename"] == "leave_policy.txt"
    assert leave_case["expected_facts"] == ["annual leave", "sick leave"]


def test_filename_locator_matches_title_only_when_original_filename_metadata_matches():
    case = next(case for case in load_cases() if case["id"] == "leave-types")
    result = leave_result()
    report = evaluate_retrieval_case(case, [result], top_k=1, min_similarity=0.25)

    assert result["document_title"] == "Leave policy"
    assert result["original_filename"] == "leave_policy.txt"
    assert report["supporting_chunks_found"] == 1
    assert report["support_checks"][0]["document_id"] == 7
    assert report["support_checks"][0]["chunk_id"] == 42


def test_no_matching_document_filename_does_not_count_even_if_content_matches():
    case = next(case for case in load_cases() if case["id"] == "leave-types")
    result = leave_result()
    result["original_filename"] = "other_policy.txt"
    report = evaluate_retrieval_case(case, [result], top_k=1, min_similarity=0.25)

    assert report["supporting_chunks_found"] == 0
    assert report["support_checks"][0]["retrieved"] is False


def test_retrieval_reports_support_recall_and_configurable_precision_at_k():
    cases = load_cases()
    calls = []

    def retrieve(question, top_k):
        calls.append(top_k)
        if "types of leave" in question:
            return [leave_result(), {
                **leave_result("An unrelated handbook chunk."),
                "chunk_id": 43,
                "similarity_score": 0.5,
            }]
        return []

    report = evaluate_retrieval(cases, retrieve, top_k=2, min_similarity=0.25)

    assert calls == [2] * len(cases)
    leave = next(case for case in report["cases"] if case["case_id"] == "leave-types")
    assert leave["supporting_chunks_found"] == 1
    assert leave["supporting_chunks_expected"] == 1
    assert leave["recall_at_k"] == 1.0
    assert leave["precision_at_k"] == 0.5
    assert leave["precision_at_returned"] == 0.5
    assert report["supporting_chunks_found"] == 1
    assert report["supporting_chunks_expected"] == 2
    assert report["recall_at_k"] == 0.5
    assert report["mean_precision_at_k"] == 0.25
    assert report["mean_precision_at_returned"] == 0.5


def test_precision_at_k_keeps_fixed_denominator_and_reports_returned_set_precision():
    case = next(case for case in load_cases() if case["id"] == "leave-types")

    report = evaluate_retrieval_case(
        case, [leave_result()], top_k=5, min_similarity=0.25
    )
    empty_report = evaluate_retrieval_case(
        case, [], top_k=5, min_similarity=0.25
    )

    # One correct result out of one returned, while fixed P@5 remains 1/5.
    assert report["precision_at_k"] == 0.2
    assert report["precision_at_returned"] == 1.0
    assert empty_report["precision_at_k"] == 0.0
    assert empty_report["precision_at_returned"] is None


def test_answer_evaluation_accepts_supported_facts_and_valid_citations():
    case = next(case for case in load_cases() if case["id"] == "leave-types")
    result = leave_result()
    check = evaluate_answer(
        case,
        "Employees may take annual leave and sick leave. [S1]",
        [{"source_id": "S1", "document_id": 7, "chunk_id": 42}],
        [result],
        min_similarity=0.25,
    )

    assert check["missing_citation"] is False
    assert check["invalid_source_ids"] == []
    assert check["unsupported_answer"] is False
    assert check["expected_facts_found"] == 2


def test_answer_evaluation_detects_missing_and_invalid_citations_without_fallback_credit():
    case = next(case for case in load_cases() if case["id"] == "leave-types")
    result = leave_result()

    missing = evaluate_answer(
        case,
        "Employees may take annual leave and sick leave.",
        # The application may return fallback citations; without source IDs in
        # the raw answer these must not turn the model response into a cited one.
        [{"source_id": "S1", "document_id": 7, "chunk_id": 42}],
        [result],
        0.25,
    )
    invalid = evaluate_answer(
        case,
        "Employees may take annual leave and sick leave. [S99]",
        [{"source_id": "S99"}],
        [result],
        0.25,
    )

    assert missing["missing_citation"] is True
    assert missing["unsupported_facts"] == []
    assert missing["unsupported_answer"] is False
    assert invalid["invalid_source_ids"] == ["S99"]
    assert invalid["missing_citation"] is True


def test_answer_evaluation_detects_expected_facts_present_but_not_supported_by_evidence():
    case = next(case for case in load_cases() if case["id"] == "leave-types")
    unrelated = leave_result("Employees may work remotely with manager approval.")
    check = evaluate_answer(
        case,
        "Employees may take annual leave and sick leave. [S1]",
        [{"source_id": "S1", "document_id": 7, "chunk_id": 42}],
        [unrelated],
        0.25,
    )

    assert check["expected_facts_found"] == 2
    assert check["expected_facts_absent"] == []
    assert check["unsupported_facts"] == ["annual leave", "sick leave"]
    assert check["unsupported_citation_facts"] == ["annual leave", "sick leave"]
    assert check["unsupported_answer"] is True


def test_answer_evaluation_detects_citation_that_points_to_wrong_chunk():
    case = next(case for case in load_cases() if case["id"] == "leave-types")
    result = leave_result()
    check = evaluate_answer(
        case,
        "Employees may take annual leave and sick leave. [S1]",
        [{"source_id": "S1", "document_id": 7, "chunk_id": 999}],
        [result],
        0.25,
    )

    assert check["invalid_citations"] == [{
        "source_id": "S1",
        "mismatched_fields": ["chunk_id"],
    }]
    assert check["missing_citation"] is True


def test_answer_citations_must_support_the_claim_in_their_sentence():
    case = next(case for case in load_cases() if case["id"] == "leave-types")
    annual = leave_result("Employees may take annual leave.")
    sick = {
        **leave_result("Employees may take sick leave."),
        "document_id": 8,
        "chunk_id": 43,
        "chunk_index": 1,
    }
    check = evaluate_answer(
        case,
        "Annual leave is available. [S2] Sick leave is available. [S1]",
        [
            {"source_id": "S1", "document_id": 7, "chunk_id": 42},
            {"source_id": "S2", "document_id": 8, "chunk_id": 43},
        ],
        [annual, sick],
        0.25,
    )

    assert check["unsupported_facts"] == []
    assert check["missing_citation"] is False
    assert check["unsupported_citation_facts"] == ["annual leave", "sick leave"]
    assert check["unsupported_answer"] is True


def test_answer_evaluation_requires_abstention_for_unanswerable_case():
    case = next(case for case in load_cases() if case["id"] == "annual-leave-duration")
    answer = evaluate_answer(case, "Annual leave is 30 days. [S1]", [], [leave_result()], 0.25)
    abstention = evaluate_answer(case, INSUFFICIENT_ANSWER, [], [leave_result()], 0.25)

    assert answer["unsupported_answer"] is True
    assert abstention["unsupported_answer"] is False
    assert abstention["correct_abstention"] is True


@pytest.mark.parametrize(
    "case_id,raw_answer",
    [
        (
            "annual-leave-duration",
            "The policy does not specify the number of days of annual leave. [S1]",
        ),
        (
            "parental-leave",
            "The company's parental leave allowance is not explicitly stated "
            "in the provided evidence.",
        ),
    ],
)
def test_benchmark_absence_phrases_are_correct_abstentions(
    case_id, raw_answer
):
    case = next(case for case in load_cases() if case["id"] == case_id)
    # API cleanup standardizes recognized abstentions and returns no citations;
    # the raw model answer may still contain a valid retrieved source marker.
    check = evaluate_answer(case, raw_answer, [], [leave_result()], 0.25)

    assert check["correct_abstention"] is True
    assert check["unsupported_answer"] is False
    assert check["invalid_source_ids"] == []


def test_answer_check_summary_counts_failures():
    summary = summarize_answer_checks([
        {"missing_citation": True, "invalid_source_ids": [], "unsupported_answer": True},
        {"missing_citation": False, "invalid_source_ids": ["S9"], "unsupported_answer": False,
         "invalid_citations": [], "expected_facts_absent": [], "correct_abstention": True},
    ])

    assert summary["missing_citations"] == 1
    assert summary["cases_with_invalid_source_ids"] == 1
    assert summary["unsupported_answers"] == 1
    assert summary["correct_abstentions"] == 1


def test_answer_diagnostic_shows_raw_and_api_citations_without_document_excerpts():
    raw_answer = "Annual and sick leave are available. [S1]"
    api_result = {
        "answer": raw_answer,
        "citations": [{"source_id": "S1", "excerpt": "private document text"}],
        "insufficient_evidence": False,
    }

    diagnostic = _answer_diagnostic("leave-types", raw_answer, api_result)

    assert diagnostic["case_id"] == "leave-types"
    assert diagnostic["raw_answer"] == raw_answer
    assert diagnostic["raw_answer_source_ids"] == ["S1"]
    assert diagnostic["api_answer_source_ids"] == ["S1"]
    assert diagnostic["returned_citation_source_ids"] == ["S1"]
    assert "excerpt" not in diagnostic
    assert "private document text" not in repr(diagnostic)


def test_answer_diagnostic_exposes_missing_raw_citation_and_truncates_answer():
    raw_answer = "Annual leave is available. " + ("details " * 100)
    api_result = {
        "answer": "Annual leave is available. [S1]",
        "citations": [{"source_id": "S1"}],
        "insufficient_evidence": False,
    }

    diagnostic = _answer_diagnostic("leave-types", raw_answer, api_result)

    assert diagnostic["raw_answer_truncated"] is True
    assert len(diagnostic["raw_answer"]) == 500
    assert diagnostic["raw_answer_source_ids"] == []
    assert diagnostic["api_answer_source_ids"] == ["S1"]
    assert diagnostic["returned_citation_source_ids"] == ["S1"]
