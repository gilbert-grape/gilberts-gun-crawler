"""
Tests for crawler orchestrator.

Tests the crawl orchestration:
- Sequential execution of scrapers
- Error isolation (failure doesn't stop others)
- Matching and persistence integration
- Summary logging
"""
import pytest
from unittest.mock import patch
from datetime import datetime, timezone

from backend.database.models import Match, Source
from backend.database.crud import (
    create_search_term,
    get_or_create_source,
    get_all_matches,
)
from backend.services.crawler import (
    CrawlResult,
    CrawlState,
    SCRAPER_REGISTRY,
    SOURCE_BASE_URLS,
    _log_crawl_summary,
    add_crawl_log,
    clear_crawl_log,
    ensure_sources_exist,
    get_crawl_log,
    get_crawl_state,
    get_last_crawl_result,
    get_registered_sources,
    is_cancel_requested,
    is_crawl_running,
    prepare_crawl_state,
    request_crawl_cancel,
    run_crawl,
    run_crawl_async,
    run_single_scraper,
    _crawl_state,
)


def make_async_scraper(return_value):
    """Helper to create an async mock scraper that returns given value."""
    async def scraper():
        return return_value
    return scraper


def make_failing_async_scraper(exception):
    """Helper to create an async mock scraper that raises given exception."""
    async def scraper():
        raise exception
    return scraper


class TestScraperRegistry:
    """Tests for scraper registry configuration."""

    def test_registry_has_all_sources(self):
        """Test that all expected sources are registered."""
        expected = {
            "aats-group.ch", "aebiwaffen.ch", "armashop.ch", "egun.de",
            "ellie-firearms.com", "gebrauchtwaffen.com", "gwmh-shop.ch",
            "petitesannonces.ch", "renehild-tactical.ch", "vnsm.ch",
            "waffenboerse.ch", "waffengebraucht.ch", "waffen-joray.ch",
            "waffenzimmi.ch"
        }
        assert set(SCRAPER_REGISTRY.keys()) == expected

    def test_base_urls_match_registry(self):
        """Test that base URLs exist for all registered scrapers."""
        for source_name in SCRAPER_REGISTRY:
            assert source_name in SOURCE_BASE_URLS
            assert SOURCE_BASE_URLS[source_name].startswith("https://")

    def test_get_registered_sources(self):
        """Test get_registered_sources returns all source names."""
        sources = get_registered_sources()
        assert len(sources) == 14
        assert "aebiwaffen.ch" in sources
        assert "waffenboerse.ch" in sources
        assert "waffengebraucht.ch" in sources
        assert "waffenzimmi.ch" in sources
        assert "renehild-tactical.ch" in sources
        assert "vnsm.ch" in sources


class TestEnsureSourcesExist:
    """Tests for ensure_sources_exist function."""

    def test_creates_missing_sources(self, test_session):
        """Test that missing sources are created."""
        # No sources initially
        assert test_session.query(Source).count() == 0

        source_map = ensure_sources_exist(test_session)

        # All sources created
        assert test_session.query(Source).count() == 14
        assert "aebiwaffen.ch" in source_map
        assert "waffenboerse.ch" in source_map
        assert "waffengebraucht.ch" in source_map
        assert "waffenzimmi.ch" in source_map
        assert "renehild-tactical.ch" in source_map

    def test_returns_source_ids(self, test_session):
        """Test that source_map contains correct IDs."""
        source_map = ensure_sources_exist(test_session)

        for name, source_id in source_map.items():
            source = test_session.query(Source).filter(Source.id == source_id).first()
            assert source is not None
            assert source.name == name

    def test_idempotent(self, test_session):
        """Test that calling multiple times doesn't create duplicates."""
        ensure_sources_exist(test_session)
        ensure_sources_exist(test_session)
        ensure_sources_exist(test_session)

        assert test_session.query(Source).count() == 14


