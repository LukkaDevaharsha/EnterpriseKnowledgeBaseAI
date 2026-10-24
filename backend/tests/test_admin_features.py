from io import BytesIO
import os

from flask_jwt_extended import create_access_token

from app import db
from app.models import AuditEvent, Document, DocumentChunk, User


def make_user(app, email, employee_id, role="EMPLOYEE"):
    with app.app_context():
        user = User(
            name=email.split("@")[0], email=email, employee_id=employee_id,
            department="Engineering", role=role, is_active=True, is_verified=True,
            password_hash="test-hash",
        )
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
        return {"Authorization": f"Bearer {token}"}, user.id


def test_admin_apis_reject_anonymous_and_employee(client, app):
    employee, _ = make_user(app, "employee-admin-test@example.com", "ADM-EMP")
    assert client.get("/api/admin/stats").status_code == 401
    assert client.get("/api/admin/stats", headers=employee).status_code == 403


def test_bootstrap_admin_is_repeatable_and_never_echoes_password(app):
    runner = app.test_cli_runner()
    first = runner.invoke(
        args=["bootstrap-admin", "--email", "first-admin@example.com",
              "--name", "First Admin", "--department", "IT"],
        input="OnlyLocalTestPassword123!\nOnlyLocalTestPassword123!\n",
    )
    assert first.exit_code == 0, first.output
    assert "OnlyLocalTestPassword123!" not in first.output
    second = runner.invoke(
        args=["bootstrap-admin", "--email", "another@example.com",
              "--name", "Ignored", "--department", "IT"],
    )
    assert second.exit_code == 0
    assert "already exists" in second.output
    with app.app_context():
        assert User.query.filter_by(role="ADMIN").count() == 1


def test_development_seed_is_idempotent_and_uses_generated_ids(app):
    runner = app.test_cli_runner()
    first = runner.invoke(args=["seed-dev-employees"],
                          input="LocalOnlyTestPassword123!\nLocalOnlyTestPassword123!\n")
    assert first.exit_code == 0, first.output
    assert "3 new" in first.output
    second = runner.invoke(args=["seed-dev-employees"],
                           input="AnotherLocalTestPassword123!\nAnotherLocalTestPassword123!\n")
    assert second.exit_code == 0, second.output
    assert "0 new" in second.output
    assert "LocalOnlyTestPassword123!" not in first.output
    with app.app_context():
        samples = User.query.filter(User.email.like("%@example.test")).all()
        assert len(samples) == 3
        assert all(user.role == "EMPLOYEE" and user.is_verified for user in samples)
        assert all(user.employee_id.startswith("EMP") for user in samples)


def test_last_active_admin_cannot_be_demoted_or_deactivated(client, app):
    admin, admin_id = make_user(app, "only-admin@example.com", "ADM-ONE", role="ADMIN")
    response = client.patch(f"/api/admin/employees/{admin_id}", headers=admin,
                            json={"is_active": False})
    assert response.status_code == 409
    response = client.patch(f"/api/admin/employees/{admin_id}", headers=admin,
                            json={"role": "EMPLOYEE"})
    assert response.status_code == 409


def test_admin_cannot_deactivate_own_account_when_other_admin_exists(client, app):
    admin_headers, admin_id = make_user(
        app, "self-deactivate-admin@example.com", "ADM-SELF-DEACTIVATE", role="ADMIN"
    )
    make_user(app, "backup-admin@example.com", "ADM-BACKUP", role="ADMIN")

    response = client.patch(
        f"/api/admin/employees/{admin_id}", headers=admin_headers,
        json={"is_active": False},
    )

    assert response.status_code == 409
    assert "own account" in response.get_json()["message"]
    with app.app_context():
        assert db.session.get(User, admin_id).is_active is True


def test_admin_cannot_change_own_role_even_if_another_admin_exists(client, app):
    admin_headers, admin_id = make_user(app, "self-role-admin@example.com", "ADM-SELF", role="ADMIN")
    make_user(app, "second-role-admin@example.com", "ADM-SECOND", role="ADMIN")

    response = client.patch(f"/api/admin/employees/{admin_id}", headers=admin_headers,
                            json={"role": "EMPLOYEE"})

    assert response.status_code == 409
    assert "own role" in response.get_json()["message"]
    with app.app_context():
        assert db.session.get(User, admin_id).role == "ADMIN"


def test_admin_cannot_grant_admin_role_to_another_employee(client, app):
    admin_headers, _ = make_user(app, "grant-role-admin@example.com", "ADM-GRANT", role="ADMIN")
    _, employee_id = make_user(app, "grant-role-employee@example.com", "EMP-GRANT")

    response = client.patch(f"/api/admin/employees/{employee_id}", headers=admin_headers,
                            json={"role": "ADMIN"})

    assert response.status_code == 403
    with app.app_context():
        assert db.session.get(User, employee_id).role == "EMPLOYEE"


