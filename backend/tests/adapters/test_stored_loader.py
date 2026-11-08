from datetime import UTC, datetime

import pytest

from fontes.adapters.loaders.markdown import parse_markdown
from fontes.adapters.loaders.stored import StoredFileLoader
from fontes.application.ports.ingestion import PermanentIngestionError
from fontes.domain.chunks import Segment
from fontes.domain.documents import Document
from tests.fakes import InMemoryFileStorage

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


async def test_reads_storage_and_parses() -> None:
    storage = InMemoryFileStorage()
    doc = Document.from_upload("a.md", "hash", now=NOW)
    assert doc.storage_key is not None
    await storage.save(doc.storage_key, b"# A\nx")
    assert await StoredFileLoader(storage, parse_markdown).load(doc) == [
        Segment("A\nx", section="A")
    ]


async def test_missing_file_is_permanent() -> None:
    doc = Document.from_upload("a.md", "hash", now=NOW)
    with pytest.raises(PermanentIngestionError, match="missing from storage"):
        await StoredFileLoader(InMemoryFileStorage(), parse_markdown).load(doc)
