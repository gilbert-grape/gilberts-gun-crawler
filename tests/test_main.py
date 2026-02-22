"""
Tests for main.py application startup and verification.

Tests verify:
- verify_database() handles missing database
- verify_database() handles missing alembic_version table
- verify_database() handles missing application tables
- verify_database() succeeds with complete database
- FastAPI routes return correct responses
"""
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from alembic import command
from alembic.config import Config

from backend.database.connection import PROJECT_ROOT


ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


class TestVerifyDatabase:
    """Tests for verify_database() function."""

    @pytest.fixture
    def mock_database_path(self, tmp_path):
        """Create a mock DATABASE_PATH that points to a temp directory."""
        db_file = tmp_path / "test.db"
        return db_file

    def test_logs_error_when_database_missing(self, mock_database_path, caplog):
        """verify_database should log error when database file doesn't exist."""
        import logging
        import backend.main

        caplog.set_level(logging.ERROR)

        # Patch DATABASE_PATH to use our temp path (file doesn't exist)
        with patch.object(backend.main, 'DATABASE_PATH', mock_database_path):
            backend.main.verify_database()

        assert "Database file not found" in caplog.text
        assert "alembic upgrade head" in caplog.text

    def test_logs_warning_when_alembic_version_missing(self, mock_database_path, caplog):
        """verify_database should log warning when alembic_version table doesn't exist."""
        import logging
        import backend.main

        caplog.set_level(logging.WARNING)

        # Create an empty database file with a dummy table
        test_engine = create_engine(
            f"sqlite:///{mock_database_path}",
            connect_args={"check_same_thread": False}
        )
        with test_engine.connect() as conn:
            conn.execute(text("CREATE TABLE dummy (id INTEGER PRIMARY KEY)"))
            conn.commit()

        with patch.object(backend.main, 'DATABASE_PATH', mock_database_path), \
             patch.object(backend.main, 'engine', test_engine):
            backend.main.verify_database()

        test_engine.dispose()
        assert "Alembic version table not found" in caplog.text

    def test_logs_warning_when_tables_missing(self, mock_database_path, caplog):
        """verify_database should log warning when application tables are missing."""
        import logging
        import backend.main

        caplog.set_level(logging.WARNING)

        # Create database with alembic_version but no app tables
        test_engine = create_engine(
            f"sqlite:///{mock_database_path}",
            connect_args={"check_same_thread": False}
        )
        with test_engine.connect() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
            conn.execute(text("INSERT INTO alembic_version VALUES ('001_initial')"))
            conn.commit()

        with patch.object(backend.main, 'DATABASE_PATH', mock_database_path), \
             patch.object(backend.main, 'engine', test_engine):
            backend.main.verify_database()

        test_engine.dispose()
        assert "Missing tables" in caplog.text

    def test_succeeds_when_database_complete(self, mock_database_path):
        """verify_database should complete without warning/error when all tables exist."""
        import backend.main

        # Run actual migrations to create complete database
        alembic_cfg = Config(str(ALEMBIC_INI))
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{mock_database_path}")
        command.upgrade(alembic_cfg, "head")

        test_engine = create_engine(
            f"sqlite:///{mock_database_path}",
            connect_args={"check_same_thread": False}
        )

        # Mock the logger to verify the success message is logged
        with patch.object(backend.main, 'DATABASE_PATH', mock_database_path), \
             patch.object(backend.main, 'engine', test_engine), \
             patch.object(backend.main.logger, 'info') as mock_info, \
             patch.object(backend.main.logger, 'warning') as mock_warning, \
             patch.object(backend.main.logger, 'error') as mock_error:
            backend.main.verify_database()

            # Should log success info, no warnings or errors
            mock_info.assert_called_once()
            assert "Database verification successful" in mock_info.call_args[0][0]
            mock_warning.assert_not_called()
            mock_error.assert_not_called()

        test_engine.dispose()

    def test_raises_on_connection_error(self, mock_database_path):
        """verify_database should raise exception on database connection error."""
        import backend.main

        # Create database file so it passes existence check
        mock_database_path.touch()

        # Create a mock engine that raises on connect
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("Connection failed")

        with patch.object(backend.main, 'DATABASE_PATH', mock_database_path), \
             patch.object(backend.main, 'engine', mock_engine):
            with pytest.raises(Exception, match="Connection failed"):
                backend.main.verify_database()


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_returns_ok(self):
        """Test /health endpoint returns healthy status."""
        from backend.main import app

        with patch("backend.main.verify_database"), \
             patch("backend.database.SessionLocal") as mock_session, \
             patch("backend.main.ensure_sources_exist"), \
             patch("backend.database.ensure_default_search_terms"), \
             patch("backend.database.ensure_default_exclude_terms"):

            mock_db = MagicMock()
            mock_session.return_value = mock_db
            client = TestClient(app)
            response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestDashboardRoute:
    """Tests for dashboard route."""

    def test_dashboard_returns_html(self):
        """Test dashboard returns HTML response."""
        from backend.main import app

        with patch("backend.main.verify_database"), \
             patch("backend.database.SessionLocal") as mock_session_class, \
             patch("backend.main.ensure_sources_exist"), \
             patch("backend.database.ensure_default_search_terms"), \
             patch("backend.database.ensure_default_exclude_terms"), \
             patch("backend.main.get_all_search_terms") as mock_terms, \
             patch("backend.main.get_matches_by_search_term") as mock_matches, \
             patch("backend.main.mark_matches_as_seen"):

            mock_db = MagicMock()
            mock_session_class.return_value = mock_db
            mock_terms.return_value = []
            mock_matches.return_value = []

            client = TestClient(app)
            response = client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestAdminSearchTermsRoute:
    """Tests for admin search terms route."""

    def test_admin_search_terms_returns_html(self):
        """Test admin search terms page returns HTML."""
        from backend.main import app

        with patch("backend.main.verify_database"), \
             patch("backend.database.SessionLocal") as mock_session_class, \
             patch("backend.main.ensure_sources_exist"), \
             patch("backend.database.ensure_default_search_terms"), \
             patch("backend.database.ensure_default_exclude_terms"), \
             patch("backend.main.get_all_search_terms") as mock_terms:

            mock_db = MagicMock()
            mock_session_class.return_value = mock_db
            mock_terms.return_value = []

            client = TestClient(app)
            response = client.get("/admin/search-terms")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestAdminSourcesRoute:
    """Tests for admin sources route."""

    def test_admin_sources_returns_html(self):
        """Test admin sources page returns HTML."""
        from backend.main import app

        with patch("backend.main.verify_database"), \
             patch("backend.database.SessionLocal") as mock_session_class, \
             patch("backend.main.ensure_sources_exist"), \
             patch("backend.database.ensure_default_search_terms"), \
             patch("backend.database.ensure_default_exclude_terms"), \
             patch("backend.main.get_all_sources_sorted") as mock_sources:

            mock_db = MagicMock()
            mock_session_class.return_value = mock_db
            mock_sources.return_value = []

            client = TestClient(app)
            response = client.get("/admin/sources")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestAdminCrawlRoute:
    """Tests for admin crawl status route."""

    def test_admin_crawl_status_returns_html(self):
        """Test admin crawl status page returns HTML."""
        from backend.main import app
        from backend.services.crawler import CrawlState

        with patch("backend.main.verify_database"), \
             patch("backend.database.SessionLocal") as mock_session_class, \
             patch("backend.main.ensure_sources_exist"), \
             patch("backend.database.ensure_default_search_terms"), \
             patch("backend.database.ensure_default_exclude_terms"), \
             patch("backend.main.get_crawl_state") as mock_state, \
             patch("backend.main.get_crawl_log") as mock_log:

            mock_db = MagicMock()
            mock_session_class.return_value = mock_db
            mock_state.return_value = CrawlState()
            mock_log.return_value = []

            client = TestClient(app)
            response = client.get("/admin/crawl")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestAdminExcludeTermsRoute:
    """Tests for admin exclude terms route."""

    def test_admin_exclude_terms_returns_html(self):
        """Test admin exclude terms page returns HTML."""
        from backend.main import app

        with patch("backend.main.verify_database"), \
             patch("backend.database.SessionLocal") as mock_session_class, \
             patch("backend.main.ensure_sources_exist"), \
             patch("backend.database.ensure_default_search_terms"), \
             patch("backend.database.ensure_default_exclude_terms"), \
             patch("backend.main.get_all_exclude_terms_sorted") as mock_terms:

            mock_db = MagicMock()
            mock_session_class.return_value = mock_db
            mock_terms.return_value = []

            client = TestClient(app)
            response = client.get("/admin/exclude-terms")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestCrawlStatusPolling:
    """Tests for crawl status polling endpoint."""

    def test_crawl_status_partial_returns_html(self):
        """Test crawl status partial returns HTML."""
        from backend.main import app
        from backend.services.crawler import CrawlState

        with patch("backend.main.verify_database"), \
             patch("backend.database.SessionLocal") as mock_session_class, \
             patch("backend.main.ensure_sources_exist"), \
             patch("backend.database.ensure_default_search_terms"), \
             patch("backend.database.ensure_default_exclude_terms"), \
             patch("backend.main.get_crawl_state") as mock_state, \
             patch("backend.main.get_crawl_log") as mock_log:

            mock_db = MagicMock()
            mock_session_class.return_value = mock_db
            mock_state.return_value = CrawlState()
            mock_log.return_value = []

            client = TestClient(app)
            response = client.get("/admin/crawl/status")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestCancelCrawl:
    """Tests for cancel crawl endpoint."""

    def test_cancel_crawl_when_not_running(self):
        """Test cancel crawl returns error when not running."""
        from backend.main import app
        from backend.services.crawler import CrawlState

        with patch("backend.main.verify_database"), \
             patch("backend.database.SessionLocal") as mock_session_class, \
             patch("backend.main.ensure_sources_exist"), \
             patch("backend.database.ensure_default_search_terms"), \
             patch("backend.database.ensure_default_exclude_terms"), \
             patch("backend.main.is_crawl_running") as mock_running, \
             patch("backend.main.get_crawl_state") as mock_state:

            mock_db = MagicMock()
            mock_session_class.return_value = mock_db
            mock_running.return_value = False
            mock_state.return_value = CrawlState()

            client = TestClient(app)
            response = client.post("/admin/crawl/cancel")

        assert response.status_code == 200

    def test_cancel_crawl_when_running(self):
        """Test cancel crawl requests cancellation when running."""
        from backend.main import app
        from backend.services.crawler import CrawlState

        with patch("backend.main.verify_database"), \
             patch("backend.database.SessionLocal") as mock_session_class, \
             patch("backend.main.ensure_sources_exist"), \
             patch("backend.database.ensure_default_search_terms"), \
             patch("backend.database.ensure_default_exclude_terms"), \
             patch("backend.main.is_crawl_running") as mock_running, \
             patch("backend.main.request_crawl_cancel") as mock_cancel, \
             patch("backend.main.get_crawl_state") as mock_state:

            mock_db = MagicMock()
            mock_session_class.return_value = mock_db
            mock_running.return_value = True
            state = CrawlState(is_running=True)
            mock_state.return_value = state

            client = TestClient(app)
            response = client.post("/admin/crawl/cancel")

            mock_cancel.assert_called_once()

        assert response.status_code == 200
