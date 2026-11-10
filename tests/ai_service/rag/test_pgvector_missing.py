"""A database without pgvector: vector search gives a clear warning and no results (keyword
search still works); every other database error is still raised."""

import logging
import uuid

import pytest
from sqlalchemy.exc import DBAPIError

from ai_service.rag.indexing import vector_store
from ai_service.rag.indexing.vector_store import PgVectorStore, SearchFilters, is_missing_pgvector


def db_error(message: str) -> DBAPIError:
    return DBAPIError("SELECT ...", {}, Exception(message))


class FailingSession:
    """Stands in for AsyncSession: every query raises `error`."""

    def __init__(self, error: Exception):
        self.error = error
        self.rollbacks = 0

    async def execute(self, stmt):  # type: ignore[no-untyped-def]
        raise self.error

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture(autouse=True)
def fresh_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vector_store, "_PGVECTOR_MISSING", False)


@pytest.mark.parametrize(
    "message",
    [
        "operator does not exist: vector <=> vector",
        'type "vector" does not exist',
    ],
)
def test_missing_pgvector_is_recognised(message: str) -> None:
    assert is_missing_pgvector(db_error(message))


@pytest.mark.parametrize(
    "message",
    ["connection refused", "relation \"document_chunks\" does not exist", "operator does not exist: text = integer"],
)  # fmt: skip
def test_other_errors_are_not_mistaken_for_it(message: str) -> None:
    assert not is_missing_pgvector(db_error(message))


async def test_missing_pgvector_gives_a_warning_and_no_vector_results(caplog) -> None:  # type: ignore[no-untyped-def]
    session = FailingSession(db_error("operator does not exist: vector <=> vector"))
    store = PgVectorStore(session)  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        assert await store.vector_search([0.1] * 768, SearchFilters(), 5) == []
    assert session.rollbacks == 1  # so keyword search can still run in this session
    assert "pgvector is not installed" in caplog.text
    # Later searches skip the vector part straight away (no new error, no new warning)
    caplog.clear()
    assert await store.vector_search([0.1] * 768, SearchFilters(), 5) == []
    assert session.rollbacks == 1 and caplog.text == ""


async def test_other_database_errors_are_raised() -> None:
    store = PgVectorStore(FailingSession(db_error("connection refused")))  # type: ignore[arg-type]
    with pytest.raises(DBAPIError):
        await store.vector_search([0.1] * 768, SearchFilters(unit_id=uuid.uuid4()), 5)
    assert vector_store._PGVECTOR_MISSING is False


async def test_keyword_search_never_returns_random_chunks() -> None:
    # Before, a failed keyword search fell back to random chunks of the unit; now it raises.
    store = PgVectorStore(FailingSession(db_error("connection refused")))  # type: ignore[arg-type]
    with pytest.raises(DBAPIError):
        await store.keyword_search("osmosis", SearchFilters(unit_id=uuid.uuid4()), 5)
