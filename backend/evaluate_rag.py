"""Run the versioned RAG baseline against one user's indexed documents."""

import argparse
import json
import re
from pathlib import Path

from app import create_app, db
from app.models import Document, User
from app.rag.evaluation import (
    evaluate_answer,
    evaluate_retrieval,
    summarize_answer_checks,
)
from app.services import rag_service
from app.services.rag_service import answer_question
from app.services.semantic_search import MAX_LIMIT, search_chunks


DEFAULT_DATASET = Path(__file__).parent / "evaluation" / "rag_cases.json"
SOURCE_ID_RE = re.compile(r"\[S(\d+)\]")
DIAGNOSTIC_TEXT_LIMIT = 500


def _source_ids(answer):
    return list(dict.fromkeys(
        f"S{match.group(1)}" for match in SOURCE_ID_RE.finditer(answer or "")
    ))


def _answer_diagnostic(case_id, raw_answer, api_result):
    """Return opt-in, truncated answer text and citation IDs (never excerpts)."""
    api_answer = api_result.get("answer", "")
    return {
        "case_id": case_id,
        "raw_answer": raw_answer[:DIAGNOSTIC_TEXT_LIMIT],
        "raw_answer_truncated": len(raw_answer) > DIAGNOSTIC_TEXT_LIMIT,
        "raw_answer_source_ids": _source_ids(raw_answer),
        "api_answer": api_answer[:DIAGNOSTIC_TEXT_LIMIT],
        "api_answer_truncated": len(api_answer) > DIAGNOSTIC_TEXT_LIMIT,
        "api_answer_source_ids": _source_ids(api_answer),
        "returned_citation_source_ids": [
            item.get("source_id") for item in api_result.get("citations", [])
            if isinstance(item, dict) and isinstance(item.get("source_id"), str)
        ],
        "insufficient_evidence": api_result.get("insufficient_evidence"),
    }


def _load_cases(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError("Evaluation dataset must contain a non-empty cases list.")
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError("Every evaluation case must have a string id.")
        if case["id"] in ids:
            raise ValueError(f"Duplicate evaluation case id: {case['id']}")
        ids.add(case["id"])
        if not isinstance(case.get("answerable"), bool):
            raise ValueError(f"Case {case['id']} must set answerable to true or false.")
        if not isinstance(case.get("expected_facts"), list):
            raise ValueError(f"Case {case['id']} must provide expected_facts.")
        if not isinstance(case.get("supporting_chunks"), list):
            raise ValueError(f"Case {case['id']} must provide supporting_chunks.")
        if case["answerable"] and not case["supporting_chunks"]:
            raise ValueError(f"Answerable case {case['id']} needs supporting chunks.")
        if not case["answerable"] and case["supporting_chunks"]:
            raise ValueError(f"Unanswerable case {case['id']} cannot list supporting chunks.")
    return payload, cases


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=int, required=True,
                        help="Owner ID whose document corpus will be evaluated")
    parser.add_argument("--top-k", type=int, default=5,
                        help=f"Retrieval depth (1-{MAX_LIMIT}; default: 5)")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET,
                        help="Path to a versioned RAG evaluation JSON dataset")
    parser.add_argument("--evaluate-answers", action="store_true",
                        help="Also call configured local Ollama and check answers/citations")
    parser.add_argument(
        "--diagnostics", action="store_true",
        help=("With --evaluate-answers, print each raw/API answer (first 500 chars) "
              "and parsed source IDs; does not print document excerpts"),
    )
    args = parser.parse_args()
    if args.diagnostics and not args.evaluate_answers:
        parser.error("--diagnostics requires --evaluate-answers")
    if not 1 <= args.top_k <= MAX_LIMIT:
        parser.error(f"--top-k must be between 1 and {MAX_LIMIT}")
    return args


def main():
    args = _parse_args()
    dataset, cases = _load_cases(args.dataset)
    app = create_app()
    with app.app_context():
        if args.top_k > app.config["RAG_MAX_TOP_K"]:
            raise SystemExit(
                f"--top-k cannot exceed configured RAG_MAX_TOP_K="
                f"{app.config['RAG_MAX_TOP_K']}."
            )
        user = db.session.get(User, args.user_id)
        if user is None or not user.is_active:
            raise SystemExit("The requested evaluation user does not exist or is inactive.")

        retrieved_by_id = {}

        def retrieve(question, top_k):
            results = search_chunks(question, user.id, top_k)
            document_ids = {result["document_id"] for result in results}
            filenames = {
                document_id: filename
                for document_id, filename in db.session.query(
                    Document.id, Document.original_filename
                ).filter(
                    Document.uploaded_by == user.id,
                    Document.id.in_(document_ids),
                ).all()
            } if document_ids else {}
            for result in results:
                result["original_filename"] = filenames.get(result["document_id"], "")
            retrieved_by_id[question] = results
            return results

        retrieval = evaluate_retrieval(
            cases,
            retrieve,
            args.top_k,
            app.config["RAG_MIN_SIMILARITY"],
        )
        report = {
            "dataset_name": dataset.get("dataset_name"),
            "dataset_version": dataset.get("dataset_version"),
            "user_id": user.id,
            "top_k": args.top_k,
            "similarity_threshold": app.config["RAG_MIN_SIMILARITY"],
            "retrieval": retrieval,
        }

        if args.evaluate_answers:
            original_generate = rag_service.generate_chat_answer
            answer_checks = []
            answer_diagnostics = []
            try:
                for case in cases:
                    captured = {}

                    def capture_answer(question, evidence, system_prompt):
                        answer = original_generate(question, evidence, system_prompt)
                        captured["raw_answer"] = answer
                        return answer

                    rag_service.generate_chat_answer = capture_answer
                    api_result = answer_question(case["question"], user.id, args.top_k)
                    raw_answer = captured.get("raw_answer", api_result["answer"])
                    if args.diagnostics:
                        answer_diagnostics.append(_answer_diagnostic(
                            case["id"], raw_answer, api_result
                        ))
                    answer_checks.append(evaluate_answer(
                        case,
                        raw_answer,
                        api_result["citations"],
                        retrieved_by_id.get(case["question"], []),
                        app.config["RAG_MIN_SIMILARITY"],
                    ))
            finally:
                rag_service.generate_chat_answer = original_generate
            report["answers"] = summarize_answer_checks(answer_checks)
            if args.diagnostics:
                report["answer_diagnostics"] = answer_diagnostics

        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
