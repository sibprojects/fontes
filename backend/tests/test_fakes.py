"""The in-memory fake must behave like the real repository: run the shared contract on it."""

import pytest

from tests.fakes import InMemoryDocumentRepository
from tests.repository_contract import (  # noqa: F401
    test_list_by_status_oldest_first,
    test_set_status_clears_error,
    test_set_status_missing_returns_false,
    test_set_status_with_error,
    test_start_processing_increments_attempts,
    test_start_processing_missing_returns_none,
    test_start_processing_skips_ready,
)


@pytest.fixture
def repo() -> InMemoryDocumentRepository:
    return InMemoryDocumentRepository()
