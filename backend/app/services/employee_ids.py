"""Generate EMP identifiers from a PostgreSQL sequence for concurrency safety."""

from app import db


def next_employee_id():
    # PostgreSQL's users primary-key sequence is already created by the
    # existing schema and allocates unique values across concurrent requests.
    value = db.session.execute(
        db.text("SELECT nextval(pg_get_serial_sequence('users', 'id'))")
    ).scalar_one()
    return f"EMP{value:06d}"
