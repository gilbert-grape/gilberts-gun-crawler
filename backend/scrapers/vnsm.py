"""
vnsm.ch Scraper

Scrapes firearms listings from vnsm.ch (PrestaShop-based).
Two-phase approach:
1) Always browses weapon category pages (Kurzwaffen, Langwaffen, Vollautomatische).
2) Uses search for terms >= 3 characters.
Short terms (< 3 chars, e.g. "CZ") are covered by the category crawl,
since PrestaShop requires a minimum of 3 characters for search.
"""
import re
from typing import List, Optional
from urllib.parse import quote_plus

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

BASE_URL = "https://www.vnsm.ch"
SEARCH_URL = f"{BASE_URL}/recherche"
SOURCE_NAME = "vnsm.ch"
MAX_PAGES = 5  # Max pages per search term
MIN_SEARCH_LENGTH = 3  # PrestaShop minimum search length
MAX_CATEGORY_PAGES = 10

# Weapon category pages - always crawled
CATEGORY_URLS = [
    f"{BASE_URL}/8-armes-de-poing",
    f"{BASE_URL}/7-armes-longues",
    f"{BASE_URL}/16-armes-automatiques",
]


async def scrape_vnsm(search_terms: Optional[List[str]] = None) -> ScraperResults:
    """
    Scrape listings from vnsm.ch.

    Two-phase approach:
    1) Always browses weapon category pages (armes de poing, armes longues, automatiques).
    2) Uses search for terms with >= 3 characters.
    Short terms (< 3 chars) are covered by the category crawl,
    since PrestaShop rejects searches under 3 characters.

    Args:
        search_terms: Optional list of search terms. If None, fetches from database.

    Returns:
        List of ScraperResult dicts with title, price, image_url, link, source.
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

    # Only terms >= 3 chars can use PrestaShop search
    searchable_terms = [t for t in search_terms if len(t) >= MIN_SEARCH_LENGTH]

    results: ScraperResults = []
    seen_links = set()  # Deduplicate results across searches

    try:
        from backend.services.crawler import is_cancel_requested

        async with create_http_client() as client:
            # 1) Always browse weapon category pages
            add_crawl_log(f"  → Durchsuche Waffen-Kategorien...")
            for cat_url in CATEGORY_URLS:
                if is_cancel_requested():
                    logger.info(f"{SOURCE_NAME} - Cancelled by user")
                    return results

                cat_name = cat_url.split("/")[-1]
                add_crawl_log(f"    Kategorie: {cat_name}")

                page = 1
                while page <= MAX_CATEGORY_PAGES:
                    if is_cancel_requested():
                        logger.info(f"{SOURCE_NAME} - Cancelled by user")
                        return results

                    url = cat_url if page == 1 else f"{cat_url}?page={page}"

                    response = await client.get(url)
                    response.raise_for_status()

                    soup = BeautifulSoup(response.text, "html.parser")
                    listings = soup.select("article.product-miniature")

                    if not listings:
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

                    logger.debug(f"{SOURCE_NAME} - Category '{cat_name}' page {page}: found {page_results} new listings")

                    if page_results == 0 or not _has_next_page(soup, page):
                        break

                    page += 1
                    if page <= MAX_CATEGORY_PAGES:
                        await delay_between_requests()

                await delay_between_requests()

            add_crawl_log(f"    Kategorien: {len(results)} Inserate")

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
                    url = f"{SEARCH_URL}?s={encoded_term}"
                    if page > 1:
                        url += f"&page={page}"
                    add_crawl_log(f"    Seite {page}...")

                    response = await client.get(url)
                    response.raise_for_status()

                    soup = BeautifulSoup(response.text, "html.parser")
                    listings = soup.select("article.product-miniature")

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

                    if not _has_next_page(soup, page) or page_results == 0:
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


def _has_next_page(soup: BeautifulSoup, current_page: int) -> bool:
    """Check if there's a next page link in pagination."""
    # PrestaShop pagination - look for "Suivant" (Next) link or page numbers
    next_link = soup.select_one("a.next, a[rel='next'], .pagination a:-soup-contains('Suivant'), .pagination a:-soup-contains('»')")
    if next_link:
        return True

    # Check for page number links with higher page numbers
    pagination = soup.select(".pagination a[href*='page='], ul.page-list a[href*='page=']")
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
    # Extract title
    title = _extract_title(listing)
    if not title:
        return None

    # Extract link
    link = _extract_link(listing)
    if not link:
        return None

    # Extract price
    price = _extract_price(listing)

    # Extract image URL
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
    # PrestaShop product title selectors
    title_selectors = [
        ".product-title a",
        "h2.product-title a",
        "h3.product-title a",
        ".product-name a",
        "h2 a",
        "h3 a",
        ".title a",
        "a.product-name",
    ]

    for selector in title_selectors:
        elem = listing.select_one(selector)
        if elem:
            title = elem.get_text(strip=True)
            if title:
                return title

    return None


def _extract_link(listing: Tag) -> Optional[str]:
    """Extract link from listing element."""
    # Try PrestaShop product link selectors
    link_selectors = [
        ".product-title a",
        "h2.product-title a",
        "h3.product-title a",
        ".product-name a",
        "a.product-name",
        ".thumbnail a",
        "a.product-thumbnail",
        "a[href*='controller=product']",
        "a",
    ]

    for selector in link_selectors:
        link_elem = listing.select_one(selector)
        if link_elem and link_elem.get("href"):
            href = link_elem["href"]
            if isinstance(href, list):
                href = href[0]
            # Only accept product links, not category or other links
            if href and not href.startswith("#"):
                return make_absolute_url(BASE_URL, href)

    return None


def _extract_price(listing: Tag) -> Optional[float]:
    """Extract price from listing element."""
    # PrestaShop price selectors
    price_selectors = [
        ".product-price-and-shipping .price",
        ".price",
        ".product-price",
        "[itemprop='price']",
        ".current-price",
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
        # Look for patterns like "CHF 1'234" or "1234 CHF" or "1 550,00 CHF"
        match = re.search(r"(?:CHF|Fr\.?)\s*([\d\s',.]+)|(\d[\d\s',.]*)\s*(?:CHF|Fr\.?)", text)
        if match:
            price_str = match.group(1) or match.group(2)
            return parse_price(price_str)

    return None


def _extract_image_url(listing: Tag) -> Optional[str]:
    """Extract image URL from listing element."""
    # PrestaShop image selectors
    img_selectors = [
        ".product-thumbnail img",
        ".thumbnail img",
        ".product-cover img",
        ".product-image img",
        "img.product-image",
        "img",
    ]

    for selector in img_selectors:
        img_elem = listing.select_one(selector)
        if img_elem:
            # Try different image source attributes (lazy loading support)
            for attr in ["src", "data-src", "data-lazy-src", "data-full-size-image-url"]:
                img_url = img_elem.get(attr)
                if img_url:
                    if isinstance(img_url, list):
                        img_url = img_url[0]
                    # Skip placeholder images
                    if "placeholder" not in img_url.lower() and "blank" not in img_url.lower():
                        return make_absolute_url(BASE_URL, img_url)

    return None
