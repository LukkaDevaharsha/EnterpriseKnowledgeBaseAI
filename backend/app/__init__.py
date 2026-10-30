import os
import math
import tempfile
from datetime import timedelta
from urllib.parse import urlsplit, urlparse

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.engine import URL
import click


load_dotenv(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
)

db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()


def _parse_cors_origins(value, production=False):
    """Parse and validate a comma-separated list of browser origins."""
    if not value or not value.strip():
        if production:
            raise RuntimeError(
                "CORS_ALLOWED_ORIGINS must be configured in production."
            )
        return []

    origins = []
    for candidate in value.split(","):
        origin = candidate.strip()
        if not origin or origin == "*":
            raise RuntimeError("CORS_ALLOWED_ORIGINS contains an invalid origin.")
        try:
            parsed = urlsplit(origin)
            port = parsed.port
        except ValueError:
            raise RuntimeError(
                "CORS_ALLOWED_ORIGINS contains an invalid origin."
            ) from None

        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or "*" in parsed.netloc
            or "\\" in origin
            or any(character.isspace() for character in origin)
            or (port is not None and not 1 <= port <= 65535)
            or (production and parsed.scheme.lower() != "https")
        ):
            raise RuntimeError("CORS_ALLOWED_ORIGINS contains an invalid origin.")

        hostname = parsed.hostname.lower()
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        default_port = 443 if parsed.scheme.lower() == "https" else 80
        netloc = hostname if port is None or port == default_port else f"{hostname}:{port}"
        normalized = f"{parsed.scheme.lower()}://{netloc}"
        if normalized not in origins:
            origins.append(normalized)

    if production and not origins:
        raise RuntimeError("CORS_ALLOWED_ORIGINS must be configured in production.")
    return origins


def _validate_document_storage(path):
    """Create the storage directory and verify it is writable without logging its path."""
    try:
        os.makedirs(path, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".storage-write-check-", dir=path
        ):
            pass
    except OSError:
        raise RuntimeError(
            "DOCUMENT_STORAGE_PATH must be a writable directory."
        ) from None


