"""documents

Revision ID: 0001_documents
Revises:
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_documents"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_documents_content_hash",
        "documents",
        ["content_hash"],
        unique=True,
        postgresql_where=sa.text("content_hash IS NOT NULL"),
    )
    op.create_index(
        "uq_documents_url",
        "documents",
        ["url"],
        unique=True,
        postgresql_where=sa.text("url IS NOT NULL"),
    )
    op.create_index("ix_documents_created_at", "documents", ["created_at"])


def downgrade() -> None:
    op.drop_table("documents")