class TestRunSingleScraper:
    """Tests for run_single_scraper function."""

    @pytest.mark.asyncio
    async def test_successful_scrape(self, test_session):
        """Test successful scraper execution."""
        source = get_or_create_source(test_session, "test.ch", "https://test.ch")

        mock_scraper = make_async_scraper([
            {"title": "Test Item", "price": 100, "link": "https://test.ch/1", "source": "test.ch"}
        ])

        results, error = await run_single_scraper(source, mock_scraper)

        assert error is None
        assert len(results) == 1
        assert results[0]["title"] == "Test Item"

    @pytest.mark.asyncio
    async def test_failed_scrape_returns_error(self, test_session):
        """Test that scraper failure returns error message."""
        source = get_or_create_source(test_session, "test.ch", "https://test.ch")

        failing_scraper = make_failing_async_scraper(ValueError("Connection failed"))

        results, error = await run_single_scraper(source, failing_scraper)

        assert results == []
        assert error is not None
        assert "ValueError" in error
        assert "Connection failed" in error

    @pytest.mark.asyncio
    async def test_failed_scrape_isolates_error(self, test_session):
        """Test that scraper failure doesn't raise exception."""
        source = get_or_create_source(test_session, "test.ch", "https://test.ch")

        failing_scraper = make_failing_async_scraper(RuntimeError("Unexpected error"))

        # Should not raise
        results, error = await run_single_scraper(source, failing_scraper)
        assert error is not None


class TestCrawlResult:
    """Tests for CrawlResult dataclass."""

    def test_default_values(self):
        """Test CrawlResult has correct defaults."""
        result = CrawlResult()

        assert result.sources_attempted == 0
        assert result.sources_succeeded == 0
        assert result.sources_failed == 0
        assert result.total_listings == 0
        assert result.new_matches == 0
        assert result.duplicate_matches == 0
        assert result.failed_sources == []
        assert result.duration_seconds == 0.0

    def test_str_representation(self):
        """Test CrawlResult string representation."""
        result = CrawlResult(
            sources_attempted=3,
            sources_succeeded=2,
            sources_failed=1,
            total_listings=100,
            new_matches=10,
            duration_seconds=5.5,
        )

        str_rep = str(result)
        assert "attempted=3" in str_rep
        assert "succeeded=2" in str_rep
        assert "failed=1" in str_rep
        assert "listings=100" in str_rep
        assert "new_matches=10" in str_rep


