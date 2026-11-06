from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_documents_content_hash",
            "content_hash",
            unique=True,
            postgresql_where=text("content_hash IS NOT NULL"),
        ),
        Index("uq_documents_url", "url", unique=True, postgresql_where=text("url IS NOT NULL")),
        Index("ix_documents_created_at", "created_at"),
    )
