"""
swissarsenal.com Scraper

Scrapes firearms listings from swissarsenal.com (PrestaShop-based shop).
Two-phase approach:
1) Always browses the "Occasions" category (used firearms).
2) Uses search for terms >= 3 characters.
Short terms (< 3 chars, e.g. "CZ") are covered by the Occasions crawl,
since PrestaShop requires a minimum of 3 characters for search.
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

BASE_URL = "https://www.swissarsenal.com"
SEARCH_URL = f"{BASE_URL}/recherche"
SOURCE_NAME = "swissarsenal.com"
MAX_PAGES = 5  # 40 items per page, 5 pages = 200 items max per term
MIN_SEARCH_LENGTH = 3  # PrestaShop minimum search length

# Occasions category - always crawled (used firearms)
OCCASIONS_URL = f"{BASE_URL}/32-occasions"
MAX_CATEGORY_PAGES = 10


async def scrape_swissarsenal(search_terms: Optional[List[str]] = None) -> ScraperResults:
    """
    Scrape listings from swissarsenal.com.

    Two-phase approach:
    1) Always browses the "Occasions" (used firearms) category pages.
    2) Uses search for terms with >= 3 characters.
    Short terms (< 3 chars) are covered by the Occasions crawl,
    since PrestaShop rejects searches under 3 characters.

    Args:
        search_terms: Optional list of search terms. If None, fetches from database.

    Returns:
        List of ScraperResult dicts with title, price, image_url, link, source.
        Returns empty list on any error.
    """
    from backend.services.crawler import add_crawl_log
    from urllib.parse import quote_plus

    if search_terms is None:
        from backend.database import SessionLocal
        from backend.database.crud import get_active_search_terms
        with SessionLocal() as session:
            db_terms = get_active_search_terms(session)
            search_terms = [t.term for t in db_terms]

    if not search_terms:
        logger.warning(f"{SOURCE_NAME} - No search terms to search for")
        return []

    # Only terms >= 3 chars can use PrestaShop search
    searchable_terms = [t for t in search_terms if len(t) >= MIN_SEARCH_LENGTH]

    results: ScraperResults = []
    seen_links = set()

    try:
        from backend.services.crawler import is_cancel_requested

        async with create_http_client() as client:
            # 1) Always browse Occasions category (used firearms)
            add_crawl_log(f"  → Durchsuche Occasions-Kategorie...")
            page = 1
            while page <= MAX_CATEGORY_PAGES:
                if is_cancel_requested():
                    logger.info(f"{SOURCE_NAME} - Cancelled by user")
                    return results

                url = OCCASIONS_URL if page == 1 else f"{OCCASIONS_URL}?page={page}"
                add_crawl_log(f"    Occasions Seite {page}...")

                response = await client.get(url)
                response.raise_for_status()

                soup = BeautifulSoup(response.text, "html.parser")
                page_results = _collect_listings(soup, results, seen_links)

                if page_results == 0:
                    break

                logger.debug(f"{SOURCE_NAME} - Occasions page {page}: found {page_results} new listings")

                if not _has_next_page(soup, page):
                    break

                page += 1
                if page <= MAX_CATEGORY_PAGES:
                    await delay_between_requests()

            add_crawl_log(f"    Occasions: {len(results)} Inserate")
            await delay_between_requests()

            # 2) Search-based scraping for terms >= 3 characters
            for term in searchable_terms:
                if is_cancel_requested():
                    logger.info(f"{SOURCE_NAME} - Cancelled by user")
                    return results

                add_crawl_log(f"  → Suche: '{term}'")

                page = 1
                while page <= MAX_PAGES:
                    if is_cancel_requested():
                        logger.info(f"{SOURCE_NAME} - Cancelled by user")
                        return results

                    encoded_term = quote_plus(term)
                    url = f"{SEARCH_URL}?controller=search&s={encoded_term}"
                    if page > 1:
                        url += f"&page={page}"
                    add_crawl_log(f"    Seite {page}...")

                    response = await client.get(url)
                    response.raise_for_status()

                    soup = BeautifulSoup(response.text, "html.parser")

                    page_results = _collect_listings(soup, results, seen_links)

                    if page_results == 0:
                        if page == 1:
                            add_crawl_log(f"    Keine Ergebnisse für '{term}'")
                        break

                    logger.debug(f"{SOURCE_NAME} - Search '{term}' page {page}: found {page_results} new listings")

                    if not _has_next_page(soup, page):
                        break

                    page += 1
                    if page <= MAX_PAGES:
                        await delay_between_requests()

                await delay_between_requests()

            logger.info(f"{SOURCE_NAME} - Scraped {len(results)} unique listings total")

    except Exception as e:
        logger.error(f"{SOURCE_NAME} - Failed: {e}")
        return []

    return results


def _collect_listings(soup: BeautifulSoup, results: ScraperResults, seen_links: set) -> int:
    """Parse all listings from a page and add new ones to results.

    Returns the number of new listings added.
    """
    listings = soup.select("article.product-miniature, .product-miniature, li.product-miniature")
    if not listings:
        listings = soup.select("li:has(a[href$='.html'])")

    if not listings:
        return 0

    count = 0
    for listing in listings:
        try:
            result = _parse_listing(listing)
            if result and result["link"] not in seen_links:
                seen_links.add(result["link"])
                results.append(result)
                count += 1
        except Exception as e:
            logger.warning(f"{SOURCE_NAME} - Failed to parse listing: {e}")
            continue

    return count


def _has_next_page(soup: BeautifulSoup, current_page: int) -> bool:
    """Check if there's a next page link in pagination."""
    # PrestaShop uses "Suivant" (Next) link
    next_link = soup.select_one(
        "a.next, a[rel='next'], "
        "a:-soup-contains('Suivant'), a:-soup-contains('Next'), a:-soup-contains('»')"
    )
    if next_link:
        return True

    # Check for page number links with higher page numbers
    pagination = soup.select("a[href*='page=']")
    for link in pagination:
        href = link.get("href", "")
        match = re.search(r"page=(\d+)", str(href))
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
        source=SOURCE_NAME,
    )