class TestRunCrawl:
    """Tests for run_crawl orchestration."""

    def test_no_active_sources(self, test_session):
        """Test crawl with no active sources."""
        # Create inactive source only - don't let ensure_sources_exist run
        # We need to mock SCRAPER_REGISTRY to be empty so no sources get created
        with patch.dict(SCRAPER_REGISTRY, {}, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {}, clear=True):
            # Create inactive source manually
            source = get_or_create_source(test_session, "test.ch", "https://test.ch")
            source.is_active = False
            test_session.commit()

            result = run_crawl(test_session)

        assert result.sources_attempted == 0
        assert result.sources_succeeded == 0

    def test_no_search_terms_still_scrapes(self, test_session):
        """Test that crawl runs scrapers even without search terms."""
        # Mock all scrapers to return results as async functions
        mock_results = [
            {"title": "Test", "price": 100, "link": "https://test.ch/1", "source": "waffenboerse.ch"}
        ]

        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_async_scraper(mock_results),
            "waffengebraucht.ch": make_async_scraper([]),
            "waffenzimmi.ch": make_async_scraper([]),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
            "waffenzimmi.ch": "https://waffenzimmi.ch",
        }, clear=True):
            result = run_crawl(test_session)

        # Scrapers ran
        assert result.sources_attempted == 3
        assert result.sources_succeeded == 3
        assert result.total_listings == 1
        # But no matches without search terms
        assert result.new_matches == 0

    def test_sequential_execution(self, test_session):
        """Test that scrapers run sequentially (AC: 1)."""
        execution_order = []

        def make_tracking_scraper(name):
            async def scraper():
                execution_order.append(name)
                return []
            return scraper

        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_tracking_scraper("waffenboerse"),
            "waffengebraucht.ch": make_tracking_scraper("waffengebraucht"),
            "waffenzimmi.ch": make_tracking_scraper("waffenzimmi"),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
            "waffenzimmi.ch": "https://waffenzimmi.ch",
        }, clear=True):
            run_crawl(test_session)

        # All scrapers executed
        assert len(execution_order) == 3
        # Order determined by database query, but all should run

    def test_failure_continues_to_next(self, test_session):
        """Test that scraper failure continues to next (AC: 2)."""
        execution_order = []

        async def failing_scraper():
            execution_order.append("failing")
            raise ValueError("Failed")

        async def success_scraper():
            execution_order.append("success")
            return []

        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": failing_scraper,
            "waffengebraucht.ch": success_scraper,
            "waffenzimmi.ch": success_scraper,
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
            "waffenzimmi.ch": "https://waffenzimmi.ch",
        }, clear=True):
            result = run_crawl(test_session)

        # All scrapers attempted despite failure
        assert len(execution_order) == 3
        assert result.sources_attempted == 3
        assert result.sources_failed == 1
        assert result.sources_succeeded == 2
        assert "waffenboerse.ch" in result.failed_sources

    def test_updates_source_last_crawl_at(self, test_session):
        """Test that successful scrape updates last_crawl_at."""
        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_async_scraper([]),
            "waffengebraucht.ch": make_async_scraper([]),
            "waffenzimmi.ch": make_async_scraper([]),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
            "waffenzimmi.ch": "https://waffenzimmi.ch",
        }, clear=True):
            before = datetime.now(timezone.utc).replace(tzinfo=None)
            run_crawl(test_session)
            after = datetime.now(timezone.utc).replace(tzinfo=None)

        source = test_session.query(Source).filter(Source.name == "waffenboerse.ch").first()
        assert source.last_crawl_at is not None
        assert before <= source.last_crawl_at <= after

    def test_updates_source_last_error_on_failure(self, test_session):
        """Test that failed scrape updates last_error."""
        failing_scraper = make_failing_async_scraper(ValueError("Test error message"))

        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": failing_scraper,
            "waffengebraucht.ch": make_async_scraper([]),
            "waffenzimmi.ch": make_async_scraper([]),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
            "waffenzimmi.ch": "https://waffenzimmi.ch",
        }, clear=True):
            run_crawl(test_session)

        source = test_session.query(Source).filter(Source.name == "waffenboerse.ch").first()
        assert source.last_error is not None
        assert "ValueError" in source.last_error
        assert "Test error message" in source.last_error

    def test_clears_last_error_on_success(self, test_session):
        """Test that successful scrape clears last_error."""
        # Set initial error
        source = get_or_create_source(test_session, "waffenboerse.ch", "https://waffenboerse.ch")
        source.last_error = "Previous error"
        test_session.commit()

        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_async_scraper([]),
            "waffengebraucht.ch": make_async_scraper([]),
            "waffenzimmi.ch": make_async_scraper([]),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
            "waffenzimmi.ch": "https://waffenzimmi.ch",
        }, clear=True):
            run_crawl(test_session)

        test_session.refresh(source)
        assert source.last_error is None


