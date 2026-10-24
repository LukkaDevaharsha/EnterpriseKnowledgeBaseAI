import pytest

from flask_jwt_extended import create_access_token

from app import db
from app.models import User
from app.services import rag_service, semantic_search
from app.services.ollama_client import OllamaUnavailableError


def user_header(app):
    with app.app_context():
        user = User(name="General User", email="general@example.com",
                    employee_id="GENERAL1", department="Research",
                    role="EMPLOYEE", is_active=True, is_verified=True,
                    password_hash="test-hash")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
        return {"Authorization": f"Bearer {token}"}


def test_general_question_returns_explicitly_general_answer_with_no_citations(
    client, app, monkeypatch
):
    headers = user_header(app)
    calls = []
    # General answers must not depend on retrieval or be diverted by unrelated
    # high-scoring chunks into the citation-required response path.
    monkeypatch.setattr(
        rag_service, "search_chunks",
        lambda *args: (_ for _ in ()).throw(AssertionError("general question searched documents")),
    )
    monkeypatch.setattr(
        rag_service, "generate_chat_answer",
        lambda question, evidence, prompt, model=None: calls.append(
            (evidence, prompt, model)
        ) or "An API lets software systems communicate.",
    )
    response = client.post("/api/ask", headers=headers,
                           json={"question": "Explain what an API is."})
    assert response.status_code == 200
    body = response.get_json()
    assert body["answer_type"] == "general"
    assert body["insufficient_evidence"] is False
    assert body["citations"] == []
    assert body["answer"].startswith("General information (not company policy):")
    assert calls[0][0] == "[]"
    assert calls[0][2] == app.config["GENERAL_AI_MODEL"]


@pytest.mark.parametrize(
    "question",
    [
        "What is blockchain?",
        "Whta is machne lerning?",
        "Explain the difference between Java and JavaScript.",
    ],
)
def test_main_baseai_general_intents_do_not_route_through_company_documents(
    client, app, monkeypatch, question
):
    headers = user_header(app)
    calls = []
    monkeypatch.setattr(
        rag_service, "search_chunks",
        lambda *args, **kwargs: [{
            "chunk_id": 1, "document_id": 10, "document_title": "Unrelated policy",
            "document_type": "PDF", "chunk_index": 0,
            "content": "Unrelated company information.", "similarity_score": 0.99,
        }],
    )
    monkeypatch.setattr(
        rag_service, "generate_chat_answer",
        lambda actual_question, evidence, prompt, model=None: calls.append(
            (actual_question, evidence, prompt, model)
        ) or "A general answer from the configured model.",
    )

    response = client.post(
        "/api/ask", headers=headers,
        json={"question": question, "top_k": 5},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["answer_type"] == "general"
    assert body["insufficient_evidence"] is False
    assert body["citations"] == []
    assert calls[0][0] == question
    assert calls[0][1] == "[]"
    assert calls[0][3] == app.config["GENERAL_AI_MODEL"]


@pytest.mark.parametrize(
    "question",
    ["Hi, how are you?", "Hello!", "How are you doing today?", "How's it going?"],
)
def test_social_greetings_are_stable_without_retrieval_or_model(
    client, app, monkeypatch, question
):
    headers = user_header(app)
    monkeypatch.setattr(
        rag_service, "search_chunks",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("social greeting searched company documents")
        ),
    )
    monkeypatch.setattr(
        rag_service, "generate_chat_answer",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("social greeting invoked the model validator path")
        ),
    )

    responses = [
        client.post("/api/ask", headers=headers, json={"question": question})
        for _ in range(2)
    ]

    bodies = [response.get_json() for response in responses]
    assert all(response.status_code == 200 for response in responses)
    assert bodies[0] == bodies[1]
    assert bodies[0]["answer_type"] == "general"
    assert bodies[0]["insufficient_evidence"] is False
    assert bodies[0]["citations"] == []
    assert "ready to help" in bodies[0]["answer"]


def test_general_question_falls_back_when_retrieval_returns_no_chunks(
    client, app, monkeypatch
):
    headers = user_header(app)
    retrieval_calls = []
    monkeypatch.setattr(
        rag_service, "search_chunks",
        lambda *args, **kwargs: retrieval_calls.append((args, kwargs)) or [],
    )
    monkeypatch.setattr(
        rag_service, "generate_chat_answer",
        lambda question, evidence, prompt, model=None: (
            "A vector database stores vector representations."
        ),
    )

    response = client.post(
        "/api/ask", headers=headers,
        json={"question": "Can you tell me about vector databases?"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["answer_type"] == "general"
    assert body["insufficient_evidence"] is False
    assert body["citations"] == []
    assert retrieval_calls


@pytest.mark.parametrize(
    "question",
    [
        "What is our company's leave policy?",
        "How many days of annual leave does the policy grant?",
        "How many days of annual leave does the company provide?",
        "How many days of annual leave do I get?",
    ],
)
def test_company_specific_question_without_evidence_abstains(
    client, app, monkeypatch, question
):
    headers = user_header(app)
    calls = []
    monkeypatch.setattr(rag_service, "generate_chat_answer",
                        lambda *args: calls.append(args) or "Should not run")
    response = client.post("/api/ask", headers=headers,
                           json={"question": question})
    body = response.get_json()
    assert response.status_code == 200
    assert body["answer_type"] == "insufficient_evidence"
    assert body["insufficient_evidence"] is True
    assert body["citations"] == []
    assert calls == []


def test_general_model_failure_returns_existing_safe_service_error(client, app, monkeypatch):
    headers = user_header(app)
    monkeypatch.setattr(rag_service, "generate_chat_answer",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            OllamaUnavailableError("offline")
                        ))
    response = client.post("/api/ask", headers=headers,
                           json={"question": "What is a vector database?"})
    assert response.status_code == 503
    assert response.get_json()["status"] == "error"
