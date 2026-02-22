"""
Tests for crawl admin routes (Epic 6).

Tests the crawl control functionality:
- 6.1: Manual crawl trigger
- 6.2: Display crawl status
"""
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal, Base, engine
from backend.database.models import Source, SearchTerm
from backend.services.crawler import CrawlResult, CrawlState, _crawl_state


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def db_session():
    """Create a fresh database session for each test."""
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)


@pytest.fixture
def reset_crawl_state():
    """Reset global crawl state before and after each test."""
    global _crawl_state
    _crawl_state.is_running = False
    _crawl_state.current_source = None
    _crawl_state.last_result = None
    yield
    _crawl_state.is_running = False
    _crawl_state.current_source = None
    _crawl_state.last_result = None


@pytest.fixture
def sample_sources(db_session):
    """Create sample sources for testing."""
    sources = [
        Source(name="waffenboerse.ch", base_url="https://www.waffenboerse.ch", is_active=True),
        Source(name="waffengebraucht.ch", base_url="https://waffengebraucht.ch", is_active=True),
    ]
    for source in sources:
        db_session.add(source)
    db_session.commit()
    return sources


@pytest.fixture
def sample_search_terms(db_session):
    """Create sample search terms for testing."""
    terms = [
        SearchTerm(term="Glock", match_type="exact", is_active=True),
    ]
    for term in terms:
        db_session.add(term)
    db_session.commit()
    return terms


class TestCrawlStatusPage:
    """Tests for Story 6.2: Display Crawl Status (FR17)."""

    def test_crawl_page_returns_200(self, client, reset_crawl_state):
        """Test that crawl page returns 200 status."""
        response = client.get("/admin/crawl")
        assert response.status_code == 200

    def test_crawl_page_is_html(self, client, reset_crawl_state):
        """Test that crawl page returns HTML."""
        response = client.get("/admin/crawl")
        assert "text/html" in response.headers["content-type"]

    def test_crawl_page_has_title(self, client, reset_crawl_state):
        """Test that crawl page has correct title."""
        response = client.get("/admin/crawl")
        assert "Crawl-Status" in response.text

    def test_crawl_button_shown_when_idle(self, client, reset_crawl_state):
        """Test that crawl button is shown when no crawl is running."""
        response = client.get("/admin/crawl")
        assert "Jetzt crawlen" in response.text

    def test_no_previous_crawl_message(self, client, reset_crawl_state):
        """Test that message is shown when no crawl has been done."""
        response = client.get("/admin/crawl")
        assert "Kein Crawl durchgeführt" in response.text

    def test_ready_status_shown_when_idle(self, client, reset_crawl_state):
        """Test that 'Bereit' status is shown when idle."""
        response = client.get("/admin/crawl")
        assert "Bereit" in response.text


class TestCrawlStatusWithLastResult:
    """Tests for displaying last crawl result."""

    def test_last_result_shown(self, client, reset_crawl_state):
        """Test that last crawl result is displayed."""
        from datetime import datetime, timezone
        from backend.services import crawler

        # Set up a last result
        crawler._crawl_state.last_result = CrawlResult(
            sources_attempted=3,
            sources_succeeded=2,
            sources_failed=1,
            total_listings=50,
            new_matches=10,
            duplicate_matches=5,
            failed_sources=["test.ch"],
            duration_seconds=15.5,
            completed_at=datetime.now(timezone.utc),
        )

        response = client.get("/admin/crawl")

        # Should show statistics
        assert "3" in response.text  # sources_attempted
        assert "2" in response.text  # sources_succeeded
        assert "50" in response.text  # total_listings
        assert "10" in response.text  # new_matches

    def test_success_status_shown(self, client, reset_crawl_state):
        """Test that success status is shown for successful crawl."""
        from datetime import datetime, timezone
        from backend.services import crawler

        crawler._crawl_state.last_result = CrawlResult(
            sources_attempted=2,
            sources_succeeded=2,
            sources_failed=0,
            completed_at=datetime.now(timezone.utc),
        )

        response = client.get("/admin/crawl")
        assert "Erfolgreich" in response.text

    def test_partial_success_status_shown(self, client, reset_crawl_state):
        """Test that partial success status is shown."""
        from datetime import datetime, timezone
        from backend.services import crawler

        crawler._crawl_state.last_result = CrawlResult(
            sources_attempted=3,
            sources_succeeded=2,
            sources_failed=1,
            failed_sources=["test.ch"],
            completed_at=datetime.now(timezone.utc),
        )

        response = client.get("/admin/crawl")
        assert "Teilweise erfolgreich" in response.text

    def test_failed_sources_listed(self, client, reset_crawl_state):
        """Test that failed sources are listed."""
        from datetime import datetime, timezone
        from backend.services import crawler

        crawler._crawl_state.last_result = CrawlResult(
            sources_attempted=2,
            sources_succeeded=1,
            sources_failed=1,
            failed_sources=["problematic.ch"],
            completed_at=datetime.now(timezone.utc),
        )

        response = client.get("/admin/crawl")
        assert "problematic.ch" in response.text


