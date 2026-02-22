"""
Tests for gebrauchtwaffen.com scraper.

Tests verify:
- Listing parsing from div.item containers
- Price extraction (CHF format)
- Image URL extraction
- Pagination detection (iPage,N pattern)
- Error handling
- Deduplication
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.scrapers.gebrauchtwaffen import (
    SOURCE_NAME,
    scrape_gebrauchtwaffen,
    _has_next_page,
    _parse_listing,
)
from bs4 import BeautifulSoup


# Sample HTML fixtures
SAMPLE_HTML_RESULTS = """
<html>
<body>
    <div class="item">
        <h3><a href="/listing/12345">SIG Sauer P226</a></h3>
        <div class="price">CHF 1'250.00</div>
        <img src="https://d1abc.cloudfront.net/img/sig226.jpg">
    </div>
    <div class="item">
        <h3><a href="/listing/12346">Glock 17 Gen5</a></h3>
        <div class="price">CHF 850.00</div>
        <img src="https://d1abc.cloudfront.net/img/glock17.jpg">
    </div>
</body>
</html>
"""

SAMPLE_HTML_NO_RESULTS = """
<html>
<body>
    <div class="search-results">
        <p>Keine Ergebnisse gefunden</p>
    </div>
</body>
</html>
"""

SAMPLE_HTML_WITH_PAGINATION = """
<html>
<body>
    <div class="item">
        <h3><a href="/listing/100">Test Waffe</a></h3>
        <div class="price">CHF 500.00</div>
        <img src="https://d1abc.cloudfront.net/img/test.jpg">
    </div>
    <div class="pagination">
        <a href="index.php?page=search&sPattern=sig&iPage,1">1</a>
        <a href="index.php?page=search&sPattern=sig&iPage,2">2</a>
        <a href="index.php?page=search&sPattern=sig&iPage,3">3</a>
    </div>
</body>
</html>
"""

SAMPLE_HTML_MISSING_FIELDS = """
<html>
<body>
    <div class="item">
        <h3><a href="/listing/200">Nur Titel</a></h3>
    </div>
    <div class="item">
        <h3><a href="">Kein Link</a></h3>
        <div class="price">CHF 100.00</div>
    </div>
    <div class="item">
        <h3><a href="/listing/201"></a></h3>
        <div class="price">CHF 200.00</div>
    </div>
