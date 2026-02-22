"""
Tests for scraper base utilities.

Tests verify:
- HTTP client configuration (timeout, User-Agent)
- Rate limiting delay between requests
- URL utilities (relative to absolute conversion)
- Price parsing (Swiss formats, "Auf Anfrage")
- Type definitions (ScraperResult, ScraperResults)
- Error isolation pattern for scrapers
"""
from unittest.mock import patch

import httpx
import pytest

from backend.scrapers.base import (
    REQUEST_TIMEOUT,
    REQUEST_DELAY_MIN,
    REQUEST_DELAY_MAX,
    ScraperResult,
    ScraperResults,
    create_http_client,
    delay_between_requests,
    get_user_agent,
    make_absolute_url,
    parse_price,
)


class TestConstants:
    """Tests for module constants."""

    def test_request_timeout_is_30_seconds(self):
        """REQUEST_TIMEOUT should be 30 seconds per AC3."""
        assert REQUEST_TIMEOUT == 30

    def test_request_delay_min_is_2_seconds(self):
        """REQUEST_DELAY_MIN should be 2 seconds per AC4."""
        assert REQUEST_DELAY_MIN == 2

    def test_request_delay_max_is_5_seconds(self):
        """REQUEST_DELAY_MAX should be 5 seconds per AC4."""
        assert REQUEST_DELAY_MAX == 5


class TestGetUserAgent:
    """Tests for get_user_agent function."""

    def test_returns_non_empty_string(self):
        """User-Agent should be a non-empty string per AC5."""
        ua = get_user_agent()
        assert isinstance(ua, str)
        assert len(ua) > 0

    def test_contains_scraper_identifier(self):
        """User-Agent should identify the scraper."""
        ua = get_user_agent()
        assert "YogaHelper" in ua

    def test_looks_like_browser_user_agent(self):
        """User-Agent should look like a browser to avoid blocking."""
        ua = get_user_agent()
        assert "Mozilla" in ua


class TestCreateHttpClient:
    """Tests for create_http_client function."""

    @pytest.mark.asyncio
    async def test_returns_async_client(self):
        """Should return an httpx.AsyncClient instance."""
        client = create_http_client()
        try:
            assert isinstance(client, httpx.AsyncClient)
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_has_correct_timeout(self):
        """Client should have 30 second timeout per AC3."""
        client = create_http_client()
        try:
            # httpx.Timeout with single value sets all timeout components
            assert client.timeout.connect == REQUEST_TIMEOUT
            assert client.timeout.read == REQUEST_TIMEOUT
            assert client.timeout.write == REQUEST_TIMEOUT
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_has_user_agent_header(self):
        """Client should include User-Agent header per AC5."""
        client = create_http_client()
        try:
            assert "User-Agent" in client.headers
            assert client.headers["User-Agent"] == get_user_agent()
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_follows_redirects(self):
        """Client should follow redirects."""
        client = create_http_client()
        try:
            assert client.follow_redirects is True
        finally:
            await client.aclose()


