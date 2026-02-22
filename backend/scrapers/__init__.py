"""
Scraper Package

Provides utilities and functions for web scraping.

Exports:
    - ScraperResult: TypedDict for scraper results
    - ScraperResults: Type alias for list of results
    - create_http_client: Create configured async HTTP client
    - get_user_agent: Get User-Agent string
    - delay_between_requests: Async delay for rate limiting
    - make_absolute_url: Convert relative URLs to absolute
    - parse_price: Parse price strings to float
    - REQUEST_TIMEOUT: Timeout constant (30 seconds)
    - REQUEST_DELAY_MIN: Minimum delay constant (2 seconds)
    - REQUEST_DELAY_MAX: Maximum delay constant (5 seconds)
    - scrape_aats: Scraper function for aats-group.ch
    - scrape_aebiwaffen: Scraper function for aebiwaffen.ch
    - scrape_armashop: Scraper function for armashop.ch
    - scrape_gwmh: Scraper function for gwmh-shop.ch
    - scrape_waffenboerse: Scraper function for waffenboerse.ch
    - scrape_waffengebraucht: Scraper function for waffengebraucht.ch
    - scrape_waffenjoray: Scraper function for waffen-joray.ch
    - scrape_waffenzimmi: Scraper function for waffenzimmi.ch
    - scrape_petitesannonces: Scraper function for petitesannonces.ch
"""
from backend.scrapers.base import (
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_MIN,
    REQUEST_TIMEOUT,
    ScraperResult,
    ScraperResults,
    create_http_client,
    delay_between_requests,
    get_user_agent,
    make_absolute_url,
    parse_price,
)
from backend.scrapers.aats import scrape_aats
from backend.scrapers.aebiwaffen import scrape_aebiwaffen
from backend.scrapers.armashop import scrape_armashop
from backend.scrapers.gwmh import scrape_gwmh
from backend.scrapers.waffenboerse import scrape_waffenboerse
from backend.scrapers.waffengebraucht import scrape_waffengebraucht
from backend.scrapers.waffenjoray import scrape_waffenjoray
from backend.scrapers.waffenzimmi import scrape_waffenzimmi
from backend.scrapers.petitesannonces import scrape_petitesannonces
from backend.scrapers.renehild import scrape_renehild
from backend.scrapers.vnsm import scrape_vnsm
from backend.scrapers.ellie import scrape_ellie
from backend.scrapers.egun import scrape_egun
from backend.scrapers.gebrauchtwaffen import scrape_gebrauchtwaffen

__all__ = [
    # Type definitions
    "ScraperResult",
    "ScraperResults",
    # HTTP client
    "create_http_client",
    "get_user_agent",
    # Rate limiting
    "delay_between_requests",
    "REQUEST_TIMEOUT",
    "REQUEST_DELAY_MIN",
    "REQUEST_DELAY_MAX",
    # URL utilities
    "make_absolute_url",
    "parse_price",
    # Scrapers
    "scrape_aats",
    "scrape_aebiwaffen",
    "scrape_armashop",
    "scrape_gwmh",
    "scrape_waffenboerse",
    "scrape_waffengebraucht",
    "scrape_waffenjoray",
    "scrape_waffenzimmi",
    "scrape_petitesannonces",
    "scrape_renehild",
    "scrape_vnsm",
    "scrape_ellie",
    "scrape_egun",
    "scrape_gebrauchtwaffen",
]