</body>
</html>
"""


class TestParseListing:
    """Tests for _parse_listing helper."""

    def test_parses_complete_listing(self):
        """Parse listing with all fields."""
        html = """
        <div class="item">
            <h3><a href="/listing/123">SIG Sauer P226</a></h3>
            <div class="price">CHF 1'250.00</div>
            <img src="https://d1abc.cloudfront.net/img/sig.jpg">
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        item = soup.select_one("div.item")
        result = _parse_listing(item)

        assert result is not None
        assert result["title"] == "SIG Sauer P226"
        assert result["price"] == 1250.0
        assert result["image_url"] == "https://d1abc.cloudfront.net/img/sig.jpg"
        assert "listing/123" in result["link"]
        assert result["source"] == SOURCE_NAME

    def test_returns_none_for_empty_title(self):
        """Return None when title is empty."""
        html = """
        <div class="item">
            <h3><a href="/listing/123"></a></h3>
            <div class="price">CHF 500.00</div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        item = soup.select_one("div.item")
        assert _parse_listing(item) is None

    def test_returns_none_for_missing_link(self):
        """Return None when href is empty."""
        html = """
        <div class="item">
            <h3><a href="">Test Gun</a></h3>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        item = soup.select_one("div.item")
        assert _parse_listing(item) is None

    def test_returns_none_for_no_h3_link(self):
        """Return None when no h3 > a element found."""
        html = """
        <div class="item">
            <p>Some text</p>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        item = soup.select_one("div.item")
        assert _parse_listing(item) is None

    def test_handles_missing_price(self):
        """Parse listing with no price div."""
        html = """
        <div class="item">
            <h3><a href="/listing/123">Waffe ohne Preis</a></h3>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        item = soup.select_one("div.item")
        result = _parse_listing(item)

        assert result is not None
        assert result["title"] == "Waffe ohne Preis"
        assert result["price"] is None
        assert result["image_url"] is None

    def test_handles_missing_image(self):
        """Parse listing with no image."""
        html = """
        <div class="item">
            <h3><a href="/listing/123">Waffe ohne Bild</a></h3>
            <div class="price">CHF 300.00</div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        item = soup.select_one("div.item")
        result = _parse_listing(item)

        assert result is not None
        assert result["image_url"] is None
        assert result["price"] == 300.0


class TestHasNextPage:
    """Tests for _has_next_page helper."""

    def test_detects_pagination(self):
        """Detect iPage pagination links."""
        soup = BeautifulSoup(SAMPLE_HTML_WITH_PAGINATION, "html.parser")
        assert _has_next_page(soup, 1) is True

    def test_returns_false_for_last_page(self):
        """Return False when on last page."""
        soup = BeautifulSoup(SAMPLE_HTML_WITH_PAGINATION, "html.parser")
        assert _has_next_page(soup, 3) is False

    def test_returns_false_for_no_pagination(self):
        """Return False when no pagination links."""
        soup = BeautifulSoup(SAMPLE_HTML_NO_RESULTS, "html.parser")
        assert _has_next_page(soup, 1) is False

    def test_detects_next_from_middle_page(self):
        """Detect next page when on page 2."""
        soup = BeautifulSoup(SAMPLE_HTML_WITH_PAGINATION, "html.parser")
        assert _has_next_page(soup, 2) is True


class TestScrapeGebrauchtwaffen:
    """Tests for scrape_gebrauchtwaffen main function."""

    @pytest.mark.asyncio
    async def test_extracts_results(self):
        """Test extraction from div.item structure."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_HTML_RESULTS
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.gebrauchtwaffen.create_http_client", return_value=mock_client):
            with patch("backend.scrapers.gebrauchtwaffen.delay_between_requests", new_callable=AsyncMock):
                with patch("backend.services.crawler.add_crawl_log"):
                    results = await scrape_gebrauchtwaffen(search_terms=["sig"])

        assert len(results) == 2
        assert results[0]["title"] == "SIG Sauer P226"
        assert results[0]["price"] == 1250.0
        assert results[0]["source"] == SOURCE_NAME
        assert results[1]["title"] == "Glock 17 Gen5"

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_search_terms(self):
        """Test that empty search terms return empty list."""
        results = await scrape_gebrauchtwaffen(search_terms=[])
        assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_http_error(self):
        """Test that HTTP errors return empty list."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        ))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.gebrauchtwaffen.create_http_client", return_value=mock_client):
            with patch("backend.services.crawler.add_crawl_log"):
                results = await scrape_gebrauchtwaffen(search_terms=["sig"])

        assert results == []

    @pytest.mark.asyncio
    async def test_deduplicates_by_link(self):
        """Test that items with same link across search terms are deduplicated."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_HTML_RESULTS
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.gebrauchtwaffen.create_http_client", return_value=mock_client):
            with patch("backend.scrapers.gebrauchtwaffen.delay_between_requests", new_callable=AsyncMock):
                with patch("backend.services.crawler.add_crawl_log"):
                    # Two search terms returning same products
                    results = await scrape_gebrauchtwaffen(search_terms=["sig", "glock"])

        # Should only have 2 unique results (not 4)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_handles_no_results_page(self):
        """Test handling of page with no div.item results."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_HTML_NO_RESULTS
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.gebrauchtwaffen.create_http_client", return_value=mock_client):
            with patch("backend.scrapers.gebrauchtwaffen.delay_between_requests", new_callable=AsyncMock):
                with patch("backend.services.crawler.add_crawl_log"):
                    results = await scrape_gebrauchtwaffen(search_terms=["xyz_nonexistent"])

        assert results == []
