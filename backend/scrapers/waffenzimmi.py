"""
waffenzimmi.ch Scraper

Scrapes used firearms listings from waffenzimmi.ch (WooCommerce site)
"""
import re
from typing import List, Optional

from bs4 import BeautifulSoup, Tag

from backend.scrapers.base import (
    ScraperResult,
    ScraperResults,
    create_http_client,
    delay_between_requests,
    make_absolute_url,
    parse_price,
)
from backend.utils.logging import get_logger

logger = get_logger(__name__)

BASE_URL = "https://www.waffenzimmi.ch"
# Site uses search-based scraping - search for each term directly
# Search URL pattern: /?s={term}, pagination: /page/{N}/?s={term}
SOURCE_NAME = "waffenzimmi.ch"
MAX_PAGES = 10  # Max pages per search term


async def scrape_waffenzimmi(search_terms: Optional[List[str]] = None) -> ScraperResults:
    """
    Scrape listings from waffenzimmi.ch using search.

    This scraper uses the site's search functionality to find relevant listings.
    If no search_terms are provided, it will fetch them from the database.

    Args:
        search_terms: Optional list of search terms. If None, fetches from database.

    Returns:
        List of ScraperResult dicts with title, price, image_url, link, source.
        Returns empty list on any error.
    """
    # Import here to avoid circular dependency
    from backend.services.crawler import add_crawl_log
    from urllib.parse import quote_plus

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
    seen_links = set()  # Deduplicate results across searches

    try:
        from backend.services.crawler import is_cancel_requested

        async with create_http_client() as client:
            for term in search_terms:
                # Check for cancellation between search terms
                if is_cancel_requested():
                    logger.info(f"{SOURCE_NAME} - Cancelled by user")
                    return results

                add_crawl_log(f"  → Suche: '{term}'")

                page = 1
                while page <= MAX_PAGES:
                    # Check for cancellation between pages
                    if is_cancel_requested():
                        logger.info(f"{SOURCE_NAME} - Cancelled by user")
                        return results
                    # Construct search URL - WooCommerce search pagination
                    encoded_term = quote_plus(term)
                    if page == 1:
                        url = f"{BASE_URL}/?s={encoded_term}"
                    else:
                        url = f"{BASE_URL}/page/{page}/?s={encoded_term}"
                    add_crawl_log(f"    Seite {page}...")

                    response = await client.get(url)
                    response.raise_for_status()

                    soup = BeautifulSoup(response.text, "html.parser")

                    # Find all listing items - XStore theme uses various selectors
                    listings = soup.select(
                        ".content-product, "
                        ".product-grid-item, "
                        "li.product, "
                        "[class*='type-product'], "
                        ".et_product-block"
                    )

                    # Fallback: look for links that match product detail pages
                    if not listings:
                        product_links = soup.select("a[href*='/produkt/']")
                        if product_links:
                            listings = [_find_listing_container(elem) for elem in product_links]
                            listings = [item for item in listings if item is not None]
                            # Deduplicate by element id
                            seen_ids = set()
                            unique_listings = []
                            for listing in listings:
                                listing_id = id(listing)
                                if listing_id not in seen_ids:
                                    seen_ids.add(listing_id)
                                    unique_listings.append(listing)
                            listings = unique_listings

                    if not listings:
                        if page == 1:
                            add_crawl_log(f"    Keine Ergebnisse für '{term}'")
                        break

                    page_results = 0
                    for listing in listings:
                        try:
                            result = _parse_listing(listing)
                            if result and result["link"] not in seen_links:
                                seen_links.add(result["link"])
                                results.append(result)
                                page_results += 1
                        except Exception as e:
                            logger.warning(f"{SOURCE_NAME} - Failed to parse listing: {e}")
                            continue

                    logger.debug(f"{SOURCE_NAME} - Search '{term}' page {page}: found {page_results} new listings")

                    # Check if there's a next page
                    if not _has_next_page(soup, page) or page_results == 0:
                        break

                    page += 1
                    if page <= MAX_PAGES:
                        await delay_between_requests()

                # Delay between search terms
                await delay_between_requests()

            logger.info(f"{SOURCE_NAME} - Scraped {len(results)} unique listings total")

    except Exception as e:
        logger.error(f"{SOURCE_NAME} - Failed: {e}")
        return []

    return results


def _find_listing_container(element: Tag) -> Optional[Tag]:
    """Find the parent container of a product link."""
    parent = element.parent
    for _ in range(5):  # Don't go too far up
        if parent is None:
            break
        if parent.name in ("article", "div", "li") and parent.get("class"):
            return parent
        parent = parent.parent
    return element.parent if element.parent else None