class TestManualCrawlTrigger:
    """Tests for Story 6.1: Manual Crawl Trigger (FR16)."""

    def test_crawl_button_disabled_when_running(self, client, reset_crawl_state):
        """Test that button is disabled when crawl is running."""
        from backend.services import crawler

        crawler._crawl_state.is_running = True
        crawler._crawl_state.current_source = "waffenboerse.ch"

        response = client.get("/admin/crawl")

        assert "Läuft..." in response.text
        assert "disabled" in response.text

    def test_current_source_shown_when_running(self, client, reset_crawl_state):
        """Test that current source is shown when crawl is running."""
        from backend.services import crawler

        crawler._crawl_state.is_running = True
        crawler._crawl_state.current_source = "waffenboerse.ch"

        response = client.get("/admin/crawl")
        assert "waffenboerse.ch" in response.text

    def test_start_crawl_rejected_without_search_terms(self, client, reset_crawl_state, db_session):
        """Test that starting crawl is rejected when no search terms exist."""
        # Ensure no search terms exist
        db_session.query(SearchTerm).delete()
        db_session.commit()

        response = client.post("/admin/crawl/start")

        assert response.status_code == 200
        assert "Suchbegriffe" in response.text

    @patch("backend.main.run_crawl_async")
    def test_start_crawl_success(self, mock_crawl, client, reset_crawl_state, sample_search_terms):
        """Test successfully starting a crawl."""
        from datetime import datetime, timezone

        mock_result = CrawlResult(
            sources_attempted=2,
            sources_succeeded=2,
            sources_failed=0,
            total_listings=30,
            new_matches=5,
            duplicate_matches=3,
            duration_seconds=10.0,
            completed_at=datetime.now(timezone.utc),
        )
        mock_crawl.return_value = mock_result

        response = client.post("/admin/crawl/start")

        assert response.status_code == 200
        assert "erfolgreich" in response.text.lower()

    @patch("backend.main.run_crawl_async")
    def test_start_crawl_shows_results(self, mock_crawl, client, reset_crawl_state, sample_search_terms):
        """Test that crawl results are shown after completion."""
        from datetime import datetime, timezone

        mock_result = CrawlResult(
            sources_attempted=3,
            sources_succeeded=3,
            sources_failed=0,
            total_listings=100,
            new_matches=25,
            duplicate_matches=10,
            duration_seconds=30.0,
            completed_at=datetime.now(timezone.utc),
        )
        mock_crawl.return_value = mock_result

        response = client.post("/admin/crawl/start")

        assert "100" in response.text  # total_listings
        assert "25" in response.text   # new_matches

    def test_start_crawl_rejected_when_running(self, client, reset_crawl_state, sample_search_terms):
        """Test that starting crawl is rejected when already running."""
        from backend.services import crawler

        crawler._crawl_state.is_running = True

        response = client.post("/admin/crawl/start")

        assert response.status_code == 200
        assert "läuft bereits" in response.text

    @patch("backend.main.run_crawl_async")
    def test_start_crawl_handles_error(self, mock_crawl, client, reset_crawl_state, sample_search_terms):
        """Test that errors during crawl are handled gracefully."""
        mock_crawl.side_effect = Exception("Test error")

        response = client.post("/admin/crawl/start")

        assert response.status_code == 200
        assert "fehlgeschlagen" in response.text.lower()


class TestCrawlStatusPolling:
    """Tests for HTMX status polling endpoint."""

    def test_status_endpoint_returns_partial(self, client, reset_crawl_state):
        """Test that status endpoint returns partial HTML."""
        response = client.get("/admin/crawl/status")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_status_endpoint_shows_running_state(self, client, reset_crawl_state):
        """Test that status endpoint shows running state."""
        from backend.services import crawler

        crawler._crawl_state.is_running = True
        crawler._crawl_state.current_source = "test.ch"

        response = client.get("/admin/crawl/status")

        assert "Läuft" in response.text or "läuft" in response.text
        assert "test.ch" in response.text