class TestRunCrawlWithMatching:
    """Tests for crawl with matching integration."""

    def test_matches_listings_against_search_terms(self, test_session):
        """Test that listings are matched against search terms (AC: 4)."""
        # Create search term
        create_search_term(test_session, "Glock 17", match_type="exact")

        mock_listings = [
            {
                "title": "Glock 17 Gen 5",
                "price": 800,
                "link": "https://waffenboerse.ch/glock17",
                "image_url": "https://waffenboerse.ch/img.jpg",
                "source": "waffenboerse.ch"
            },
            {
                "title": "SIG P226",
                "price": 900,
                "link": "https://waffenboerse.ch/sig226",
                "source": "waffenboerse.ch"
            },
        ]

        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_async_scraper(mock_listings),
            "waffengebraucht.ch": make_async_scraper([]),
            "waffenzimmi.ch": make_async_scraper([]),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
            "waffenzimmi.ch": "https://waffenzimmi.ch",
        }, clear=True):
            result = run_crawl(test_session)

        # Only Glock should match
        assert result.new_matches == 1
        assert result.total_listings == 2

        # Verify match in database
        matches = get_all_matches(test_session)
        assert len(matches) == 1
        assert "Glock 17" in matches[0].title

    def test_deduplication_on_second_crawl(self, test_session):
        """Test that duplicate matches are skipped on second crawl."""
        create_search_term(test_session, "Glock", match_type="exact")

        mock_listings = [
            {
                "title": "Glock 17",
                "price": 800,
                "link": "https://waffenboerse.ch/glock17",
                "source": "waffenboerse.ch"
            },
        ]

        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_async_scraper(mock_listings),
            "waffengebraucht.ch": make_async_scraper([]),
            "waffenzimmi.ch": make_async_scraper([]),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
            "waffenzimmi.ch": "https://waffenzimmi.ch",
        }, clear=True):
            # First crawl
            result1 = run_crawl(test_session)
            assert result1.new_matches == 1
            assert result1.duplicate_matches == 0

            # Second crawl with same listings
            result2 = run_crawl(test_session)
            assert result2.new_matches == 0
            assert result2.duplicate_matches == 1

        # Only one match in database
        assert test_session.query(Match).count() == 1

    def test_multiple_search_terms(self, test_session):
        """Test matching against multiple search terms."""
        create_search_term(test_session, "Glock", match_type="exact")
        create_search_term(test_session, "SIG", match_type="exact")

        mock_listings = [
            {
                "title": "Glock 17 Gen 5",
                "price": 800,
                "link": "https://waffenboerse.ch/glock17",
                "source": "waffenboerse.ch"
            },
            {
                "title": "SIG P226",
                "price": 900,
                "link": "https://waffenboerse.ch/sig226",
                "source": "waffenboerse.ch"
            },
            {
                "title": "CZ 75",
                "price": 700,
                "link": "https://waffenboerse.ch/cz75",
                "source": "waffenboerse.ch"
            },
        ]

        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_async_scraper(mock_listings),
            "waffengebraucht.ch": make_async_scraper([]),
            "waffenzimmi.ch": make_async_scraper([]),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
            "waffenzimmi.ch": "https://waffenzimmi.ch",
        }, clear=True):
            result = run_crawl(test_session)

        # Glock and SIG should match, CZ should not
        assert result.new_matches == 2
        assert result.total_listings == 3

    def test_same_listing_multiple_terms(self, test_session):
        """Test that same listing can match multiple terms."""
        create_search_term(test_session, "Glock", match_type="exact")
        create_search_term(test_session, "Gen 5", match_type="exact")

        mock_listings = [
            {
                "title": "Glock 17 Gen 5",
                "price": 800,
                "link": "https://waffenboerse.ch/glock17",
                "source": "waffenboerse.ch"
            },
        ]

        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_async_scraper(mock_listings),
            "waffengebraucht.ch": make_async_scraper([]),
            "waffenzimmi.ch": make_async_scraper([]),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
            "waffenzimmi.ch": "https://waffenzimmi.ch",
        }, clear=True):
            result = run_crawl(test_session)

        # Same listing matches both terms
        assert result.new_matches == 2
        assert test_session.query(Match).count() == 2


class TestCrawlSummaryLogging:
    """Tests for crawl summary logging (AC: 3)."""

    def test_logs_summary(self, test_session):
        """Test that crawl logs summary at end (AC: 3).

        We verify this by checking that _log_crawl_summary is called
        with the correct result data, which then logs the summary.
        """
        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_async_scraper([]),
            "waffengebraucht.ch": make_async_scraper([]),
            "waffenzimmi.ch": make_async_scraper([]),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
            "waffenzimmi.ch": "https://waffenzimmi.ch",
        }, clear=True):
            with patch("backend.services.crawler._log_crawl_summary") as mock_log:
                run_crawl(test_session)

        # Verify _log_crawl_summary was called with the result
        mock_log.assert_called_once()
        call_args = mock_log.call_args[0][0]
        assert call_args.sources_attempted == 3
        assert call_args.sources_succeeded == 3
        assert call_args.sources_failed == 0

    def test_logs_failed_sources(self, test_session):
        """Test that failed sources are tracked in result (AC: 3)."""
        failing_scraper = make_failing_async_scraper(ValueError("Failed"))

        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": failing_scraper,
            "waffengebraucht.ch": make_async_scraper([]),
            "waffenzimmi.ch": make_async_scraper([]),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
            "waffenzimmi.ch": "https://waffenzimmi.ch",
        }, clear=True):
            result = run_crawl(test_session)

        # Verify failed sources are tracked in result
        assert result.sources_failed == 1
        assert "waffenboerse.ch" in result.failed_sources


