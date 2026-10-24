"""Helpers for rendering database URLs without exposing credentials."""


def render_database_url(url):
    """Render a SQLAlchemy URL with passwords masked for Alembic config."""
    try:
        rendered = url.render_as_string(hide_password=True)
    except AttributeError:
        # SQLAlchemy URL.__str__ also masks the password on older supported APIs.
        rendered = str(url)
    return rendered.replace("%", "%%")