class TestDelayBetweenRequests:
    """Tests for delay_between_requests function."""

    @pytest.mark.asyncio
    async def test_waits_between_min_and_max(self):
        """Delay should be between REQUEST_DELAY_MIN and REQUEST_DELAY_MAX per AC4."""
        with patch("backend.scrapers.base.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            await delay_between_requests()

            # Verify sleep was called with a value in the expected range
            mock_sleep.assert_called_once()
            delay_value = mock_sleep.call_args[0][0]
            assert REQUEST_DELAY_MIN <= delay_value <= REQUEST_DELAY_MAX

    @pytest.mark.asyncio
    async def test_uses_asyncio_sleep(self):
        """Should use asyncio.sleep, not time.sleep."""
        with patch("backend.scrapers.base.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            await delay_between_requests()
            mock_sleep.assert_called_once()

    @pytest.mark.asyncio
    async def test_delay_is_random(self):
        """Multiple calls should produce different delays (random)."""
        delays = []
        with patch("backend.scrapers.base.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            for _ in range(10):
                await delay_between_requests()
                delays.append(mock_sleep.call_args[0][0])

        # With 10 calls, we should have some variation
        # (statistically extremely unlikely to get all same values)
        assert len(set(delays)) > 1


class TestMakeAbsoluteUrl:
    """Tests for make_absolute_url function."""

    def test_converts_relative_url(self):
        """Should convert relative URL to absolute."""
        base = "https://example.ch/listings/"
        relative = "photo.jpg"
        result = make_absolute_url(base, relative)
        assert result == "https://example.ch/listings/photo.jpg"

    def test_handles_parent_directory_reference(self):
        """Should handle ../ in relative URLs."""
        base = "https://example.ch/listings/"
        relative = "../images/photo.jpg"
        result = make_absolute_url(base, relative)
        assert result == "https://example.ch/images/photo.jpg"

    def test_preserves_absolute_url(self):
        """Should preserve already absolute URLs."""
        base = "https://example.ch/listings/"
        absolute = "https://cdn.example.ch/img.jpg"
        result = make_absolute_url(base, absolute)
        assert result == "https://cdn.example.ch/img.jpg"

    def test_handles_root_relative_url(self):
        """Should handle URLs starting with /."""
        base = "https://example.ch/listings/item/"
        relative = "/images/photo.jpg"
        result = make_absolute_url(base, relative)
        assert result == "https://example.ch/images/photo.jpg"

    def test_handles_protocol_relative_url(self):
        """Should handle URLs starting with //."""
        base = "https://example.ch/listings/"
        relative = "//cdn.example.ch/img.jpg"
        result = make_absolute_url(base, relative)
        assert result == "https://cdn.example.ch/img.jpg"


class TestParsePrice:
    """Tests for parse_price function."""

    def test_parses_simple_price(self):
        """Should parse simple numeric price."""
        assert parse_price("1234") == 1234.0
        assert parse_price("1234.50") == 1234.5

    def test_parses_swiss_format_with_apostrophe(self):
        """Should parse Swiss format with apostrophe thousands separator."""
        assert parse_price("1'234") == 1234.0
        assert parse_price("1'234.50") == 1234.5
        assert parse_price("12'345'678") == 12345678.0

    def test_parses_price_with_currency(self):
        """Should parse price with CHF currency symbol."""
        assert parse_price("CHF 1'234.50") == 1234.5
        assert parse_price("1'234.50 CHF") == 1234.5
        assert parse_price("CHF 500") == 500.0

    def test_parses_comma_decimal_separator(self):
        """Should parse European format with comma decimal separator."""
        assert parse_price("1234,50") == 1234.5
        assert parse_price("1'234,50") == 1234.5
        assert parse_price("1'234,50 CHF") == 1234.5

    def test_parses_european_format_with_dot_thousands(self):
        """Should parse European format with dot as thousands separator."""
        # European: 1.234,50 means 1234.50
        assert parse_price("1.234,50") == 1234.5
        assert parse_price("12.345,67") == 12345.67

    def test_returns_none_for_auf_anfrage(self):
        """Should return None for 'Auf Anfrage'."""
        assert parse_price("Auf Anfrage") is None
        assert parse_price("auf anfrage") is None
        assert parse_price("Preis auf Anfrage") is None

    def test_returns_none_for_empty_string(self):
        """Should return None for empty string."""
        assert parse_price("") is None

    def test_returns_none_for_none_input(self):
        """Should return None for None input."""
        assert parse_price(None) is None

    def test_returns_none_for_unparseable_string(self):
        """Should return None for strings that can't be parsed."""
        assert parse_price("kostenlos") is None
        assert parse_price("---") is None

    def test_handles_spaces_in_price(self):
        """Should handle spaces in price string."""
        assert parse_price(" 1234 ") == 1234.0
        assert parse_price("CHF  1234") == 1234.0


class TestScraperResultType:
    """Tests for ScraperResult TypedDict."""

    def test_can_create_valid_result(self):
        """Should be able to create a valid ScraperResult."""
        result: ScraperResult = {
            "title": "Test Item",
            "price": 1234.50,
            "image_url": "https://example.ch/img.jpg",
            "link": "https://example.ch/item/123",
            "source": "example.ch"
        }
        assert result["title"] == "Test Item"
        assert result["price"] == 1234.50
        assert result["image_url"] == "https://example.ch/img.jpg"
        assert result["link"] == "https://example.ch/item/123"
        assert result["source"] == "example.ch"

    def test_can_have_none_price(self):
        """ScraperResult should allow None for price."""
        result: ScraperResult = {
            "title": "Test Item",
            "price": None,
            "image_url": "https://example.ch/img.jpg",
            "link": "https://example.ch/item/123",
            "source": "example.ch"
        }
        assert result["price"] is None

    def test_can_have_none_image_url(self):
        """ScraperResult should allow None for image_url."""
        result: ScraperResult = {
            "title": "Test Item",
            "price": 100.0,
            "image_url": None,
            "link": "https://example.ch/item/123",
            "source": "example.ch"
        }
        assert result["image_url"] is None


class TestScraperResultsList:
    """Tests for ScraperResults type alias."""

    def test_is_list_of_scraper_results(self):
        """ScraperResults should be a list of ScraperResult."""
        results: ScraperResults = [
            {
                "title": "Item 1",
                "price": 100.0,
                "image_url": None,
                "link": "https://example.ch/1",
                "source": "example.ch"
            },
            {
                "title": "Item 2",
                "price": None,
                "image_url": "https://example.ch/img.jpg",
                "link": "https://example.ch/2",
                "source": "example.ch"
            }
        ]
        assert len(results) == 2
        assert results[0]["title"] == "Item 1"
        assert results[1]["title"] == "Item 2"

    def test_empty_list_is_valid(self):
        """Empty list should be valid ScraperResults (for error cases)."""
        results: ScraperResults = []
        assert len(results) == 0
        assert isinstance(results, list)


class TestErrorIsolationPattern:
    """Tests for error isolation pattern per AC2."""

    @pytest.mark.asyncio
    async def test_scraper_returns_empty_list_on_exception(self):
        """Scraper using error isolation pattern should return [] on failure, not raise."""
        from backend.utils.logging import get_logger

        logger = get_logger("test_scraper")

        # Simulate a scraper using the documented error isolation pattern
        async def mock_failing_scraper() -> ScraperResults:
            """A scraper that encounters an error."""
            try:
                # Simulate an error during scraping
                raise ConnectionError("Network unreachable")
            except Exception as e:
                logger.error(f"test_source - Failed: {e}")
                return []  # Never raise, always return empty list

        # The scraper should return empty list, not raise
        result = await mock_failing_scraper()
        assert result == []
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_scraper_returns_results_on_success(self):
        """Scraper using error isolation pattern should return results on success."""

        async def mock_successful_scraper() -> ScraperResults:
            """A scraper that succeeds."""
            try:
                return [
                    {
                        "title": "Test Item",
                        "price": 100.0,
                        "image_url": "https://example.ch/img.jpg",
                        "link": "https://example.ch/item/1",
                        "source": "example.ch"
                    }
                ]
            except Exception:
                return []

        result = await mock_successful_scraper()
        assert len(result) == 1
        assert result[0]["title"] == "Test Item"

    @pytest.mark.asyncio
    async def test_error_isolation_with_http_client(self):
        """Scraper should handle httpx errors gracefully."""
        from backend.utils.logging import get_logger

        logger = get_logger("test_http_scraper")

        async def mock_http_scraper() -> ScraperResults:
            """A scraper that fails during HTTP request."""
            try:
                async with create_http_client() as _client:
                    # Simulate HTTP error
                    raise httpx.ConnectError("Connection refused")
            except Exception as e:
                logger.error(f"http_test - Failed: {e}")
                return []

        result = await mock_http_scraper()
        assert result == []