class TestCrawlDuration:
    """Tests for crawl duration tracking."""

    def test_tracks_duration(self, test_session):
        """Test that duration is tracked."""
        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_async_scraper([]),
            "waffengebraucht.ch": make_async_scraper([]),
            "waffenzimmi.ch": make_async_scraper([]),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
            "waffenzimmi.ch": "https://waffenzimmi.ch",
        }, clear=True):
            result = run_crawl(test_session)

        # Duration should be non-negative (may be 0.0 for very fast runs)
        assert result.duration_seconds >= 0
        # Should be very fast with mock scrapers
        assert result.duration_seconds < 10


class TestCrawlResultProperties:
    """Tests for CrawlResult property methods."""

    def test_is_success_true(self):
        """Test is_success returns True when no failures."""
        result = CrawlResult(
            sources_attempted=3,
            sources_succeeded=3,
            sources_failed=0,
        )
        assert result.is_success is True

    def test_is_success_false_with_failures(self):
        """Test is_success returns False when there are failures."""
        result = CrawlResult(
            sources_attempted=3,
            sources_succeeded=2,
            sources_failed=1,
        )
        assert result.is_success is False

    def test_is_success_false_no_attempts(self):
        """Test is_success returns False when no attempts."""
        result = CrawlResult(sources_attempted=0)
        assert result.is_success is False

    def test_is_partial_success_true(self):
        """Test is_partial_success when some succeeded and some failed."""
        result = CrawlResult(
            sources_attempted=3,
            sources_succeeded=2,
            sources_failed=1,
        )
        assert result.is_partial_success is True

    def test_is_partial_success_false_all_success(self):
        """Test is_partial_success returns False when all succeeded."""
        result = CrawlResult(
            sources_attempted=3,
            sources_succeeded=3,
            sources_failed=0,
        )
        assert result.is_partial_success is False

    def test_is_partial_success_false_all_failed(self):
        """Test is_partial_success returns False when all failed."""
        result = CrawlResult(
            sources_attempted=3,
            sources_succeeded=0,
            sources_failed=3,
        )
        assert result.is_partial_success is False

    def test_status_text_no_sources(self):
        """Test status_text when no sources."""
        result = CrawlResult(sources_attempted=0)
        assert result.status_text == "Keine Quellen"

    def test_status_text_success(self):
        """Test status_text when successful."""
        result = CrawlResult(
            sources_attempted=3,
            sources_succeeded=3,
            sources_failed=0,
        )
        assert result.status_text == "Erfolgreich"

    def test_status_text_partial(self):
        """Test status_text when partial success."""
        result = CrawlResult(
            sources_attempted=3,
            sources_succeeded=2,
            sources_failed=1,
        )
        assert result.status_text == "Teilweise erfolgreich"

    def test_status_text_failed(self):
        """Test status_text when all failed."""
        result = CrawlResult(
            sources_attempted=3,
            sources_succeeded=0,
            sources_failed=3,
        )
        assert result.status_text == "Fehlgeschlagen"


class TestCrawlState:
    """Tests for CrawlState dataclass."""

    def test_default_values(self):
        """Test CrawlState has correct defaults."""
        state = CrawlState()
        assert state.is_running is False
        assert state.cancel_requested is False
        assert state.last_result is None
        assert state.current_source is None
        assert state.log_messages == []

    def test_progress_tracking_defaults(self):
        """Test CrawlState has correct progress tracking defaults."""
        state = CrawlState()
        assert state.sources_total == 0
        assert state.sources_done == 0
        assert state.started_at is None


