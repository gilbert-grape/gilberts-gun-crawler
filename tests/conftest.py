"""
Pytest configuration and fixtures for Gilbert's Yoga Helper tests.
"""
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.database.connection import Base
from backend.services.crawler import _crawl_state, clear_crawl_log


@pytest.fixture(autouse=True)
def reset_crawl_state():
    """Reset global crawl state before each test to ensure test isolation."""
    # Reset before test
    _crawl_state.is_running = False
    _crawl_state.cancel_requested = False
    _crawl_state.current_source = None
    _crawl_state.last_result = None
    clear_crawl_log()

    yield

    # Reset after test
    _crawl_state.is_running = False
    _crawl_state.cancel_requested = False
    _crawl_state.current_source = None
    _crawl_state.last_result = None
    clear_crawl_log()


@pytest.fixture
def client():
    """Create a test client for the FastAPI application."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def test_db():
    """
    Create an isolated test database for tests that need database isolation.

    This fixture creates a temporary SQLite database with WAL mode enabled,
    creates all tables, and cleans up after the test.

    Usage:
        def test_something(test_db):
            session = test_db()
            # ... use session
            session.close()
    """
    # Create temporary database file
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # Create test engine with same settings as production
    test_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )

    # Enable WAL mode
    @event.listens_for(test_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    # Create all tables
    Base.metadata.create_all(bind=test_engine)

    # Create session factory
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    yield TestSessionLocal

    # Cleanup
    test_engine.dispose()
    # Remove temporary database files
    for suffix in ["", "-wal", "-shm"]:
        file_path = Path(str(db_path) + suffix)
        if file_path.exists():
            file_path.unlink()


@pytest.fixture
def test_session(test_db):
    """
    Provide a database session for tests, with automatic cleanup.

    Usage:
        def test_something(test_session):
            # test_session is already a Session instance
            test_session.execute(...)
    """
    session = test_db()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
