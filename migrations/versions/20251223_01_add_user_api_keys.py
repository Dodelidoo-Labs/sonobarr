"""add per-user api keys

Revision ID: 20251223_01
Revises: 20251013_01
Create Date: 2025-12-23 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '20251223_01'
down_revision = '20251013_01'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("users")}

    columns_to_add = [
        ("lastfm_api_key", sa.String(length=256)),
        ("lastfm_api_secret", sa.String(length=256)),
        ("youtube_api_key", sa.String(length=256)),
        ("openai_api_key", sa.String(length=512)),
        ("openai_api_base", sa.String(length=512)),
        ("openai_model", sa.String(length=128)),
        ("openai_extra_headers", sa.Text()),
        ("openai_max_seed_artists", sa.Integer()),
    ]

    with op.batch_alter_table('users', schema=None) as batch_op:
        for column_name, column_type in columns_to_add:
            if column_name not in existing_columns:
                batch_op.add_column(sa.Column(column_name, column_type, nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("users")}

    columns_to_remove = [
        "lastfm_api_key",
        "lastfm_api_secret",
        "youtube_api_key",
        "openai_api_key",
        "openai_api_base",
        "openai_model",
        "openai_extra_headers",
        "openai_max_seed_artists",
    ]

    with op.batch_alter_table('users', schema=None) as batch_op:
        for column_name in columns_to_remove:
            if column_name in existing_columns:
                batch_op.drop_column(column_name)
