"""
gebrauchtwaffen.com Scraper

Scrapes firearms listings from gebrauchtwaffen.com, a Swiss marketplace for used firearms.
Site uses a search with `sPattern` parameter, results are div.item elements with
title, price (CHF), image (CloudFront CDN) and link. Pagination via `iPage,N` parameter,
20 results per page.
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

BASE_URL = "https://www.gebrauchtwaffen.com"
SEARCH_URL = f"{BASE_URL}/index.php"
SOURCE_NAME = "gebrauchtwaffen.com"
MAX_PAGES = 5  # Max pages per search term


async def scrape_gebrauchtwaffen(search_terms: Optional[List[str]] = None) -> ScraperResults:
    """
    Scrape listings from gebrauchtwaffen.com using search.

    This scraper uses the site's search functionality to find relevant listings.
    If no search_terms are provided, it will fetch them from the database.

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

                    # Construct search URL
                    encoded_term = quote_plus(term)
                    url = f"{SEARCH_URL}?page=search&sPattern={encoded_term}"
                    if page > 1:
                        url += f"&iPage,{page}"
                    add_crawl_log(f"    Seite {page}...")

                    response = await client.get(url)
                    response.raise_for_status()

                    # Parse HTML
                    soup = BeautifulSoup(response.text, "html.parser")

                    # Find all item containers
                    items = soup.select("div.item")

                    if not items:
                        if page == 1:
                            add_crawl_log(f"    Keine Ergebnisse für '{term}'")
                        break

                    # Process each item
                    page_results = 0
                    for item in items:
                        try:
                            result = _parse_listing(item)
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


def _parse_listing(item: Tag) -> Optional[ScraperResult]:
    """Parse a div.item container into a ScraperResult.

    Expected structure:
        <div class="item">
            <h3><a href="...">Title</a></h3>
            <div class="price">CHF 1'234.00</div>
            <img src="https://...cloudfront.net/...">
        </div>

    Args:
        item: BeautifulSoup Tag for a div.item element.

    Returns:
        ScraperResult dict or None if essential fields are missing.
    """
    # Extract title and link from h3 > a
    title_link = item.select_one("h3 > a")
    if not title_link:
        return None

    title = title_link.get_text(strip=True)
    if not title:
        return None

    href = title_link.get("href", "")
    if not href:
        return None
    link = make_absolute_url(BASE_URL + "/", href)

    # Extract price from div.price
    price = None
    price_div = item.select_one("div.price")
    if price_div:
        price_text = price_div.get_text(strip=True)
        price = parse_price(price_text)

    # Extract image URL
    image_url = None
    img = item.select_one("img")
    if img:
        img_src = img.get("src") or img.get("data-src")
        if img_src:
            if isinstance(img_src, list):
                img_src = img_src[0]
            image_url = make_absolute_url(BASE_URL + "/", img_src)

    return ScraperResult(
        title=title,
        price=price,
        image_url=image_url,
        link=link,
        source=SOURCE_NAME,
    )


def _has_next_page(soup: BeautifulSoup, current_page: int) -> bool:
    """Check if there's a next page by looking for iPage pagination links.

    Args:
        soup: Parsed HTML of the current page.
        current_page: The current page number (1-based).

    Returns:
        True if a link to a higher page number exists.
    """
    page_links = soup.find_all("a", href=re.compile(r"iPage,\d+"))
    for link in page_links:
        href = link.get("href", "")
        match = re.search(r"iPage,(\d+)", href)
        if match:
            page_num = int(match.group(1))
            if page_num > current_page:
                return True
    return False