def test_admin_cannot_assign_manager_role(client, app):
    """MANAGER is no longer a valid role; the endpoint must reject it."""
    admin_headers, _ = make_user(app, "assign-role-admin@example.com", "ADM-ASSIGN", role="ADMIN")
    _, employee_id = make_user(app, "assign-role-employee@example.com", "EMP-ASSIGN")

    response = client.patch(f"/api/admin/employees/{employee_id}", headers=admin_headers,
                            json={"role": "MANAGER"})

    assert response.status_code == 400
    assert "EMPLOYEE" in response.get_json()["message"]
    with app.app_context():
        assert db.session.get(User, employee_id).role == "EMPLOYEE"


def test_admin_can_assign_employee_role_to_employee(client, app):
    """Assigning EMPLOYEE (no-op) is still accepted; confirms role endpoint works."""
    admin_headers, _ = make_user(app, "assign-emp-admin@example.com", "ADM-ASSIGNE", role="ADMIN")
    _, employee_id = make_user(app, "assign-emp-employee@example.com", "EMP-ASSIGNE")

    response = client.patch(f"/api/admin/employees/{employee_id}", headers=admin_headers,
                            json={"role": "EMPLOYEE"})

    assert response.status_code == 200
    assert response.get_json()["employee"]["role"] == "EMPLOYEE"


def test_admin_shared_document_is_indexed_and_searchable_by_employee(client, app, monkeypatch):
    from app.services import rag_service, semantic_search

    admin_headers, admin_id = make_user(app, "shared-admin@example.com", "ADM-SHARED", role="ADMIN")
    employee_headers, _ = make_user(app, "shared-employee@example.com", "EMP-SHARED")
    private_upload = client.post(
        "/api/documents", headers=admin_headers,
        data={"file": (BytesIO(b"Private administrator working notes."), "private.txt")},
        content_type="multipart/form-data",
    )
    assert private_upload.status_code == 201, private_upload.get_json()
    private_document_id = private_upload.get_json()["document"]["id"]

    content = b"Company travel policy reimburses economy rail fares with manager approval."
    uploaded = client.post("/api/admin/documents", headers=admin_headers,
                           data={"file": (BytesIO(content), "travel.txt"),
                                 "title": "Travel policy"},
                           content_type="multipart/form-data")
    assert uploaded.status_code == 201, uploaded.get_json()
    document = uploaded.get_json()["document"]
    assert document["is_shared"] is True
    assert document["status"] == "PROCESSED"
    library = client.get("/api/admin/documents", headers=admin_headers)
    assert library.status_code == 200
    library_docs = library.get_json()["documents"]
    assert [item["id"] for item in library_docs] == [document["id"]]
    assert library_docs[0]["is_shared"] is True
    forbidden_delete = client.delete(
        f"/api/admin/documents/{document['id']}", headers=employee_headers
    )
    assert forbidden_delete.status_code == 403

    vector = [1.0] + [0.0] * 383
    monkeypatch.setattr(semantic_search, "generate_embeddings", lambda *args, **kwargs: [vector])
    search = client.post("/api/search", headers=employee_headers,
                         json={"query": "rail fare reimbursement", "limit": 5})
    assert search.status_code == 200
    assert any(hit["document_id"] == document["id"] for hit in search.get_json()["results"])
    assert all(hit["document_id"] != private_document_id
               for hit in search.get_json()["results"])

    monkeypatch.setattr(rag_service, "generate_chat_answer",
                        lambda *args, **kwargs: "Economy rail fares are reimbursed with manager approval. [S1]")
    answer = client.post("/api/ask", headers=employee_headers,
                         json={"question": "How are rail fares reimbursed?"})
    assert answer.status_code == 200
    body = answer.get_json()
    assert body["answer_type"] == "document_grounded"
    assert body["citations"][0]["document_id"] == document["id"]

    with app.app_context():
        stored = db.session.get(Document, document["id"])
        private_stored = db.session.get(Document, private_document_id)
        assert stored.uploaded_by == admin_id
        assert stored.is_shared is True
        assert private_stored.is_shared is False
        assert DocumentChunk.query.filter_by(document_id=stored.id, embedding_status="PROCESSED").count() == 1
        assert AuditEvent.query.filter_by(action="shared_document.upload").count() == 1


