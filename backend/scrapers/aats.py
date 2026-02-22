"""
aats-group.ch Scraper

Scrapes firearms listings from aats-group.ch using their sitemap.
Since the website is a JavaScript SPA with Algolia search (credentials not public),
we use the sitemap to discover products and match against search terms.

The sitemap contains product URLs with descriptive slugs that we can match against.
"""
import re
from typing import List, Optional
from urllib.parse import unquote

from backend.scrapers.base import (
    ScraperResult,
    ScraperResults,
    create_http_client,
)
from backend.utils.logging import get_logger

logger = get_logger(__name__)

BASE_URL = "https://aats-group.ch"
SITEMAP_URL = "https://aats-group.ch/cache/salesChannel/MYSUipyQNZxDfTH9UZ8nx/bucket/salesChannel/item-sitemap.xml"
SOURCE_NAME = "aats-group.ch"


async def scrape_aats(search_terms: Optional[List[str]] = None) -> ScraperResults:
    """
    Scrape listings from aats-group.ch using their sitemap.

    Since the website is a JavaScript SPA, we:
    1. Fetch the sitemap to get all product URLs
    2. Extract product slugs from URLs
    3. Match slugs against search terms
    4. Return matching products with basic info from the URL

    Note: Price and image data are not available without JavaScript rendering.
    Products are identified by their URL slug which contains the product name.

    Args:
        search_terms: Optional list of search terms. If None, fetches from database.

    Returns:
        List of ScraperResult dicts with title, link, source.
        Returns empty list on any error.
    """
    from backend.services.crawler import add_crawl_log

    # If no search terms provided, get them from the database
    if search_terms is None:
        from backend.database import SessionLocal
        from backend.database.crud import get_active_search_terms
        with SessionLocal() as session:
            db_terms = get_active_search_terms(session)
            search_terms = [t.term for t in db_terms]

    if not search_terms:
        logger.warning(f"{SOURCE_NAME} - No search terms to search for")
        return []

    results: ScraperResults = []
    seen_urls = set()

    try:
        from backend.services.crawler import is_cancel_requested

        async with create_http_client() as client:
            add_crawl_log("  Lade Sitemap...")

            # Fetch sitemap
            response = await client.get(SITEMAP_URL)
            response.raise_for_status()

            # Parse product URLs from sitemap
            # Format: <loc>https://aats-group.ch/shop/item/product-slug</loc>
            product_urls = re.findall(r'<loc>(https://aats-group\.ch/shop/item/[^<]+)</loc>', response.text)

            add_crawl_log(f"  {len(product_urls)} Produkte in Sitemap gefunden")

            # Convert search terms to lowercase for matching
            search_patterns = [term.lower() for term in search_terms]

            # Match products against search terms
            for url in product_urls:
                # Check for cancellation between products
                if is_cancel_requested():
                    logger.info(f"{SOURCE_NAME} - Cancelled by user")
                    return results

                # Extract slug from URL
                # URL format: https://aats-group.ch/shop/item/product-name-here
                slug = url.split('/shop/item/')[-1] if '/shop/item/' in url else ''
                if not slug:
                    continue

                # Decode URL-encoded characters and convert to lowercase
                slug_decoded = unquote(slug).lower()

                # Replace hyphens with spaces for better matching
                slug_searchable = slug_decoded.replace('-', ' ')

                # Check if any search term matches the slug
                for term in search_patterns:
                    term_lower = term.lower()
                    # Match if term is found in slug (with hyphens or spaces)
                    if term_lower in slug_searchable or term_lower in slug_decoded:
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)

                        # Create title from slug (convert hyphens to spaces, capitalize)
                        title = slug_decoded.replace('-', ' ').title()

                        # Remove trailing ID/SKU patterns (e.g., "-12345" at end)
                        title = re.sub(r'\s+\d+$', '', title)
                        title = re.sub(r'\s+[a-z0-9]{5,}$', '', title, flags=re.IGNORECASE)

                        result = ScraperResult(
                            title=title,
                            price=None,  # Price not available without JS rendering
                            image_url=None,  # Image not available without JS rendering
                            link=url,
                            source=SOURCE_NAME,
                        )
                        results.append(result)
                        break  # Don't add same product multiple times

            # Log results per search term
            for term in search_terms:
                term_lower = term.lower()
                count = sum(1 for r in results if term_lower in r['title'].lower())
                if count > 0:
                    add_crawl_log(f"    '{term}': {count} Treffer")

            logger.info(f"{SOURCE_NAME} - Found {len(results)} matching products from sitemap")

    except Exception as e:
        logger.error(f"{SOURCE_NAME} - Failed: {e}")
        add_crawl_log(f"  Fehler: {e}")
        return []

    return results