def _extract_title(listing: Tag) -> Optional[str]:
    """Extract title from listing element."""
    title_selectors = [
        ".product-title a",
        ".product-title",
        "h3 a",
        "h3",
        "h2 a",
        "h2",
        "a[href$='.html']",
    ]

    for selector in title_selectors:
        elem = listing.select_one(selector)
        if elem:
            title = elem.get_text(strip=True)
            if title and len(title) > 3:
                return title

    return None


def _extract_link(listing: Tag) -> Optional[str]:
    """Extract link from listing element."""
    link_selectors = [
        "a.product-thumbnail",
        ".product-title a",
        "h3 a",
        "a[href$='.html']",
    ]

    for selector in link_selectors:
        link_elem = listing.select_one(selector)
        if link_elem and link_elem.get("href"):
            href = link_elem["href"]
            if isinstance(href, list):
                href = href[0]
            if ".html" in href or "/swissarsenal" in href:
                return make_absolute_url(BASE_URL, href)

    # Fallback: any link that looks like a product URL
    for a_tag in listing.select("a[href]"):
        href = a_tag.get("href", "")
        if isinstance(href, list):
            href = href[0]
        if href.endswith(".html") and "recherche" not in href:
            return make_absolute_url(BASE_URL, href)

    return None


def _extract_price(listing: Tag) -> Optional[float]:
    """Extract price from listing element."""
    price_selectors = [
        ".product-price-and-shipping .price",
        ".price",
        "span[itemprop='price']",
        "[class*='price']",
    ]

    for selector in price_selectors:
        elem = listing.select_one(selector)
        if elem:
            content = elem.get("content")
            if content:
                try:
                    return float(content)
                except ValueError:
                    pass
            text = elem.get_text(strip=True)
            if text:
                price = parse_price(text)
                if price is not None:
                    return price

    # Fallback: search text for CHF price pattern
    full_text = listing.get_text()
    match = re.search(r"([\d',.]+)\s*CHF|CHF\s*([\d',.]+)", full_text)
    if match:
        price_str = match.group(1) or match.group(2)
        return parse_price(price_str)

    return None


def _extract_image_url(listing: Tag) -> Optional[str]:
    """Extract image URL from listing element."""
    img_elem = listing.select_one(
        ".thumbnail-container img, .product-thumbnail img, img"
    )

    if img_elem:
        for attr in ["src", "data-src", "data-full-size-image-url", "data-lazy-src"]:
            img_url = img_elem.get(attr)
            if img_url:
                if isinstance(img_url, list):
                    img_url = img_url[0]
                if "placeholder" not in img_url.lower() and "blank" not in img_url.lower():
                    return make_absolute_url(BASE_URL, img_url)

    return None
