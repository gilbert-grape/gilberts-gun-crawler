"""
Tests for aats-group.ch scraper.

Tests verify:
- Sitemap parsing
- Product URL matching against search terms
- Title extraction from slug
- Error handling
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.scrapers.aats import (
    SOURCE_NAME,
    scrape_aats,
)


# Sample sitemap XML
SAMPLE_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://aats-group.ch/shop/item/sig-sauer-p226-9mm</loc></url>
    <url><loc>https://aats-group.ch/shop/item/glock-17-gen5</loc></url>
    <url><loc>https://aats-group.ch/shop/item/cz-75-sp01</loc></url>
    <url><loc>https://aats-group.ch/shop/item/hk-p30-sk</loc></url>
</urlset>
"""

SAMPLE_SITEMAP_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
</urlset>
"""


class TestScrapeAats:
    """Tests for scrape_aats main function."""

    @pytest.mark.asyncio
    async def test_finds_matching_products(self):
        """Test that scraper finds products matching search terms."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_SITEMAP
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.aats.create_http_client", return_value=mock_client):
            with patch("backend.services.crawler.add_crawl_log"):
                results = await scrape_aats(search_terms=["sig", "glock"])

        assert len(results) == 2
        titles = [r["title"].lower() for r in results]
        assert any("sig" in t for t in titles)
        assert any("glock" in t for t in titles)

    @pytest.mark.asyncio
    async def test_deduplicates_results(self):
        """Test that same product is not added multiple times for different terms."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_SITEMAP
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.aats.create_http_client", return_value=mock_client):
            with patch("backend.services.crawler.add_crawl_log"):
                # Both terms match the same product
                results = await scrape_aats(search_terms=["sig", "p226"])

        # Should only have 1 result, not 2
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_matches(self):
        """Test that scraper returns empty list when no products match."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_SITEMAP
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.aats.create_http_client", return_value=mock_client):
            with patch("backend.services.crawler.add_crawl_log"):
                results = await scrape_aats(search_terms=["nonexistent"])

        assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_http_error(self):
        """Test that HTTP errors return empty list."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500)
        ))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.aats.create_http_client", return_value=mock_client):
            with patch("backend.services.crawler.add_crawl_log"):
                results = await scrape_aats(search_terms=["sig"])

        assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_empty_search_terms(self):
        """Test that empty search terms return empty list."""
        results = await scrape_aats(search_terms=[])
        assert results == []

    @pytest.mark.asyncio
    async def test_extracts_correct_fields(self):
        """Test that result has correct fields."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_SITEMAP
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.scrapers.aats.create_http_client", return_value=mock_client):
            with patch("backend.services.crawler.add_crawl_log"):
                results = await scrape_aats(search_terms=["sig"])

        assert len(results) == 1
        result = results[0]
        assert result["source"] == SOURCE_NAME
        assert "sig" in result["link"].lower()
        assert result["price"] is None  # No price from sitemap
        assert result["image_url"] is None  # No image from sitemap
