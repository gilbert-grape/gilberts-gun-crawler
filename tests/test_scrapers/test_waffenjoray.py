"""
Tests for waffen-joray.ch scraper.

Tests verify:
- Joomla search result parsing
- Multiple result container patterns
- Link validation
- Error handling
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.scrapers.waffenjoray import (
    SOURCE_NAME,
    scrape_waffenjoray,
    _parse_search_result_dt,
    _parse_search_result_item,
    _parse_h3_link,
    _parse_product_link,
    _is_product_link,
)
from bs4 import BeautifulSoup


# Sample HTML fixtures
SAMPLE_HTML_DL_RESULTS = """
<html>
<body>
    <dl class="search-results">
        <dt><a href="/waffen/pistolen/sig-p226-detail">SIG P226</a></dt>
        <dd>Description of SIG P226</dd>
        <dt><a href="/waffen/pistolen/glock-17-detail">Glock 17</a></dt>
        <dd>Description of Glock 17</dd>
    </dl>
</body>
</html>
"""

SAMPLE_HTML_H3_RESULTS = """
<html>
<body>
    <div class="results">
        <h3><a href="/waffen/123/cz-75-detail">CZ 75</a></h3>
        <p>Description</p>
        <h3><a href="/waffen/124/beretta-92-detail">Beretta 92</a></h3>
        <p>Description</p>
    </div>
</body>
</html>
"""

SAMPLE_HTML_NO_RESULTS = """
<html>
<body>
    <div class="no-results">
        <p>Keine Ergebnisse gefunden</p>
    </div>
</body>
</html>
"""


class TestParseSearchResultDt:
    """Tests for _parse_search_result_dt helper."""

    def test_parses_dt_with_link(self):
        """Parse dt element with link."""
        html = '<dt><a href="/waffen/sig-p226-detail">SIG P226</a></dt>'
        soup = BeautifulSoup(html, "lxml")
        dt = soup.select_one("dt")
        result = _parse_search_result_dt(dt)

        assert result is not None
        assert result["title"] == "SIG P226"
        assert result["source"] == SOURCE_NAME

    def test_returns_none_for_missing_link(self):
        """Return None when no link in dt."""
        html = '<dt>No link here</dt>'
        soup = BeautifulSoup(html, "lxml")
        dt = soup.select_one("dt")
        assert _parse_search_result_dt(dt) is None

    def test_returns_none_for_empty_title(self):
        """Return None when title is empty."""
        html = '<dt><a href="/test"></a></dt>'
        soup = BeautifulSoup(html, "lxml")
        dt = soup.select_one("dt")
        assert _parse_search_result_dt(dt) is None


class TestParseSearchResultItem:
    """Tests for _parse_search_result_item helper."""

    def test_parses_item_with_product_link(self):
        """Parse item with product link."""
        html = '<div class="result"><a href="/waffen/sig-detail">SIG Sauer</a></div>'
        soup = BeautifulSoup(html, "lxml")
        item = soup.select_one("div.result")
        result = _parse_search_result_item(item)

        assert result is not None
        assert result["title"] == "SIG Sauer"

    def test_returns_none_for_missing_link(self):
        """Return None when no link found."""
        html = '<div class="result"><span>No link</span></div>'
        soup = BeautifulSoup(html, "lxml")
        item = soup.select_one("div.result")
        assert _parse_search_result_item(item) is None


class TestParseH3Link:
    """Tests for _parse_h3_link helper."""

    def test_parses_h3_product_link(self):
        """Parse h3 link to product page."""
        html = '<a href="/waffen/123/sig-detail">SIG P226</a>'
        soup = BeautifulSoup(html, "lxml")
        link = soup.select_one("a")
        result = _parse_h3_link(link)

        assert result is not None
        assert result["title"] == "SIG P226"

    def test_returns_none_for_non_product_link(self):
        """Return None for non-product links."""
        html = '<a href="/kategorie/waffen">Waffen</a>'
        soup = BeautifulSoup(html, "lxml")
        link = soup.select_one("a")
        assert _parse_h3_link(link) is None


class TestParseProductLink:
    """Tests for _parse_product_link helper."""

    def test_parses_detail_link(self):
        """Parse link ending with -detail."""
        html = '<a href="/sig-p226-detail">SIG P226</a>'
        soup = BeautifulSoup(html, "lxml")
        link = soup.select_one("a")
        result = _parse_product_link(link)

        assert result is not None
        assert result["title"] == "SIG P226"

    def test_skips_navigation_links(self):
        """Skip navigation links like 'mehr', 'weiter'."""
        html = '<a href="/test-detail">Mehr anzeigen</a>'
        soup = BeautifulSoup(html, "lxml")
        link = soup.select_one("a")
        assert _parse_product_link(link) is None

    def test_skips_short_titles(self):
        """Skip links with very short titles."""
        html = '<a href="/test-detail">ab</a>'
        soup = BeautifulSoup(html, "lxml")
        link = soup.select_one("a")
        assert _parse_product_link(link) is None


class TestIsProductLink:
    """Tests for _is_product_link helper."""

    def test_detects_detail_link(self):
        """Detect links containing -detail."""
        assert _is_product_link("/waffen/sig-p226-detail") is True

    def test_detects_waffen_category_link(self):
        """Detect links in /waffen/ with numeric ID."""
        assert _is_product_link("/waffen/123/sig") is True

    def test_rejects_non_product_link(self):
        """Reject non-product links."""
        assert _is_product_link("/kategorie/waffen") is False


class TestScrapeWaffenjoray:
    """Tests for scrape_waffenjoray main function."""

    @pytest.mark.asyncio
    async def test_extracts_dl_results(self):
        """Test extraction from dl/dt structure."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_HTML_DL_RESULTS
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.waffenjoray.create_http_client", return_value=mock_client):
            with patch("backend.scrapers.waffenjoray.delay_between_requests", new_callable=AsyncMock):
                with patch("backend.services.crawler.add_crawl_log"):
                    results = await scrape_waffenjoray(search_terms=["sig"])

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_extracts_h3_results(self):
        """Test extraction from h3 structure."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_HTML_H3_RESULTS
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.waffenjoray.create_http_client", return_value=mock_client):
            with patch("backend.scrapers.waffenjoray.delay_between_requests", new_callable=AsyncMock):
                with patch("backend.services.crawler.add_crawl_log"):
                    results = await scrape_waffenjoray(search_terms=["cz"])

        assert len(results) == 2

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

        with patch("backend.scrapers.waffenjoray.create_http_client", return_value=mock_client):
            with patch("backend.services.crawler.add_crawl_log"):
                results = await scrape_waffenjoray(search_terms=["sig"])

        assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_search_terms(self):
        """Test that empty search terms return empty list."""
        results = await scrape_waffenjoray(search_terms=[])
        assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_results(self):
        """Test that no results page returns empty list."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_HTML_NO_RESULTS
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.waffenjoray.create_http_client", return_value=mock_client):
            with patch("backend.scrapers.waffenjoray.delay_between_requests", new_callable=AsyncMock):
                with patch("backend.services.crawler.add_crawl_log"):
                    results = await scrape_waffenjoray(search_terms=["nonexistent"])

        assert results == []
