"""
Tests for armashop.ch scraper.

Tests verify:
- WooCommerce API response parsing
- Price extraction (centimes to CHF conversion)
- Image URL extraction
- Deduplication by SKU
- Error handling
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.scrapers.armashop import (
    SOURCE_NAME,
    scrape_armashop,
)


# Sample API response
SAMPLE_API_RESPONSE = [
    {
        "id": 1,
        "sku": "SIG-P226",
        "name": "SIG Sauer P226",
        "permalink": "https://armashop.ch/produkt/sig-p226",
        "prices": {"price": "120000"},  # 1200.00 CHF in centimes
        "images": [{"src": "https://armashop.ch/images/sig-p226.jpg"}]
    },
    {
        "id": 2,
        "sku": "GLOCK-17",
        "name": "Glock 17 Gen5",
        "permalink": "https://armashop.ch/produkt/glock-17",
        "prices": {"price": "85000"},  # 850.00 CHF
        "images": [{"src": "https://armashop.ch/images/glock-17.jpg"}]
    }
]

SAMPLE_API_RESPONSE_WITH_HTML = [
    {
        "id": 3,
        "sku": "ITEM-HTML",
        "name": "Test &#215; Product",  # HTML entity
        "permalink": "https://armashop.ch/produkt/test",
        "prices": {"price": "50000"},
        "images": []
    }
]


class TestScrapeArmashop:
    """Tests for scrape_armashop main function."""

    @pytest.mark.asyncio
    async def test_extracts_products_from_api(self):
        """Test that scraper extracts products from API response."""
        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value=SAMPLE_API_RESPONSE)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.armashop.create_http_client", return_value=mock_client):
            with patch("backend.scrapers.armashop.delay_between_requests", new_callable=AsyncMock):
                with patch("backend.services.crawler.add_crawl_log"):
                    results = await scrape_armashop(search_terms=["sig"])

        assert len(results) == 2
        assert results[0]["title"] == "SIG Sauer P226"
        assert results[0]["price"] == 1200.0
        assert results[0]["source"] == SOURCE_NAME

    @pytest.mark.asyncio
    async def test_converts_price_from_centimes(self):
        """Test that price is correctly converted from centimes."""
        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value=SAMPLE_API_RESPONSE)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.armashop.create_http_client", return_value=mock_client):
            with patch("backend.scrapers.armashop.delay_between_requests", new_callable=AsyncMock):
                with patch("backend.services.crawler.add_crawl_log"):
                    results = await scrape_armashop(search_terms=["glock"])

        glock = next(r for r in results if "Glock" in r["title"])
        assert glock["price"] == 850.0

    @pytest.mark.asyncio
    async def test_decodes_html_entities(self):
        """Test that HTML entities in product names are decoded."""
        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value=SAMPLE_API_RESPONSE_WITH_HTML)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.armashop.create_http_client", return_value=mock_client):
            with patch("backend.scrapers.armashop.delay_between_requests", new_callable=AsyncMock):
                with patch("backend.services.crawler.add_crawl_log"):
                    results = await scrape_armashop(search_terms=["test"])

        assert len(results) == 1
        assert "×" in results[0]["title"]  # Decoded HTML entity

    @pytest.mark.asyncio
    async def test_deduplicates_by_sku(self):
        """Test that products with same SKU are not duplicated."""
        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value=SAMPLE_API_RESPONSE)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.armashop.create_http_client", return_value=mock_client):
            with patch("backend.scrapers.armashop.delay_between_requests", new_callable=AsyncMock):
                with patch("backend.services.crawler.add_crawl_log"):
                    # Search with two terms that return same products
                    results = await scrape_armashop(search_terms=["sig", "glock"])

        # Should only have 2 results, not 4
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

        with patch("backend.scrapers.armashop.create_http_client", return_value=mock_client):
            with patch("backend.services.crawler.add_crawl_log"):
                results = await scrape_armashop(search_terms=["sig"])

        assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_search_terms(self):
        """Test that empty search terms return empty list."""
        results = await scrape_armashop(search_terms=[])
        assert results == []

    @pytest.mark.asyncio
    async def test_handles_empty_api_response(self):
        """Test handling of empty API response."""
        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value=[])
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.armashop.create_http_client", return_value=mock_client):
            with patch("backend.scrapers.armashop.delay_between_requests", new_callable=AsyncMock):
                with patch("backend.services.crawler.add_crawl_log"):
                    results = await scrape_armashop(search_terms=["nonexistent"])

        assert results == []
