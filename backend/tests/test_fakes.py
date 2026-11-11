"""The in-memory fakes must behave like the real repositories: run the shared contracts on them."""

import pytest

from tests.chunk_repository_contract import (  # noqa: F401
    test_replace_for_missing_document_writes_nothing,
    test_replace_then_list_in_order,
    test_replace_twice_leaves_only_second,
    test_replace_with_mismatched_embeddings_raises,
    test_search_across_documents,
    test_search_hit_carries_citation_fields,
    test_search_orders_by_similarity,
    test_search_respects_limit,
    test_search_skips_documents_not_ready,
    test_text_with_unusual_characters_round_trips,
)
from tests.fakes import InMemoryChunkRepository, InMemoryDocumentRepository
from tests.repository_contract import (  # noqa: F401
    test_list_by_status_oldest_first,
    test_set_status_clears_error,
    test_set_status_missing_returns_false,
    test_set_status_with_error,
    test_start_processing_increments_attempts,
    test_start_processing_missing_returns_none,
    test_start_processing_skips_failed,
    test_start_processing_skips_ready,
)


@pytest.fixture
def repo() -> InMemoryDocumentRepository:
    return InMemoryDocumentRepository()


@pytest.fixture
def docs() -> InMemoryDocumentRepository:
    return InMemoryDocumentRepository()


@pytest.fixture
def chunks(docs: InMemoryDocumentRepository) -> InMemoryChunkRepository:
    return InMemoryChunkRepository(docs)
