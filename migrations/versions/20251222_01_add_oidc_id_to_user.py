"""add oidc_id to user

Revision ID: 20251222_01
Revises: 20251013_01
Create Date: 2025-12-22 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '20251222_01'
down_revision = '20251013_01'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("users")}

    with op.batch_alter_table('users', schema=None) as batch_op:
        # Add oidc_id column if it doesn't exist
        if "oidc_id" not in existing_columns:
            batch_op.add_column(sa.Column('oidc_id', sa.String(length=256), nullable=True))
            batch_op.create_unique_constraint('uq_users_oidc_id', ['oidc_id'])

        # Make password_hash nullable to support OIDC-only users
        if "password_hash" in existing_columns:
            batch_op.alter_column('password_hash',
                                  existing_type=sa.String(length=255),
                                  nullable=True)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("users")}

    with op.batch_alter_table('users', schema=None) as batch_op:
        # Revert password_hash to NOT NULL (note: this will fail if OIDC users exist with NULL password)
        if "password_hash" in existing_columns:
            batch_op.alter_column('password_hash',
                                  existing_type=sa.String(length=255),
                                  nullable=False)

        # Remove oidc_id column
        if "oidc_id" in existing_columns:
            batch_op.drop_constraint('uq_users_oidc_id', type_='unique')
            batch_op.drop_column('oidc_id')