def test_shared_leave_policy_retrieval_builds_grounded_context_for_employee(
    client, app, monkeypatch
):
    import json

    from app.services import rag_service, semantic_search

    admin_headers, admin_id = make_user(
        app, "leave-shared-admin@example.com", "ADM-LEAVE", role="ADMIN"
    )
    employee_headers, _ = make_user(
        app, "leave-reader@example.com", "EMP-LEAVE"
    )
    private_headers, _ = make_user(
        app, "leave-private-owner@example.com", "EMP-PRIVATE"
    )
    policy_text = (
        "Employees may take annual leave and sick leave under the company leave policy."
    )
    shared_upload = client.post(
        "/api/admin/documents", headers=admin_headers,
        data={"file": (BytesIO(policy_text.encode()), "leave_policy.txt")},
        content_type="multipart/form-data",
    )
    assert shared_upload.status_code == 201, shared_upload.get_json()
    shared_doc = shared_upload.get_json()["document"]

    private_upload = client.post(
        "/api/documents", headers=private_headers,
        data={"file": (BytesIO(policy_text.encode()), "private_leave.txt")},
        content_type="multipart/form-data",
    )
    assert private_upload.status_code == 201, private_upload.get_json()
    private_doc_id = private_upload.get_json()["document"]["id"]
    my_files = client.get("/api/documents", headers=employee_headers)
    assert my_files.status_code == 200
    assert all(item["id"] != shared_doc["id"]
               for item in my_files.get_json()["documents"])

    with app.app_context():
        persisted = db.session.get(Document, shared_doc["id"])
        assert persisted.is_shared is True
        assert persisted.status == "PROCESSED"
        assert persisted.uploaded_by == admin_id
        chunk = DocumentChunk.query.filter_by(document_id=persisted.id).one()
        assert chunk.content == policy_text
        assert chunk.embedding_status == "PROCESSED"
        assert chunk.embedding_model == app.config["EMBEDDING_MODEL_NAME"]
        assert len(chunk.embedding) == 384
        private_persisted = db.session.get(Document, private_doc_id)
        assert private_persisted.is_shared is False

    vector = [1.0] + [0.0] * 383
    monkeypatch.setattr(
        semantic_search, "generate_embeddings",
        lambda *args, **kwargs: [vector],
    )
    search = client.post(
        "/api/search", headers=employee_headers,
        json={"query": "How many days of annual leave does the company provide?", "limit": 5},
    )
    assert search.status_code == 200
    hits = search.get_json()["results"]
    assert hits and hits[0]["document_id"] == shared_doc["id"]
    assert all(hit["document_id"] != private_doc_id for hit in hits)

    captured = {}

    def answer_model(question, evidence_json, system_prompt, model=None):
        captured["question"] = question
        captured["evidence"] = json.loads(evidence_json)
        captured["system_prompt"] = system_prompt
        captured["model"] = model
        return "The policy says employees may take annual leave. [S1]"

    monkeypatch.setattr(rag_service, "generate_chat_answer", answer_model)
    response = client.post(
        "/api/ask", headers=employee_headers,
        json={"question": "How many days of annual leave does the company provide?"},
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["answer_type"] == "document_grounded"
    assert body["insufficient_evidence"] is False
    assert body["citations"][0]["document_id"] == shared_doc["id"]
    assert captured["evidence"][0]["excerpt"] == policy_text
    assert captured["evidence"][0]["document_id"] == shared_doc["id"]
    assert "Cite every factual claim" in captured["system_prompt"]
    assert captured["model"] == app.config["COMPANY_KNOWLEDGE_MODEL"]


def test_admin_shared_document_delete_cleans_file_and_chunks(client, app):
    admin, _ = make_user(app, "delete-admin@example.com", "ADM-DEL", role="ADMIN")
    response = client.post("/api/admin/documents", headers=admin,
                           data={"file": (BytesIO(b"delete this policy"), "delete.txt")},
                           content_type="multipart/form-data")
    assert response.status_code == 201
    document_id = response.get_json()["document"]["id"]
    with app.app_context():
        document = db.session.get(Document, document_id)
        path = os.path.join(app.config["DOCUMENT_STORAGE_PATH"], document.stored_filename)
        assert os.path.isfile(path)
    removed = client.delete(f"/api/admin/documents/{document_id}", headers=admin)
    assert removed.status_code == 200
    with app.app_context():
        assert db.session.get(Document, document_id) is None
        assert DocumentChunk.query.filter_by(document_id=document_id).count() == 0
        assert not os.path.exists(path)


def test_failed_shared_indexing_is_reported_and_not_searchable(client, app, monkeypatch):
    from app.services import document_workflow

    admin, _ = make_user(app, "failed-index-admin@example.com", "ADM-FAIL", role="ADMIN")
    monkeypatch.setattr(document_workflow, "process_document_embeddings", lambda _document_id: False)
    response = client.post(
        "/api/admin/documents", headers=admin,
        data={"file": (BytesIO(b"shared document with failed indexing"), "failed.txt")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 202
    body = response.get_json()
    assert body["status"] == "warning"
    assert "not searchable" in body["message"]
    assert body["document"]["status"] == "PROCESSING_FAILED"
    with app.app_context():
        document = db.session.get(Document, body["document"]["id"])
        assert document.is_shared is True
        assert DocumentChunk.query.filter_by(document_id=document.id).count() == 1
        assert DocumentChunk.query.filter_by(
            document_id=document.id, embedding_status="PROCESSED"
        ).count() == 0