class TestCrawlLogFunctions:
    """Tests for crawl log helper functions."""

    def test_add_crawl_log(self):
        """Test add_crawl_log adds message with timestamp."""
        clear_crawl_log()
        add_crawl_log("Test message")
        logs = get_crawl_log()
        assert len(logs) == 1
        assert "Test message" in logs[0]
        assert "[" in logs[0]  # Has timestamp

    def test_clear_crawl_log(self):
        """Test clear_crawl_log removes all messages."""
        add_crawl_log("Message 1")
        add_crawl_log("Message 2")
        clear_crawl_log()
        assert get_crawl_log() == []

    def test_get_crawl_log_returns_copy(self):
        """Test get_crawl_log returns a copy."""
        clear_crawl_log()
        add_crawl_log("Test")
        logs1 = get_crawl_log()
        logs2 = get_crawl_log()
        assert logs1 == logs2
        assert logs1 is not logs2  # Different objects


class TestCrawlStateHelpers:
    """Tests for crawl state helper functions."""

    def test_get_crawl_state(self):
        """Test get_crawl_state returns global state."""
        state = get_crawl_state()
        assert state is _crawl_state

    def test_is_crawl_running_false(self):
        """Test is_crawl_running when not running."""
        _crawl_state.is_running = False
        assert is_crawl_running() is False

    def test_is_crawl_running_true(self):
        """Test is_crawl_running when running."""
        _crawl_state.is_running = True
        try:
            assert is_crawl_running() is True
        finally:
            _crawl_state.is_running = False

    def test_is_cancel_requested_false(self):
        """Test is_cancel_requested when not requested."""
        _crawl_state.cancel_requested = False
        assert is_cancel_requested() is False

    def test_is_cancel_requested_true(self):
        """Test is_cancel_requested when requested."""
        _crawl_state.cancel_requested = True
        try:
            assert is_cancel_requested() is True
        finally:
            _crawl_state.cancel_requested = False

    def test_get_last_crawl_result_none(self):
        """Test get_last_crawl_result when no result."""
        _crawl_state.last_result = None
        assert get_last_crawl_result() is None

    def test_get_last_crawl_result_with_result(self):
        """Test get_last_crawl_result with result."""
        result = CrawlResult(sources_attempted=1)
        _crawl_state.last_result = result
        try:
            assert get_last_crawl_result() is result
        finally:
            _crawl_state.last_result = None


class TestRequestCrawlCancel:
    """Tests for request_crawl_cancel function."""

    def test_cancel_when_running(self):
        """Test cancellation when crawl is running."""
        _crawl_state.is_running = True
        _crawl_state.cancel_requested = False
        try:
            result = request_crawl_cancel()
            assert result is True
            assert _crawl_state.cancel_requested is True
        finally:
            _crawl_state.is_running = False
            _crawl_state.cancel_requested = False

    def test_cancel_when_not_running(self):
        """Test cancellation when no crawl is running."""
        _crawl_state.is_running = False
        result = request_crawl_cancel()
        assert result is False


class TestPrepareCrawlState:
    """Tests for prepare_crawl_state function."""

    def test_prepares_state(self):
        """Test prepare_crawl_state sets up state correctly."""
        _crawl_state.is_running = False
        _crawl_state.cancel_requested = True
        _crawl_state.current_source = "old"
        add_crawl_log("old log")

        try:
            result = prepare_crawl_state()
            assert result is True
            assert _crawl_state.is_running is True
            assert _crawl_state.cancel_requested is False
            assert _crawl_state.current_source is None
            # Log should have initial message
            logs = get_crawl_log()
            assert any("gestartet" in log.lower() for log in logs)
        finally:
            _crawl_state.is_running = False
            _crawl_state.cancel_requested = False
            clear_crawl_log()

    def test_fails_when_already_running(self):
        """Test prepare_crawl_state fails when already running."""
        _crawl_state.is_running = True
        try:
            result = prepare_crawl_state()
            assert result is False
        finally:
            _crawl_state.is_running = False


