"""Remove the MANAGER role; downgrade existing MANAGER users to EMPLOYEE.

Revision ID: e3f7b2d901a4
Revises: b7d8e2c1045f
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa


revision = "e3f7b2d901a4"
down_revision = "b7d8e2c1045f"
branch_labels = None
depends_on = None


def upgrade():
    # Downgrade any existing MANAGER rows to EMPLOYEE before adding the
    # constraint so the migration is safe regardless of current data.
    op.execute(sa.text(
        "UPDATE users SET role = 'EMPLOYEE' WHERE role = 'MANAGER'"
    ))
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('ADMIN', 'EMPLOYEE')",
    )


def downgrade():
    op.drop_constraint("ck_users_role", "users", type_="check")
    # MANAGER rows are not restored on downgrade: we cannot know which rows
    # were originally MANAGER versus EMPLOYEE.
