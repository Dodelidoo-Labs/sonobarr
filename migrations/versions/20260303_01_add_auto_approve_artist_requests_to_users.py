"""add auto approve artist requests flag to users

Revision ID: 20260303_01
Revises: 20251222_01
Create Date: 2026-03-03 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "20260303_01"
down_revision = "20251222_01"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("users")}

    with op.batch_alter_table("users", schema=None) as batch_op:
        if "auto_approve_artist_requests" not in existing_columns:
            batch_op.add_column(
                sa.Column(
                    "auto_approve_artist_requests",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("users")}

    with op.batch_alter_table("users", schema=None) as batch_op:
        if "auto_approve_artist_requests" in existing_columns:
            batch_op.drop_column("auto_approve_artist_requests")