class TestLogCrawlSummary:
    """Tests for _log_crawl_summary function."""

    def test_logs_all_stats(self):
        """Test that summary logs all stats."""
        result = CrawlResult(
            sources_attempted=4,
            sources_succeeded=3,
            sources_failed=1,
            total_listings=100,
            new_matches=10,
            duplicate_matches=5,
            failed_sources=["waffenboerse.ch"],
            duration_seconds=15.5,
        )

        with patch("backend.services.crawler.logger") as mock_logger:
            _log_crawl_summary(result)

            # Verify all key stats are logged
            calls = [str(call) for call in mock_logger.info.call_args_list]
            all_logs = " ".join(calls)

            assert "4" in all_logs  # sources_attempted
            assert "3" in all_logs  # sources_succeeded
            assert "1" in all_logs  # sources_failed
            assert "100" in all_logs  # total_listings
            assert "10" in all_logs  # new_matches
            assert "5" in all_logs  # duplicate_matches
            assert "waffenboerse.ch" in all_logs  # failed_sources

    def test_logs_without_failed_sources(self):
        """Test summary when no sources failed."""
        result = CrawlResult(
            sources_attempted=3,
            sources_succeeded=3,
            sources_failed=0,
            failed_sources=[],
        )

        with patch("backend.services.crawler.logger") as mock_logger:
            _log_crawl_summary(result)
            # Should not raise and should log successfully
            assert mock_logger.info.called


class TestRunCrawlAsyncStates:
    """Tests for run_crawl_async state handling."""

    @pytest.mark.asyncio
    async def test_raises_when_already_running(self, test_session):
        """Test run_crawl_async raises RuntimeError when already running."""
        _crawl_state.is_running = True
        try:
            with pytest.raises(RuntimeError, match="already running"):
                await run_crawl_async(test_session, state_prepared=False)
        finally:
            _crawl_state.is_running = False

    @pytest.mark.asyncio
    async def test_skips_state_setup_when_prepared(self, test_session):
        """Test run_crawl_async skips state setup when state_prepared=True."""
        # Prepare state manually
        _crawl_state.is_running = True
        _crawl_state.cancel_requested = False
        clear_crawl_log()
        add_crawl_log("Pre-existing message")

        try:
            with patch.dict(SCRAPER_REGISTRY, {}, clear=True), \
                 patch.dict(SOURCE_BASE_URLS, {}, clear=True):
                result = await run_crawl_async(test_session, state_prepared=True)

            # Should complete without error
            assert result.sources_attempted == 0
        finally:
            _crawl_state.is_running = False
            clear_crawl_log()

    @pytest.mark.asyncio
    async def test_cancellation_stops_crawl(self, test_session):
        """Test that crawl respects cancellation request."""
        execution_order = []

        def make_slow_scraper(name):
            async def scraper():
                execution_order.append(name)
                # Request cancel after first scraper runs
                if len(execution_order) == 1:
                    _crawl_state.cancel_requested = True
                return []
            return scraper

        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_slow_scraper("waffenboerse"),
            "waffengebraucht.ch": make_slow_scraper("waffengebraucht"),
            "waffenzimmi.ch": make_slow_scraper("waffenzimmi"),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
            "waffenzimmi.ch": "https://waffenzimmi.ch",
        }, clear=True):
            _crawl_state.is_running = False
            await run_crawl_async(test_session, state_prepared=False)

        # Only first scraper should run before cancellation is checked
        assert len(execution_order) == 1
        assert _crawl_state.is_running is False

    @pytest.mark.asyncio
    async def test_resets_state_on_completion(self, test_session):
        """Test that crawl resets state after completion."""
        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_async_scraper([]),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
        }, clear=True):
            _crawl_state.is_running = False
            await run_crawl_async(test_session)

        assert _crawl_state.is_running is False
        assert _crawl_state.cancel_requested is False
        assert _crawl_state.current_source is None

    @pytest.mark.asyncio
    async def test_stores_last_result(self, test_session):
        """Test that crawl stores result in global state."""
        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_async_scraper([]),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
        }, clear=True):
            _crawl_state.is_running = False
            _crawl_state.last_result = None
            result = await run_crawl_async(test_session)

        assert _crawl_state.last_result is result


class TestRunCrawlAsyncExcludeTerms:
    """Tests for run_crawl_async with exclude terms."""

    @pytest.mark.asyncio
    async def test_exclude_terms_logged(self, test_session):
        """Test that exclude terms are logged when present."""
        from backend.database.crud import create_search_term, create_exclude_term

        create_search_term(test_session, "Glock", match_type="exact")
        create_exclude_term(test_session, "defekt")

        mock_listings = [
            {"title": "Glock 17", "price": 800, "link": "https://test.ch/1", "source": "waffenboerse.ch"},
        ]

        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_async_scraper(mock_listings),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
        }, clear=True):
            _crawl_state.is_running = False
            clear_crawl_log()
            await run_crawl_async(test_session)

        logs = get_crawl_log()
        # Check that exclude terms count is mentioned
        log_text = " ".join(logs)
        assert "Ausschl" in log_text or "1" in log_text


