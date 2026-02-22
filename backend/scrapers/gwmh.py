"""
gwmh-shop.ch Scraper

Scrapes firearms listings from gwmh-shop.ch using their JSONP search API.
This scraper uses a two-step approach:
1. Search via JSONP API to get product links
2. Fetch product detail pages to extract prices
"""
import json
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from backend.scrapers.base import (
    ScraperResult,
    ScraperResults,
    create_http_client,
    delay_between_requests,
    parse_price,
)
from backend.utils.logging import get_logger

logger = get_logger(__name__)

BASE_URL = "https://www.gwmh-shop.ch"
SHOP_BASE_URL = "https://www.gwmh-shop.ch/epages/64344916.sf/de_CH"
# JSONP search API endpoint - returns product suggestions
SEARCH_API_URL = "https://epj.strato.de/rs/product/Store10/517C2170-49A9-4C07-3C8F-C0A829C0B1AA/suggest/jsonp"
SOURCE_NAME = "gwmh-shop.ch"
MAX_PRODUCTS_PER_TERM = 50  # Limit products per search term to avoid too many requests


async def scrape_gwmh(search_terms: Optional[List[str]] = None) -> ScraperResults:
    """
    Scrape listings from gwmh-shop.ch using JSONP search API.

    This scraper uses a two-step approach:
    1. Call JSONP search API to get product names, images, and links
    2. Fetch each product detail page to extract the price

    Args:
        search_terms: Optional list of search terms. If None, fetches from database.

    Returns:
        List of ScraperResult dicts with title, price, image_url, link, source.
        Returns empty list on any error.
    """
    from backend.services.crawler import add_crawl_log
    from urllib.parse import quote, quote_plus

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
    seen_aliases = set()  # Deduplicate products across searches

    try:
        from backend.services.crawler import is_cancel_requested

        async with create_http_client() as client:
            for term in search_terms:
                # Check for cancellation between search terms
                if is_cancel_requested():
                    logger.info(f"{SOURCE_NAME} - Cancelled by user")
                    return results
                add_crawl_log(f"  → Suche: '{term}'")

                # Step 1: Call JSONP search API
                encoded_term = quote_plus(term)
                api_url = f"{SEARCH_API_URL}?lang=de&q={encoded_term}"

                try:
                    response = await client.get(api_url)
                    response.raise_for_status()

                    # Parse JSONP response - format: callback({...})
                    products = _parse_jsonp_response(response.text)

                    if not products:
                        add_crawl_log(f"    Keine Ergebnisse für '{term}'")
                        await delay_between_requests()
                        continue

                    add_crawl_log(f"    {len(products)} Produkte gefunden, lade Details...")

                    # Step 2: Fetch product detail pages to get prices
                    products_fetched = 0
                    for product in products:
                        if products_fetched >= MAX_PRODUCTS_PER_TERM:
                            break

                        alias = product.get("alias", "")
                        if not alias or alias in seen_aliases:
                            continue

                        seen_aliases.add(alias)

                        # Build product detail URL using the correct epages format
                        # URL-encode the alias to handle special characters like # and spaces
                        encoded_alias = quote(alias, safe='')
                        product_url = f"{SHOP_BASE_URL}/?ObjectPath=/Shops/64344916/Products/{encoded_alias}"

                        try:
                            # Fetch product page to get price
                            detail_response = await client.get(product_url)
                            detail_response.raise_for_status()

                            price = _extract_price_from_page(detail_response.text)

                            # Build image URL - images are served from the base URL (not epages path)
                            # Replace _xs (extra small) with _m (medium) for better quality
                            image_path = product.get("image", "")
                            if image_path:
                                # Handle both lowercase and uppercase extensions
                                image_path = image_path.replace("_xs.jpg", "_m.jpg")
                                image_path = image_path.replace("_xs.JPG", "_m.JPG")
                                image_path = image_path.replace("_xs.png", "_m.png")
                                image_path = image_path.replace("_xs.PNG", "_m.PNG")
                            image_url = f"{BASE_URL}{image_path}" if image_path else None

                            result = ScraperResult(
                                title=product.get("name", ""),
                                price=price,
                                image_url=image_url,
                                link=product_url,
                                source=SOURCE_NAME,
                            )
                            results.append(result)
                            products_fetched += 1

                            # Rate limiting between product page fetches
                            await delay_between_requests()

                        except Exception as e:
                            logger.warning(f"{SOURCE_NAME} - Failed to fetch product {alias}: {e}")
                            continue

                except Exception as e:
                    logger.warning(f"{SOURCE_NAME} - Search failed for '{term}': {e}")
                    continue

                # Delay between search terms
                await delay_between_requests()

            logger.info(f"{SOURCE_NAME} - Scraped {len(results)} unique listings total")

    except Exception as e:
        logger.error(f"{SOURCE_NAME} - Failed: {e}")
        return []

    return results


def _parse_jsonp_response(response_text: str) -> List[Dict]:
    """
    Parse JSONP response to extract product data.

    The response format is: callback({"products": [...], "manufacturers": [...], "categories": [...]})

    Args:
        response_text: Raw JSONP response text

    Returns:
        List of product dictionaries with keys: name, image, alias, path
    """
    try:
        # Extract JSON from JSONP callback wrapper
        # Format: callback({...}) or jQuery...(...)
        match = re.search(r'\((\{.*\})\)', response_text, re.DOTALL)
        if not match:
            logger.warning(f"{SOURCE_NAME} - Could not parse JSONP response")
            return []

        json_str = match.group(1)
        data = json.loads(json_str)

        # Extract products array
        products = data.get("products", [])
        return [p for p in products if p.get("type") == "product"]

    except (json.JSONDecodeError, AttributeError) as e:
        logger.warning(f"{SOURCE_NAME} - JSON parse error: {e}")
        return []


def _extract_price_from_page(html: str) -> Optional[float]:
    """
    Extract price from product detail page HTML.

    Looks for Swiss price format: CHF X'XXX.XX

    Args:
        html: Product detail page HTML

    Returns:
        Price as float, or None if not found
    """
    soup = BeautifulSoup(html, "html.parser")

    # Try common price selectors first
    price_selectors = [
        ".price",
        "[class*='price']",
        ".product-price",
        ".Price",
    ]

    for selector in price_selectors:
        elem = soup.select_one(selector)
        if elem:
            price_str = elem.get_text(strip=True)
            price = parse_price(price_str)
            if price is not None:
                return price

    # Fallback: Search for CHF pattern in page text
    # Pattern matches: CHF 1'234.00, CHF 1'234.50, CHF 123.00
    text = soup.get_text()
    matches = re.findall(r"CHF\s*([\d',.]+)", text)

    for match in matches:
        price = parse_price(match)
        if price is not None and price > 0:
            return price

    return None
