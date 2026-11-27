"""follow-ups: the question an answer follows up on

Revision ID: 0004_follow_ups
Revises: 0003_questions
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_follow_ups"
down_revision: str | None = "0003_questions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SET NULL: deleting an earlier question keeps its follow-ups, just unlinked.
    op.add_column(
        "questions",
        sa.Column(
            "follow_up_of",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("questions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("questions", "follow_up_of")