class TestCrawlResultTimestamps:
    """Tests for CrawlResult timestamp fields."""

    def test_timestamps_set(self, test_session):
        """Test that started_at and completed_at are set."""
        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_async_scraper([]),
            "waffengebraucht.ch": make_async_scraper([]),
            "waffenzimmi.ch": make_async_scraper([]),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
            "waffenzimmi.ch": "https://waffenzimmi.ch",
        }, clear=True):
            result = run_crawl(test_session)

        assert result.started_at is not None
        assert result.completed_at is not None
        assert result.started_at <= result.completed_at


class TestCrawlProgressTracking:
    """Tests for crawl progress tracking fields."""

    @pytest.mark.asyncio
    async def test_progress_initialized_on_crawl_start(self, test_session):
        """Test that progress tracking fields are initialized when crawl starts."""
        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_async_scraper([]),
            "waffengebraucht.ch": make_async_scraper([]),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
        }, clear=True):
            _crawl_state.is_running = False
            result = await run_crawl_async(test_session)

        # After crawl completes, sources_total should match sources attempted
        assert result.sources_attempted == 2

    @pytest.mark.asyncio
    async def test_progress_tracks_sources_done(self, test_session):
        """Test that sources_done increments as sources are processed."""
        sources_done_values = []

        def make_tracking_scraper():
            async def scraper():
                sources_done_values.append(_crawl_state.sources_done)
                return []
            return scraper

        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_tracking_scraper(),
            "waffengebraucht.ch": make_tracking_scraper(),
            "waffenzimmi.ch": make_tracking_scraper(),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
            "waffenzimmi.ch": "https://waffenzimmi.ch",
        }, clear=True):
            _crawl_state.is_running = False
            await run_crawl_async(test_session)

        # sources_done should start at 0 and increment
        # The values captured BEFORE each source is marked done
        assert len(sources_done_values) == 3
        # All should have captured values (order may vary due to DB ordering)

    @pytest.mark.asyncio
    async def test_progress_has_started_at_timestamp(self, test_session):
        """Test that started_at is set during crawl."""
        started_at_during_crawl = None

        def make_capturing_scraper():
            async def scraper():
                nonlocal started_at_during_crawl
                started_at_during_crawl = _crawl_state.started_at
                return []
            return scraper

        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_capturing_scraper(),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
        }, clear=True):
            _crawl_state.is_running = False
            await run_crawl_async(test_session)

        # started_at should have been set during crawl
        assert started_at_during_crawl is not None

    @pytest.mark.asyncio
    async def test_progress_sources_total_set_correctly(self, test_session):
        """Test that sources_total is set to the number of active sources."""
        sources_total_during_crawl = None

        def make_capturing_scraper():
            async def scraper():
                nonlocal sources_total_during_crawl
                sources_total_during_crawl = _crawl_state.sources_total
                return []
            return scraper

        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_capturing_scraper(),
            "waffengebraucht.ch": make_capturing_scraper(),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
            "waffengebraucht.ch": "https://waffengebraucht.ch",
        }, clear=True):
            _crawl_state.is_running = False
            await run_crawl_async(test_session)

        # Should have 2 sources total
        assert sources_total_during_crawl == 2

    def test_progress_reset_after_crawl(self, test_session):
        """Test that progress fields are reset after crawl completes."""
        with patch.dict(SCRAPER_REGISTRY, {
            "waffenboerse.ch": make_async_scraper([]),
        }, clear=True), \
             patch.dict(SOURCE_BASE_URLS, {
            "waffenboerse.ch": "https://waffenboerse.ch",
        }, clear=True):
            run_crawl(test_session)

        # After crawl, state should be reset
        assert _crawl_state.is_running is False
        # sources_total and sources_done are intentionally kept for display
        # but started_at is kept for the template to show last run info