def create_app(config_overrides=None):
    """Create and configure the Flask application."""
    app = Flask(__name__)

    app_environment = os.getenv("APP_ENV", "development").strip().lower()
    if app_environment not in {"development", "test", "production"}:
        raise RuntimeError(
            "APP_ENV must be one of: development, test, production."
        )
    production_mode = app_environment == "production"
    debug_default = "true" if app_environment == "development" else "false"
    debug_value = os.getenv("FLASK_DEBUG", debug_default).strip().lower()
    if debug_value not in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
        raise RuntimeError("FLASK_DEBUG must be a boolean value.")
    debug_enabled = app_environment == "development" and debug_value in {
        "1", "true", "yes", "on"
    }
    app.config["APP_ENV"] = app_environment
    app.config["DEBUG"] = debug_enabled

    jwt_secret_key = os.getenv("JWT_SECRET_KEY")

    if not jwt_secret_key:
        raise RuntimeError(
            "JWT_SECRET_KEY is missing from the backend .env file."
        )

    app.config["JWT_SECRET_KEY"] = jwt_secret_key

    try:
        token_expiration_minutes = int(
            os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", "30")
        )
    except ValueError as exc:
        raise RuntimeError(
            "JWT_ACCESS_TOKEN_EXPIRES_MINUTES must be an integer."
        ) from exc

    if token_expiration_minutes <= 0:
        raise RuntimeError(
            "JWT_ACCESS_TOKEN_EXPIRES_MINUTES must be greater than zero."
        )

    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(
        minutes=token_expiration_minutes
    )

    db_user = os.getenv("DB_USER", "postgres")
    db_password = os.getenv("DB_PASSWORD", "")
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = int(os.getenv("DB_PORT", "5432"))
    db_name = os.getenv("DB_NAME", "enterprise_knowledge_base")
    db_sslmode = os.getenv("DB_SSLMODE", "").strip()
    database_url_options = {"query": {"sslmode": db_sslmode}} if db_sslmode else {}
    app.config["SQLALCHEMY_DATABASE_URI"] = URL.create(
        drivername="postgresql+psycopg",
        username=db_user,
        password=db_password,
        host=db_host,
        port=db_port,
        database=db_name,
        **database_url_options,
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Keep uploaded files outside the backend and frontend public directories.
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(__file__))
    )

    default_storage_path = os.path.join(project_root, "storage", "documents")
    app.config["DOCUMENT_STORAGE_PATH"] = (
        os.getenv("DOCUMENT_STORAGE_PATH") or default_storage_path
    )
    app.config.update({
        "STORAGE_BACKEND": os.getenv("STORAGE_BACKEND", "local").strip().lower(),
        "S3_ENDPOINT_URL": os.getenv(
            "S3_ENDPOINT_URL",
            "https://ixkkqeyzopkbdcfnzwye.storage.supabase.co/storage/v1/s3",
        ).strip(),
        "S3_REGION": os.getenv("S3_REGION", "ap-southeast-1").strip(),
        "S3_BUCKET": os.getenv(
            "S3_BUCKET", "enterprise-knowledge-base-docs"
        ).strip(),
        "S3_ACCESS_KEY_ID": os.getenv("S3_ACCESS_KEY_ID", ""),
        "S3_SECRET_ACCESS_KEY": os.getenv("S3_SECRET_ACCESS_KEY", ""),
    })

    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
    app.config["EMBEDDING_MODEL_NAME"] = os.getenv(
        "EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2"
    )
    app.config["EMBEDDING_PROVIDER"] = os.getenv(
        "EMBEDDING_PROVIDER", "sentence_transformers"
    )
    app.config["GEMINI_EMBEDDING_MODEL"] = os.getenv(
        "GEMINI_EMBEDDING_MODEL", "gemini-embedding-2"
    )
    try:
        embedding_dimension = int(os.getenv("EMBEDDING_DIMENSION", "384"))
    except ValueError as exc:
        raise RuntimeError("EMBEDDING_DIMENSION must be an integer.") from exc
    if embedding_dimension != 384:
        raise RuntimeError(
            "The current document_chunks schema supports only 384-dimensional embeddings."
        )
    app.config["EMBEDDING_DIMENSION"] = embedding_dimension

    app.config["OLLAMA_BASE_URL"] = os.getenv(
        "OLLAMA_BASE_URL", "http://localhost:11434"
    ).rstrip("/")
    app.config["OLLAMA_MODEL"] = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    app.config["LLM_PROVIDER"] = os.getenv("LLM_PROVIDER", "ollama")
    app.config["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY", "")
    app.config["GEMINI_MODEL"] = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    app.config["GEMINI_TIMEOUT_SECONDS"] = float(
        os.getenv("GEMINI_TIMEOUT_SECONDS", os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))
    )
    app.config["EMAIL_PROVIDER"] = os.getenv("EMAIL_PROVIDER", "smtp")
    app.config["RESEND_API_KEY"] = os.getenv("RESEND_API_KEY", "")
    app.config["RESEND_FROM_EMAIL"] = os.getenv("RESEND_FROM_EMAIL", "")
    app.config["RESEND_TIMEOUT_SECONDS"] = float(
        os.getenv("RESEND_TIMEOUT_SECONDS", "10")
    )
    app.config["SMTP_HOST"] = os.getenv("SMTP_HOST", "")
    app.config["SMTP_PORT"] = int(os.getenv("SMTP_PORT", "587"))
    app.config["SMTP_USERNAME"] = os.getenv("SMTP_USERNAME", "")
    app.config["SMTP_PASSWORD"] = os.getenv("SMTP_PASSWORD", "")
    app.config["SMTP_FROM"] = os.getenv("SMTP_FROM", "")
    app.config["SMTP_USE_TLS"] = os.getenv("SMTP_USE_TLS", "true").lower() in {
        "1", "true", "yes", "on"
    }
    app.config["SMTP_TIMEOUT_SECONDS"] = float(os.getenv("SMTP_TIMEOUT_SECONDS", "10"))
    try:
        app.config["OLLAMA_TIMEOUT_SECONDS"] = float(
            os.getenv("OLLAMA_TIMEOUT_SECONDS", "60")
        )
        app.config["RAG_DEFAULT_TOP_K"] = int(
            os.getenv("RAG_DEFAULT_TOP_K", "5")
        )
        app.config["RAG_MAX_TOP_K"] = int(os.getenv("RAG_MAX_TOP_K", "10"))
        app.config["RAG_MAX_CONTEXT_CHARS"] = int(
            os.getenv("RAG_MAX_CONTEXT_CHARS", "12000")
        )
        app.config["RAG_MIN_SIMILARITY"] = float(
            os.getenv("RAG_MIN_SIMILARITY", "0.25")
        )
    except ValueError as exc:
        raise RuntimeError("Invalid RAG or Ollama configuration value.") from exc

    ollama_url = urlparse(app.config["OLLAMA_BASE_URL"])
    if ollama_url.scheme not in {"http", "https"} or not ollama_url.netloc:
        raise RuntimeError("OLLAMA_BASE_URL must be a valid HTTP or HTTPS URL.")
    if not app.config["OLLAMA_MODEL"].strip():
        raise RuntimeError("OLLAMA_MODEL must not be empty.")
    if not math.isfinite(app.config["OLLAMA_TIMEOUT_SECONDS"]) or app.config[
        "OLLAMA_TIMEOUT_SECONDS"
    ] <= 0:
        raise RuntimeError("OLLAMA_TIMEOUT_SECONDS must be greater than zero.")
    if not 1 <= app.config["RAG_DEFAULT_TOP_K"] <= app.config["RAG_MAX_TOP_K"] <= 20:
        raise RuntimeError("RAG top_k configuration must satisfy 1 <= default <= max <= 20.")
    if app.config["RAG_MAX_CONTEXT_CHARS"] < 1000:
        raise RuntimeError("RAG_MAX_CONTEXT_CHARS must be at least 1000.")
    if not math.isfinite(app.config["RAG_MIN_SIMILARITY"]) or not -1 <= app.config[
        "RAG_MIN_SIMILARITY"
    ] <= 1:
        raise RuntimeError("RAG_MIN_SIMILARITY must be between -1 and 1.")

    if config_overrides:
        app.config.update(config_overrides)

    for provider_key, supported in (
        ("LLM_PROVIDER", {"ollama", "gemini"}),
        ("EMBEDDING_PROVIDER", {"sentence_transformers", "gemini"}),
        ("EMAIL_PROVIDER", {"smtp", "resend"}),
    ):
        selected = str(app.config.get(provider_key, "")).strip().lower()
        if selected not in supported:
            raise RuntimeError(f"{provider_key} must be one of: {', '.join(sorted(supported))}.")
        app.config[provider_key] = selected

    if app.config["EMBEDDING_PROVIDER"] == "gemini":
        if "EMBEDDING_MODEL_NAME" not in (config_overrides or {}):
            app.config["EMBEDDING_MODEL_NAME"] = app.config["GEMINI_EMBEDDING_MODEL"]
    if not isinstance(app.config["GEMINI_TIMEOUT_SECONDS"], (int, float)) or not math.isfinite(
        app.config["GEMINI_TIMEOUT_SECONDS"]
    ) or app.config["GEMINI_TIMEOUT_SECONDS"] <= 0:
        raise RuntimeError("GEMINI_TIMEOUT_SECONDS must be greater than zero.")
    if not isinstance(app.config["RESEND_TIMEOUT_SECONDS"], (int, float)) or not math.isfinite(
        app.config["RESEND_TIMEOUT_SECONDS"]
    ) or app.config["RESEND_TIMEOUT_SECONDS"] <= 0:
        raise RuntimeError("RESEND_TIMEOUT_SECONDS must be greater than zero.")

    for mode_model_key in (
        "GENERAL_AI_MODEL", "COMPANY_KNOWLEDGE_MODEL", "STUDY_PDF_MODEL",
    ):
        mode_model = (
            config_overrides.get(mode_model_key, os.getenv(mode_model_key, ""))
            if config_overrides is not None
            else os.getenv(mode_model_key, "")
        )
        default_mode_model = (
            app.config["GEMINI_MODEL"]
            if app.config["LLM_PROVIDER"] == "gemini"
            else app.config["OLLAMA_MODEL"]
        )
        app.config[mode_model_key] = (
            mode_model.strip()
            if isinstance(mode_model, str) and mode_model.strip()
            else default_mode_model
        )

    effective_environment = str(app.config.get("APP_ENV", "")).strip().lower()
    if effective_environment not in {"development", "test", "production"}:
        raise RuntimeError("APP_ENV must be one of: development, test, production.")
    app.config["APP_ENV"] = effective_environment
    production_mode = effective_environment == "production"

    if production_mode and len(app.config["JWT_SECRET_KEY"].encode("utf-8")) < 32:
        raise RuntimeError(
            "JWT_SECRET_KEY must contain at least 32 bytes in production."
        )

    storage_backend = str(app.config.get("STORAGE_BACKEND", "local")).strip().lower()
    if storage_backend not in {"local", "supabase_s3"}:
        raise RuntimeError("STORAGE_BACKEND must be local or supabase_s3.")
    app.config["STORAGE_BACKEND"] = storage_backend

    if storage_backend == "supabase_s3":
        s3_endpoint = app.config["S3_ENDPOINT_URL"]
        parsed_endpoint = urlparse(s3_endpoint)
        if (parsed_endpoint.scheme != "https" or not parsed_endpoint.hostname
                or parsed_endpoint.username is not None or parsed_endpoint.password is not None
                or parsed_endpoint.query or parsed_endpoint.fragment):
            raise RuntimeError("S3_ENDPOINT_URL must be a valid HTTPS endpoint.")
        if not app.config["S3_REGION"] or not app.config["S3_BUCKET"]:
            raise RuntimeError("S3_REGION and S3_BUCKET must be configured.")
        if not app.config["S3_ACCESS_KEY_ID"] or not app.config["S3_SECRET_ACCESS_KEY"]:
            raise RuntimeError("S3 access credentials must be configured.")

    configured_storage_path = app.config.get("DOCUMENT_STORAGE_PATH")
    explicit_storage_path = (
        bool(os.getenv("DOCUMENT_STORAGE_PATH", "").strip())
        or bool(
            config_overrides
            and str(config_overrides.get("DOCUMENT_STORAGE_PATH", "")).strip()
        )
    )
    if storage_backend == "local" and production_mode and not explicit_storage_path:
        raise RuntimeError(
            "DOCUMENT_STORAGE_PATH must be explicitly configured in production."
        )
    if storage_backend == "local":
        if not isinstance(configured_storage_path, (str, os.PathLike)) or not str(
            configured_storage_path
        ).strip():
            raise RuntimeError("DOCUMENT_STORAGE_PATH must be a non-empty directory path.")
        app.config["DOCUMENT_STORAGE_PATH"] = os.path.abspath(
            os.fspath(configured_storage_path)
        )
        _validate_document_storage(app.config["DOCUMENT_STORAGE_PATH"])

    cors_origins = _parse_cors_origins(
        os.getenv("CORS_ALLOWED_ORIGINS", ""), production=production_mode
    )
    app.config["CORS_ALLOWED_ORIGINS"] = cors_origins
    if cors_origins:
        CORS(app, resources={r"/api/*": {"origins": cors_origins}})

    # A production environment always disables Werkzeug's interactive debugger,
    # including when an override or FLASK_DEBUG requests it.
    if production_mode:
        app.config["DEBUG"] = False

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    # Import every model so SQLAlchemy and Flask-Migrate can discover them.
    from app.models import (  # noqa: F401
        AuditEvent, Document, DocumentChunk, RegistrationChallenge, User,
    )

    from app.services.employee_ids import next_employee_id

    @app.cli.command("bootstrap-admin")
    @click.option("--email", prompt=True, help="Administrator email address.")
    @click.option("--name", prompt=True, help="Administrator display name.")
    @click.option("--department", prompt=True, help="Administrator department.")
    def bootstrap_admin(email, name, department):
        """Create the initial verified ADMIN using a hidden password prompt."""
        from werkzeug.security import generate_password_hash

        from app.models import User

        if User.query.filter_by(role="ADMIN").count():
            click.echo("An administrator already exists; no account was changed.")
            return
        email = email.strip().lower()
        if User.query.filter_by(email=email).first():
            raise click.ClickException("That email already belongs to an account.")
        password = click.prompt("Administrator password", hide_input=True,
                                confirmation_prompt=True)
        if len(password) < 12 or len(password) > 128:
            raise click.ClickException("Password must be between 12 and 128 characters.")
        user = User(
            name=name.strip(), email=email, employee_id=next_employee_id(),
            department=department.strip(), role="ADMIN", is_active=True,
            is_verified=True, password_hash=generate_password_hash(password),
        )
        db.session.add(user)
        db.session.commit()
        click.echo(f"Administrator created with employee ID {user.employee_id}.")

    @app.cli.command("seed-dev-employees")
    def seed_dev_employees():
        """Idempotently seed three local employee accounts outside production."""
        from werkzeug.security import generate_password_hash

        from app.models import User

        if app.config["APP_ENV"] not in {"development", "test"}:
            raise click.ClickException("This command is available only in development/test.")
        password = click.prompt("Local test-account password (hidden)", hide_input=True,
                                confirmation_prompt=True)
        if len(password) < 8 or len(password) > 128:
            raise click.ClickException("Password must be between 8 and 128 characters.")
        samples = [
            ("Alex Morgan", "alex.morgan@example.test", "Engineering"),
            ("Priya Shah", "priya.shah@example.test", "Human Resources"),
            ("Jordan Kim", "jordan.kim@example.test", "Finance"),
        ]
        created = 0
        for name, email, department in samples:
            user = User.query.filter_by(email=email).first()
            if user is None:
                user = User(
                    name=name, email=email, employee_id=next_employee_id(),
                    department=department, role="EMPLOYEE", is_active=True,
                    is_verified=True, password_hash=generate_password_hash(password),
                )
                db.session.add(user)
                created += 1
        db.session.commit()
        click.echo(f"Seeded {created} new local employees; existing accounts were unchanged.")

    from app.services.shared_search import install_shared_search
    from app.services.rag_extensions import install_rag_extensions
    install_shared_search()
    install_rag_extensions()

    from app.routes.auth import auth_bp
    from app.routes.documents import documents_bp
    from app.routes.search import search_bp
    from app.routes.ask import ask_bp
    from app.routes.admin import admin_bp, shared_bp
    from app.services.chunk_embedding_pipeline import reembed_all_chunks

    app.register_blueprint(auth_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(ask_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(shared_bp)

    @app.cli.command("reembed-chunks")
    def reembed_chunks_command():
        """Retry missing embeddings or explicitly re-embed all chunks."""
        if not DocumentChunk.query.first():
            print("No document chunks found; nothing to re-embed.")
            return
        if reembed_all_chunks():
            print("All document chunks have embeddings for the configured model.")
        else:
            raise RuntimeError(
                "Some chunks could not be embedded. Check backend logs and retry."
            )

    @jwt.unauthorized_loader
    def handle_missing_token(error):
        return jsonify({
            "status": "error",
            "message": "Authentication token is missing or invalid.",
        }), 401

    @jwt.invalid_token_loader
    def handle_invalid_token(error):
        return jsonify({
            "status": "error",
            "message": "Authentication token is invalid or expired.",
        }), 401

    @jwt.expired_token_loader
    def handle_expired_token(jwt_header, jwt_payload):
        return jsonify({
            "status": "error",
            "message": "Authentication token has expired.",
        }), 401

    @app.errorhandler(413)
    def handle_request_too_large(error):
        return jsonify({
            "status": "error",
            "message": "File size must not exceed 10 MB.",
        }), 413

    @app.get("/api/health")
    def health():
        return {
            "status": "success",
            "message": "Enterprise Knowledge Base AI API is running",
        }

    @app.get("/api/db-health")
    def db_health():
        try:
            db.session.execute(db.text("SELECT 1"))
            return {
                "status": "success",
                "message": "PostgreSQL connection successful",
            }
        except Exception:
            app.logger.exception("Database connection failed")
            db.session.rollback()
            return {
                "status": "error",
                "message": "Database connection failed. Check backend logs.",
            }, 500

    return app
