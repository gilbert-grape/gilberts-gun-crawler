"""
egun.de Scraper

Scrapes firearms listings from egun.de marketplace using their search functionality.
Site uses a custom PHP-based auction platform with table-based layouts.
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
)
from backend.utils.logging import get_logger

logger = get_logger(__name__)

BASE_URL = "https://egun.de/market"
SEARCH_URL = f"{BASE_URL}/list_items.php"
SOURCE_NAME = "egun.de"
MAX_PAGES = 5  # Max pages per search term


async def scrape_egun(search_terms: Optional[List[str]] = None) -> ScraperResults:
    """
    Scrape listings from egun.de using search.

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
                    # Construct search URL - type=1 for auctions, type=2 for buy-now
                    encoded_term = quote_plus(term)
                    url = f"{SEARCH_URL}?keyword={encoded_term}&type=1"
                    if page > 1:
                        url += f"&page={page}"
                    add_crawl_log(f"    Seite {page}...")

                    response = await client.get(url)
                    response.raise_for_status()

                    # Parse HTML
                    soup = BeautifulSoup(response.text, "html.parser")

                    # Find all item rows - egun uses table rows for listings
                    # Look for links to item.php which indicate product rows
                    item_links = soup.select("a[href*='item.php?id=']")

                    if not item_links:
                        if page == 1:
                            add_crawl_log(f"    Keine Ergebnisse für '{term}'")
                        break

                    # Process each item link and its parent row
                    page_results = 0
                    processed_ids = set()

                    for link in item_links:
                        try:
                            # Extract item ID to avoid duplicates on same page
                            href = link.get("href", "")
                            id_match = re.search(r"id=(\d+)", href)
                            if not id_match:
                                continue
                            item_id = id_match.group(1)

                            # Skip if already processed, but only if link has no text
                            # (image links have no text, title links have text)
                            link_text = link.get_text(strip=True)
                            if item_id in processed_ids:
                                # If this is a link with text and we haven't found a good result yet,
                                # we might want to process it - but for now just skip
                                continue

                            # Only mark as processed if this link has actual text (title)
                            # This ensures we don't skip the title link after seeing the image link
                            if link_text:
                                processed_ids.add(item_id)
                            else:
                                # Image link - skip and wait for title link
                                continue

                            # Find parent row (usually a <tr>)
                            row = _find_parent_row(link)
                            if not row:
                                continue

                            result = _parse_listing(row, link)
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


def _find_parent_row(element: Tag) -> Optional[Tag]:
    """Find the parent table row of an element."""
    parent = element.parent
    for _ in range(10):  # Don't go too far up
        if parent is None:
            break
        if parent.name == "tr":
            return parent
        parent = parent.parent
    return None


def _has_next_page(soup: BeautifulSoup, current_page: int) -> bool:
    """Check if there's a next page link in pagination."""
    # Look for page links like "Seite 2", "Seite 3", etc.
    page_links = soup.find_all("a", href=re.compile(r"page=\d+"))
    for link in page_links:
        href = link.get("href", "")
        match = re.search(r"page=(\d+)", href)
        if match:
            page_num = int(match.group(1))
            if page_num > current_page:
                return True
    return False


def _parse_listing(row: Tag, title_link: Tag) -> Optional[ScraperResult]:
    """Parse a table row into ScraperResult."""
    # Extract title from the link
    title = title_link.get_text(strip=True)
    if not title:
        return None

    # Extract link
    href = title_link.get("href", "")
    if not href:
        return None
    link = make_absolute_url(BASE_URL + "/", href)

    # Extract price from the row
    price = _extract_price(row)

    # Extract image URL from the row
    image_url = _extract_image_url(row)

    return ScraperResult(
        title=title,
        price=price,
        image_url=image_url,
        link=link,
        source=SOURCE_NAME
    )


def _extract_price(row: Tag) -> Optional[float]:
    """Extract price from a table row."""
    # Find all td elements
    cells = row.find_all("td")

    # Price is typically in the 3rd column (index 2)
    # Look for EUR pattern in cells
    for cell in cells:
        text = cell.get_text(strip=True)
        # Match patterns like "500.00 EUR" or "1.234,56 EUR"
        if "EUR" in text:
            # Extract the number before EUR
            match = re.search(r"([\d.,]+)\s*EUR", text)
            if match:
                price_str = match.group(1)
                # German format: dot as thousands, comma as decimal
                # Convert to standard format
                price_str = price_str.replace(".", "").replace(",", ".")
                try:
                    return float(price_str)
                except ValueError:
                    pass

    return None


def _extract_image_url(row: Tag) -> Optional[str]:
    """Extract image URL from a table row."""
    # Find image in the row
    img = row.find("img")
    if img:
        for attr in ["src", "data-src"]:
            img_url = img.get(attr)
            if img_url:
                if isinstance(img_url, list):
                    img_url = img_url[0]
                # Skip placeholder/icon images
                if "placeholder" not in img_url.lower() and "icon" not in img_url.lower():
                    return make_absolute_url(BASE_URL + "/", img_url)
    return None