def _has_next_page(soup: BeautifulSoup, current_page: int) -> bool:
    """Check if there's a next page link in pagination."""
    # WooCommerce pagination patterns - check for next link in various structures
    next_link = soup.select_one(
        "a.next, "
        "a.page-numbers.next, "
        "li.next a, "  # li with class next containing a link
        "a[rel='next'], "
        ".woocommerce-pagination a:-soup-contains('→'), "
        ".woocommerce-pagination a:-soup-contains('Weiter'), "
        ".pagination a:-soup-contains('Weiter')"
    )
    if next_link:
        return True

    # Check for page number links with /page/ pattern that are higher than current page
    pagination_links = soup.select("a[href*='/page/']")
    for link in pagination_links:
        href = link.get("href", "")
        # Extract page number from URL like /page/2/
        match = re.search(r"/page/(\d+)/?", str(href))
        if match:
            page_num = int(match.group(1))
            if page_num > current_page:
                return True

    return False


def _parse_listing(listing: Tag) -> Optional[ScraperResult]:
    """Parse a single listing element into ScraperResult."""
    title = _extract_title(listing)
    if not title:
        return None

    link = _extract_link(listing)
    if not link:
        return None

    price = _extract_price(listing)
    image_url = _extract_image_url(listing)

    return ScraperResult(
        title=title,
        price=price,
        image_url=image_url,
        link=link,
        source=SOURCE_NAME
    )


def _extract_title(listing: Tag) -> Optional[str]:
    """Extract title from listing element."""
    # XStore/WooCommerce title selectors
    title_selectors = [
        ".product-title a",
        ".product-title",
        ".woocommerce-loop-product__title",
        "h2.product-title",
        "h3.product-title",
        ".product-name a",
        ".product-name",
        "h2 a",
        "h3 a",
        "h2",
        "h3",
        "a[href*='/produkt/']",
    ]

    for selector in title_selectors:
        elem = listing.select_one(selector)
        if elem:
            # Try title attribute first (often cleaner)
            title = elem.get("title", "")
            if not title:
                title = elem.get_text(strip=True)
            if title and len(title) > 2:
                return title

    return None


def _extract_link(listing: Tag) -> Optional[str]:
    """Extract link from listing element."""
    # WooCommerce link selectors
    link_selectors = [
        "a.woocommerce-LoopProduct-link",
        "a[href*='/produkt/']",
        ".product-name a",
        "h2 a",
        "h3 a",
        "a",
    ]

    for selector in link_selectors:
        link_elem = listing.select_one(selector)
        if link_elem and link_elem.get("href"):
            href = link_elem["href"]
            if isinstance(href, list):
                href = href[0]
            # Verify it looks like a product URL
            if "/produkt/" in href or href.startswith("http"):
                return make_absolute_url(BASE_URL, href)

    # If listing itself is a link
    if listing.name == "a" and listing.get("href"):
        href = listing["href"]
        if isinstance(href, list):
            href = href[0]
        return make_absolute_url(BASE_URL, href)

    return None


def _extract_price(listing: Tag) -> Optional[float]:
    """Extract price from listing element."""
    # WooCommerce price selectors - check sale price first
    price_selectors = [
        ".price ins .woocommerce-Price-amount",  # Sale price (priority)
        ".price > .woocommerce-Price-amount",  # Direct child only (not inside del)
        ".price",
        "[class*='price']",
    ]

    for selector in price_selectors:
        elem = listing.select_one(selector)
        if elem:
            price_str = elem.get_text(strip=True)
            price = parse_price(price_str)
            if price is not None:
                return price

    # Try to find price in text that contains CHF
    text = listing.get_text()
    if "CHF" in text or "Fr." in text:
        # Swiss format: "CHF 1'234.00" or "1'234.00 CHF"
        match = re.search(r"(?:CHF|Fr\.?)\s*([\d'.,]+)|(\d[\d'.,]*)\s*(?:CHF|Fr\.?)", text)
        if match:
            price_str = match.group(1) or match.group(2)
            return parse_price(price_str)

    return None


def _extract_image_url(listing: Tag) -> Optional[str]:
    """Extract image URL from listing element."""
    # XStore/WooCommerce image selectors
    img_selectors = [
        ".product-content-image img",
        ".product-image-wrapper img",
        "img.wp-post-image",
        "img.attachment-woocommerce_thumbnail",
        ".product-image img",
        "img",
    ]

    for selector in img_selectors:
        img_elem = listing.select_one(selector)
        if img_elem:
            # Try different image source attributes (including lazy-load)
            # XStore often uses data-src for lazy loading
            for attr in ["data-src", "src", "data-lazy-src", "data-original"]:
                img_url = img_elem.get(attr)
                if img_url:
                    if isinstance(img_url, list):
                        img_url = img_url[0]
                    # Skip placeholder images
                    if ("placeholder" not in img_url.lower() and
                        "blank" not in img_url.lower() and
                        "xstore-placeholder" not in img_url.lower() and
                        "data:image" not in img_url.lower()):
                        return make_absolute_url(BASE_URL, img_url)

    return None
