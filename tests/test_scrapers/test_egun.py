"""
Tests for egun.de scraper.

Tests verify:
- Table row parsing from search results
- Price extraction (EUR format)
- Image URL extraction
- Pagination detection
- Error handling
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.scrapers.egun import (
    SOURCE_NAME,
    scrape_egun,
    _extract_image_url,
    _extract_price,
    _find_parent_row,
    _has_next_page,
    _parse_listing,
)
from bs4 import BeautifulSoup


# Sample HTML fixtures
SAMPLE_HTML_TABLE_RESULTS = """
<html>
<body>
    <table>
        <tr>
            <td><img src="/images/sig.jpg"></td>
            <td><a href="item.php?id=12345">SIG Sauer P226</a></td>
            <td>500,00 EUR</td>
        </tr>
        <tr>
            <td><img src="/images/glock.jpg"></td>
            <td><a href="item.php?id=12346">Glock 17</a></td>
            <td>450,00 EUR</td>
        </tr>
    </table>
</body>
</html>
"""

SAMPLE_HTML_NO_RESULTS = """
<html>
<body>
    <div class="no-results">
        <p>Keine Ergebnisse</p>
    </div>
</body>
</html>
"""

SAMPLE_HTML_WITH_PAGINATION = """
<html>
<body>
    <table>
        <tr>
            <td><a href="item.php?id=123">Test Gun</a></td>
            <td>100.00 EUR</td>
        </tr>
    </table>
    <div class="pagination">
        <a href="list_items.php?keyword=sig&page=1">1</a>
        <a href="list_items.php?keyword=sig&page=2">2</a>
        <a href="list_items.php?keyword=sig&page=3">3</a>
    </div>
</body>
</html>
"""


class TestFindParentRow:
    """Tests for _find_parent_row helper."""

    def test_finds_parent_tr(self):
        """Find parent tr element."""
        html = '<table><tr><td><a href="item.php?id=1">Gun</a></td></tr></table>'
        soup = BeautifulSoup(html, "lxml")
        link = soup.select_one("a")
        row = _find_parent_row(link)
        assert row is not None
        assert row.name == "tr"

    def test_returns_none_when_no_tr(self):
        """Return None when no parent tr."""
        html = '<div><a href="item.php?id=1">Gun</a></div>'
        soup = BeautifulSoup(html, "lxml")
        link = soup.select_one("a")
        assert _find_parent_row(link) is None


class TestExtractPrice:
    """Tests for _extract_price helper."""

    def test_extracts_price_eur_format(self):
        """Extract price in EUR format (German: comma as decimal)."""
        html = '<tr><td>500,00 EUR</td></tr>'
        soup = BeautifulSoup(html, "lxml")
        row = soup.select_one("tr")
        assert _extract_price(row) == 500.0

    def test_extracts_price_german_format(self):
        """Extract price in German format (dot thousands, comma decimal)."""
        html = '<tr><td>1.234,56 EUR</td></tr>'
        soup = BeautifulSoup(html, "lxml")
        row = soup.select_one("tr")
        assert _extract_price(row) == 1234.56

    def test_returns_none_for_no_price(self):
        """Return None when no price found."""
        html = '<tr><td>No price</td></tr>'
        soup = BeautifulSoup(html, "lxml")
        row = soup.select_one("tr")
        assert _extract_price(row) is None


class TestExtractImageUrl:
    """Tests for _extract_image_url helper."""

    def test_extracts_image_src(self):
        """Extract image from src attribute."""
        html = '<tr><td><img src="/images/gun.jpg"></td></tr>'
        soup = BeautifulSoup(html, "lxml")
        row = soup.select_one("tr")
        img_url = _extract_image_url(row)
        assert img_url is not None
        assert "gun.jpg" in img_url

    def test_returns_none_for_no_image(self):
        """Return None when no image found."""
        html = '<tr><td>No image</td></tr>'
        soup = BeautifulSoup(html, "lxml")
        row = soup.select_one("tr")
        assert _extract_image_url(row) is None

    def test_skips_placeholder_images(self):
        """Skip placeholder images."""
        html = '<tr><td><img src="/images/placeholder.gif"></td></tr>'
        soup = BeautifulSoup(html, "lxml")
        row = soup.select_one("tr")
        assert _extract_image_url(row) is None


class TestHasNextPage:
    """Tests for _has_next_page helper."""

    def test_detects_pagination(self):
        """Detect pagination links."""
        soup = BeautifulSoup(SAMPLE_HTML_WITH_PAGINATION, "lxml")
        assert _has_next_page(soup, 1) is True

    def test_returns_false_for_last_page(self):
        """Return False when on last page."""
        soup = BeautifulSoup(SAMPLE_HTML_WITH_PAGINATION, "lxml")
        assert _has_next_page(soup, 3) is False

    def test_returns_false_for_no_pagination(self):
        """Return False when no pagination."""
        soup = BeautifulSoup(SAMPLE_HTML_NO_RESULTS, "lxml")
        assert _has_next_page(soup, 1) is False


class TestParseListing:
    """Tests for _parse_listing helper."""

    def test_parses_complete_listing(self):
        """Parse listing with all fields."""
        html = '''
        <tr>
            <td><img src="/images/gun.jpg"></td>
            <td><a href="item.php?id=123">Test Gun</a></td>
            <td>500,00 EUR</td>
        </tr>
        '''
        soup = BeautifulSoup(html, "lxml")
        row = soup.select_one("tr")
        link = soup.select_one("a")
        result = _parse_listing(row, link)

        assert result is not None
        assert result["title"] == "Test Gun"
        assert result["price"] == 500.0
        assert result["source"] == SOURCE_NAME

    def test_returns_none_for_empty_title(self):
        """Return None when title is empty."""
        html = '<tr><td><a href="item.php?id=123"></a></td></tr>'
        soup = BeautifulSoup(html, "lxml")
        row = soup.select_one("tr")
        link = soup.select_one("a")
        assert _parse_listing(row, link) is None


class TestScrapeEgun:
    """Tests for scrape_egun main function."""

    @pytest.mark.asyncio
    async def test_extracts_table_results(self):
        """Test extraction from table structure."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_HTML_TABLE_RESULTS
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.egun.create_http_client", return_value=mock_client):
            with patch("backend.scrapers.egun.delay_between_requests", new_callable=AsyncMock):
                with patch("backend.services.crawler.add_crawl_log"):
                    results = await scrape_egun(search_terms=["sig"])

        assert len(results) == 2
        assert results[0]["title"] == "SIG Sauer P226"
        assert results[0]["price"] == 500.0

    @pytest.mark.asyncio
    async def test_returns_empty_on_http_error(self):
        """Test that HTTP errors return empty list."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500)
        ))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.egun.create_http_client", return_value=mock_client):
            with patch("backend.services.crawler.add_crawl_log"):
                results = await scrape_egun(search_terms=["sig"])

        assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_search_terms(self):
        """Test that empty search terms return empty list."""
        results = await scrape_egun(search_terms=[])
        assert results == []

    @pytest.mark.asyncio
    async def test_deduplicates_by_item_id(self):
        """Test that items with same ID are not duplicated."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_HTML_TABLE_RESULTS
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.egun.create_http_client", return_value=mock_client):
            with patch("backend.scrapers.egun.delay_between_requests", new_callable=AsyncMock):
                with patch("backend.services.crawler.add_crawl_log"):
                    # Two search terms returning same products
                    results = await scrape_egun(search_terms=["sig", "glock"])

        # Should only have 2 unique results
        assert len(results) == 2
