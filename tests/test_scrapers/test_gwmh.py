"""
Tests for gwmh-shop.ch scraper.

Tests verify:
- JSONP response parsing
- Two-step fetching (search API + product page)
- Price extraction from product page
- Error handling
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.scrapers.gwmh import (
    SOURCE_NAME,
    scrape_gwmh,
    _parse_jsonp_response,
    _extract_price_from_page,
)


# Sample JSONP response
SAMPLE_JSONP_RESPONSE = 'callback({"products": [{"type": "product", "name": "SIG P226", "image": "/images/sig.jpg", "alias": "sig-p226"}, {"type": "product", "name": "Glock 17", "image": "/images/glock.jpg", "alias": "glock-17"}], "manufacturers": [], "categories": []})'

SAMPLE_JSONP_EMPTY = 'callback({"products": [], "manufacturers": [], "categories": []})'

SAMPLE_PRODUCT_PAGE = """
<html>
<body>
    <div class="product">
        <h1>SIG P226</h1>
        <div class="price">CHF 1'200.00</div>
    </div>
</body>
</html>
"""

SAMPLE_PRODUCT_PAGE_NO_PRICE = """
<html>
<body>
    <div class="product">
        <h1>SIG P226</h1>
    </div>
</body>
</html>
"""


class TestParseJsonpResponse:
    """Tests for _parse_jsonp_response helper."""

    def test_parses_valid_jsonp(self):
        """Test parsing valid JSONP response."""
        products = _parse_jsonp_response(SAMPLE_JSONP_RESPONSE)
        assert len(products) == 2
        assert products[0]["name"] == "SIG P226"
        assert products[1]["name"] == "Glock 17"

    def test_returns_empty_for_empty_products(self):
        """Test parsing JSONP with empty products."""
        products = _parse_jsonp_response(SAMPLE_JSONP_EMPTY)
        assert products == []

    def test_returns_empty_for_invalid_jsonp(self):
        """Test parsing invalid JSONP."""
        products = _parse_jsonp_response("not valid jsonp")
        assert products == []

    def test_filters_non_product_types(self):
        """Test that non-product types are filtered out."""
        jsonp = 'callback({"products": [{"type": "product", "name": "Gun"}, {"type": "category", "name": "Waffen"}]})'
        products = _parse_jsonp_response(jsonp)
        assert len(products) == 1
        assert products[0]["name"] == "Gun"


class TestExtractPriceFromPage:
    """Tests for _extract_price_from_page helper."""

    def test_extracts_price_from_price_class(self):
        """Test extracting price from .price element."""
        price = _extract_price_from_page(SAMPLE_PRODUCT_PAGE)
        assert price == 1200.0

    def test_returns_none_for_no_price(self):
        """Test returning None when no price found."""
        price = _extract_price_from_page(SAMPLE_PRODUCT_PAGE_NO_PRICE)
        assert price is None

    def test_extracts_price_from_chf_pattern(self):
        """Test extracting price from CHF pattern in text."""
        html = "<html><body>Preis: CHF 850.50</body></html>"
        price = _extract_price_from_page(html)
        assert price == 850.5


class TestScrapeGwmh:
    """Tests for scrape_gwmh main function."""

    @pytest.mark.asyncio
    async def test_fetches_search_and_product_pages(self):
        """Test two-step fetching process."""
        # First response is JSONP search
        search_response = MagicMock()
        search_response.text = SAMPLE_JSONP_RESPONSE
        search_response.raise_for_status = MagicMock()

        # Second+ responses are product pages
        product_response = MagicMock()
        product_response.text = SAMPLE_PRODUCT_PAGE
        product_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[search_response, product_response, product_response])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.gwmh.create_http_client", return_value=mock_client):
            with patch("backend.scrapers.gwmh.delay_between_requests", new_callable=AsyncMock):
                with patch("backend.services.crawler.add_crawl_log"):
                    results = await scrape_gwmh(search_terms=["sig"])

        assert len(results) == 2
        assert results[0]["title"] == "SIG P226"
        assert results[0]["price"] == 1200.0
        assert results[0]["source"] == SOURCE_NAME

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

        with patch("backend.scrapers.gwmh.create_http_client", return_value=mock_client):
            with patch("backend.services.crawler.add_crawl_log"):
                results = await scrape_gwmh(search_terms=["sig"])

        assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_search_terms(self):
        """Test that empty search terms return empty list."""
        results = await scrape_gwmh(search_terms=[])
        assert results == []

    @pytest.mark.asyncio
    async def test_deduplicates_by_alias(self):
        """Test that products with same alias are not duplicated."""
        search_response = MagicMock()
        search_response.text = SAMPLE_JSONP_RESPONSE
        search_response.raise_for_status = MagicMock()

        product_response = MagicMock()
        product_response.text = SAMPLE_PRODUCT_PAGE
        product_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        # Return same products for both search terms
        mock_client.get = AsyncMock(side_effect=[
            search_response, product_response, product_response,  # First term
            search_response  # Second term - products already seen
        ])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.gwmh.create_http_client", return_value=mock_client):
            with patch("backend.scrapers.gwmh.delay_between_requests", new_callable=AsyncMock):
                with patch("backend.services.crawler.add_crawl_log"):
                    results = await scrape_gwmh(search_terms=["sig", "glock"])

        # Should only have 2 unique products
        assert len(results) == 2