class TestCrawlProgressDisplay:
    """Tests for crawl progress indicator display."""

    def test_progress_bar_shown_when_running(self, client, reset_crawl_state):
        """Test that progress bar is shown when crawl is running with progress data."""
        from backend.services import crawler
        from datetime import datetime, timezone

        crawler._crawl_state.is_running = True
        crawler._crawl_state.current_source = "test.ch"
        crawler._crawl_state.sources_total = 10
        crawler._crawl_state.sources_done = 3
        crawler._crawl_state.started_at = datetime.now(timezone.utc)

        response = client.get("/admin/crawl/status")

        # Should show progress text "X von Y Quellen"
        assert "3 von 10 Quellen" in response.text

    def test_progress_percentage_calculated(self, client, reset_crawl_state):
        """Test that progress percentage is shown in the progress bar."""
        from backend.services import crawler
        from datetime import datetime, timezone

        crawler._crawl_state.is_running = True
        crawler._crawl_state.current_source = "test.ch"
        crawler._crawl_state.sources_total = 4
        crawler._crawl_state.sources_done = 2
        crawler._crawl_state.started_at = datetime.now(timezone.utc)

        response = client.get("/admin/crawl/status")

        # 2/4 = 50%, should have style="width: 50%"
        assert "width: 50%" in response.text

    def test_no_progress_when_sources_total_zero(self, client, reset_crawl_state):
        """Test that progress bar is not shown when sources_total is 0."""
        from backend.services import crawler

        crawler._crawl_state.is_running = True
        crawler._crawl_state.current_source = "test.ch"
        crawler._crawl_state.sources_total = 0
        crawler._crawl_state.sources_done = 0

        response = client.get("/admin/crawl/status")

        # Should not show "von" "Quellen" progress text when no sources
        assert "von 0 Quellen" not in response.text

    def test_eta_display_element_present(self, client, reset_crawl_state):
        """Test that ETA display element is present when crawl is running."""
        from backend.services import crawler
        from datetime import datetime, timezone

        crawler._crawl_state.is_running = True
        crawler._crawl_state.current_source = "test.ch"
        crawler._crawl_state.sources_total = 10
        crawler._crawl_state.sources_done = 5
        crawler._crawl_state.started_at = datetime.now(timezone.utc)

        response = client.get("/admin/crawl/status")

        # ETA display element should be present
        assert 'id="eta-display"' in response.text

    def test_started_at_passed_to_template(self, client, reset_crawl_state):
        """Test that started_at timestamp is passed to template for ETA calculation."""
        from backend.services import crawler
        from datetime import datetime, timezone

        test_time = datetime.now(timezone.utc)
        crawler._crawl_state.is_running = True
        crawler._crawl_state.current_source = "test.ch"
        crawler._crawl_state.sources_total = 10
        crawler._crawl_state.sources_done = 3
        crawler._crawl_state.started_at = test_time

        response = client.get("/admin/crawl/status")

        # The started_at should be in the response for JavaScript ETA calculation
        assert "startedAt" in response.text

    def test_no_progress_when_not_running(self, client, reset_crawl_state):
        """Test that progress bar is not shown when crawl is not running."""
        response = client.get("/admin/crawl/status")

        # Should show "Bereit" status, not progress bar
        assert "Bereit" in response.text
        # Should not have progress-specific elements
        assert "von" not in response.text or "Quellen" not in response.text


class TestCrawlStateHelpers:
    """Tests for crawl state helper functions."""

    def test_is_crawl_running(self, reset_crawl_state):
        """Test is_crawl_running function."""
        from backend.services.crawler import is_crawl_running
        from backend.services import crawler

        assert is_crawl_running() is False

        crawler._crawl_state.is_running = True
        assert is_crawl_running() is True

    def test_get_last_crawl_result(self, reset_crawl_state):
        """Test get_last_crawl_result function."""
        from backend.services.crawler import get_last_crawl_result
        from backend.services import crawler

        assert get_last_crawl_result() is None

        result = CrawlResult(sources_attempted=1)
        crawler._crawl_state.last_result = result

        assert get_last_crawl_result() == result

    def test_get_crawl_state(self, reset_crawl_state):
        """Test get_crawl_state function."""
        from backend.services.crawler import get_crawl_state

        state = get_crawl_state()

        assert isinstance(state, CrawlState)
        assert state.is_running is False


class TestCrawlResultProperties:
    """Tests for CrawlResult dataclass properties."""

    def test_is_success(self):
        """Test is_success property."""
        result = CrawlResult(sources_attempted=2, sources_succeeded=2, sources_failed=0)
        assert result.is_success is True

        result = CrawlResult(sources_attempted=2, sources_succeeded=1, sources_failed=1)
        assert result.is_success is False

    def test_is_partial_success(self):
        """Test is_partial_success property."""
        result = CrawlResult(sources_attempted=3, sources_succeeded=2, sources_failed=1)
        assert result.is_partial_success is True

        result = CrawlResult(sources_attempted=2, sources_succeeded=2, sources_failed=0)
        assert result.is_partial_success is False

        result = CrawlResult(sources_attempted=2, sources_succeeded=0, sources_failed=2)
        assert result.is_partial_success is False

    def test_status_text(self):
        """Test status_text property."""
        # Success
        result = CrawlResult(sources_attempted=2, sources_succeeded=2, sources_failed=0)
        assert result.status_text == "Erfolgreich"

        # Partial success
        result = CrawlResult(sources_attempted=3, sources_succeeded=2, sources_failed=1)
        assert result.status_text == "Teilweise erfolgreich"

        # Complete failure
        result = CrawlResult(sources_attempted=2, sources_succeeded=0, sources_failed=2)
        assert result.status_text == "Fehlgeschlagen"

        # No sources
        result = CrawlResult(sources_attempted=0, sources_succeeded=0, sources_failed=0)
        assert result.status_text == "Keine Quellen"
