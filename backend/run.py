
from app import create_app

app = create_app()


def run_development_server():
    if app.config["APP_ENV"] != "development":
        raise RuntimeError(
            "run.py is limited to development; use the configured WSGI server."
        )
    app.run(debug=app.config["DEBUG"], port=8000)


if __name__ == "__main__":
    run_development_server()
