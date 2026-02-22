"""
Crawler Orchestrator for Gilbert's Yoga Helper.

Coordinates scraping all active sources, matching results against
search terms, and saving matches to the database.

Key features:
- Sequential execution (not parallel) for Pi resource constraints
- Error isolation: one scraper failure doesn't stop others
- Comprehensive logging and result tracking
- File-based locking to prevent concurrent crawls (Web UI, CLI, Cronjob)
"""
import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.database.crud import (
    create_crawl_log,
    get_active_search_terms,
    get_active_sources,
    get_or_create_source,
    save_matches,
    search_term_to_dict,
    update_crawl_log,
    update_source_crawl_status,
)
from backend.scrapers import (
    ScraperResults,
    scrape_aats,
    scrape_aebiwaffen,
    scrape_armashop,
    scrape_egun,
    scrape_ellie,
    scrape_gwmh,
    scrape_petitesannonces,
    scrape_renehild,
    scrape_vnsm,
    scrape_waffenboerse,
    scrape_waffengebraucht,
    scrape_waffenjoray,
    scrape_waffenzimmi,
)
from backend.services.matching import find_matches
from backend.services.telegram import notify_new_matches, is_telegram_configured
from backend.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# File-based Lock for Cross-Process Crawl Prevention
# =============================================================================

# Lock file location (in data directory, same as database)
LOCK_FILE_PATH = Path(__file__).parent.parent.parent / "data" / "crawl.lock"
LOCK_STALE_SECONDS = 3600  # Consider lock stale after 1 hour


def _get_lock_info() -> Optional[dict]:
    """
    Read lock file and return its contents.

    Returns:
        Dict with 'pid', 'timestamp', 'trigger' if lock exists, None otherwise.
    """
    if not LOCK_FILE_PATH.exists():
        return None

    try:
        content = LOCK_FILE_PATH.read_text().strip()
        lines = content.split('\n')
        info = {}
        for line in lines:
            if '=' in line:
                key, value = line.split('=', 1)
                info[key.strip()] = value.strip()
        return info
    except Exception as e:
        logger.warning(f"Failed to read lock file: {e}")
        return None


def _is_process_running(pid: int) -> bool:
    """Check if a process with given PID is still running."""
    import platform

    if platform.system() == "Windows":
        # On Windows, os.kill(pid, 0) doesn't work as expected
        # Use ctypes to check if process exists
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    else:
        # Unix/Linux: signal 0 checks if process exists without killing
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _is_lock_stale(lock_info: dict) -> bool:
    """
    Check if lock is stale (process dead or too old).

    A lock is stale if:
    - The process that created it is no longer running
    - The lock is older than LOCK_STALE_SECONDS
    """
    # Check if process is still alive
    try:
        pid = int(lock_info.get('pid', 0))
        if pid > 0 and not _is_process_running(pid):
            logger.info(f"Lock is stale: process {pid} no longer running")
            return True
    except (ValueError, TypeError):
        pass

    # Check if lock is too old
    try:
        timestamp = float(lock_info.get('timestamp', 0))
        age = time.time() - timestamp
        if age > LOCK_STALE_SECONDS:
            logger.info(f"Lock is stale: {age:.0f}s old (max {LOCK_STALE_SECONDS}s)")
            return True
    except (ValueError, TypeError):
        pass

    return False


def acquire_crawl_lock(trigger: str = "unknown") -> bool:
    """
    Try to acquire the crawl lock.

    Args:
        trigger: What triggered the crawl ('web', 'cli', 'cronjob')

    Returns:
        True if lock was acquired, False if another crawl is running.
    """
    # Ensure data directory exists
    LOCK_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Check existing lock
    lock_info = _get_lock_info()
    if lock_info:
        if _is_lock_stale(lock_info):
            logger.info("Removing stale lock file")
            try:
                LOCK_FILE_PATH.unlink()
            except Exception as e:
                logger.warning(f"Failed to remove stale lock: {e}")
                return False
        else:
            # Lock is held by another active process
            logger.warning(
                f"Crawl lock held by PID {lock_info.get('pid')} "
                f"(trigger: {lock_info.get('trigger', 'unknown')})"
            )
            return False

    # Create lock file
    try:
        lock_content = f"pid={os.getpid()}\ntimestamp={time.time()}\ntrigger={trigger}\n"
        LOCK_FILE_PATH.write_text(lock_content)
        logger.info(f"Acquired crawl lock (PID {os.getpid()}, trigger: {trigger})")
        return True
    except Exception as e:
        logger.error(f"Failed to create lock file: {e}")
        return False


def release_crawl_lock() -> bool:
    """
    Release the crawl lock.

    Only releases if we own the lock (same PID).

    Returns:
        True if lock was released, False otherwise.
    """
    lock_info = _get_lock_info()
    if not lock_info:
        return True  # No lock to release

    # Only release if we own the lock
    try:
        lock_pid = int(lock_info.get('pid', 0))
        if lock_pid != os.getpid():
            logger.warning(f"Cannot release lock owned by PID {lock_pid}")
            return False
    except (ValueError, TypeError):
        pass

    try:
        LOCK_FILE_PATH.unlink()
        logger.info("Released crawl lock")
        return True
    except Exception as e:
        logger.error(f"Failed to release lock: {e}")
        return False


def is_crawl_locked() -> bool:
    """
    Check if a crawl lock exists and is valid (not stale).

    Returns:
        True if a valid lock exists, False otherwise.
    """
    lock_info = _get_lock_info()
    if not lock_info:
        return False
    return not _is_lock_stale(lock_info)


def get_lock_holder_info() -> Optional[str]:
    """
    Get info about who holds the crawl lock.

    Returns:
        Human-readable string about lock holder, or None if no lock.
    """
    lock_info = _get_lock_info()
    if not lock_info or _is_lock_stale(lock_info):
        return None

    pid = lock_info.get('pid', 'unknown')
    trigger = lock_info.get('trigger', 'unknown')
    timestamp = lock_info.get('timestamp', '')

    try:
        ts = float(timestamp)
        age = time.time() - ts
        age_str = f"{int(age)}s ago"
    except (ValueError, TypeError):
        age_str = "unknown time"

    return f"PID {pid} ({trigger}, started {age_str})"


# =============================================================================
# Scraper Registry and Configuration
# =============================================================================

# Type alias for async scraper functions
AsyncScraperFunc = Callable[[], Awaitable[ScraperResults]]

# Registry mapping source names to their scraper functions
# Source names must match database source.name values
SCRAPER_REGISTRY: Dict[str, AsyncScraperFunc] = {
    "aats-group.ch": scrape_aats,
    "aebiwaffen.ch": scrape_aebiwaffen,
    "armashop.ch": scrape_armashop,
    "egun.de": scrape_egun,
    "ellie-firearms.com": scrape_ellie,
    "gwmh-shop.ch": scrape_gwmh,
    "petitesannonces.ch": scrape_petitesannonces,
    "renehild-tactical.ch": scrape_renehild,
    "vnsm.ch": scrape_vnsm,
    "waffenboerse.ch": scrape_waffenboerse,
    "waffengebraucht.ch": scrape_waffengebraucht,
    "waffen-joray.ch": scrape_waffenjoray,
    "waffenzimmi.ch": scrape_waffenzimmi,
}

# Base URLs for each source (used when creating sources)
SOURCE_BASE_URLS: Dict[str, str] = {
    "aats-group.ch": "https://aats-group.ch",
    "aebiwaffen.ch": "https://www.aebiwaffen.ch",
    "armashop.ch": "https://armashop.ch",
    "egun.de": "https://egun.de/market",
    "ellie-firearms.com": "https://ellie-firearms.com",
    "gwmh-shop.ch": "https://www.gwmh-shop.ch",
    "petitesannonces.ch": "https://www.petitesannonces.ch",
    "renehild-tactical.ch": "https://renehild-tactical.ch",
    "vnsm.ch": "https://www.vnsm.ch",
    "waffenboerse.ch": "https://www.waffenboerse.ch",
    "waffengebraucht.ch": "https://waffengebraucht.ch",
    "waffen-joray.ch": "https://waffen-joray.ch",
    "waffenzimmi.ch": "https://www.waffenzimmi.ch",
}


@dataclass
class CrawlResult:
    """Result of a complete crawl run."""

    sources_attempted: int = 0
    sources_succeeded: int = 0
    sources_failed: int = 0
    total_listings: int = 0
    new_matches: int = 0
    duplicate_matches: int = 0
    failed_sources: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def __str__(self) -> str:
        return (
            f"CrawlResult(attempted={self.sources_attempted}, "
            f"succeeded={self.sources_succeeded}, failed={self.sources_failed}, "
            f"listings={self.total_listings}, new_matches={self.new_matches}, "
            f"duplicates={self.duplicate_matches}, duration={self.duration_seconds:.1f}s)"
        )

    @property
    def is_success(self) -> bool:
        """Check if crawl was fully successful (no failures)."""
        return self.sources_failed == 0 and self.sources_attempted > 0

    @property
    def is_partial_success(self) -> bool:
        """Check if crawl had some failures but also some successes."""
        return self.sources_failed > 0 and self.sources_succeeded > 0

    @property
    def status_text(self) -> str:
        """Get human-readable status text."""
        if self.sources_attempted == 0:
            return "Keine Quellen"
        if self.is_success:
            return "Erfolgreich"
        if self.is_partial_success:
            return "Teilweise erfolgreich"
        return "Fehlgeschlagen"


@dataclass
class CrawlState:
    """
    Global crawl state for tracking running crawls.

    This is a simple in-memory state for single-user Pi deployment.
    """

    is_running: bool = False
    cancel_requested: bool = False
    last_result: Optional[CrawlResult] = None
    current_source: Optional[str] = None
    log_messages: List[str] = field(default_factory=list)
    # Progress tracking fields
    sources_total: int = 0
    sources_done: int = 0
    started_at: Optional[datetime] = None


# Global crawl state (single instance for single-user app)
_crawl_state = CrawlState()


def add_crawl_log(message: str) -> None:
    """Add a log message to the current crawl state."""
    from datetime import datetime
    timestamp = datetime.now().strftime("%H:%M:%S")
    _crawl_state.log_messages.append(f"[{timestamp}] {message}")


def clear_crawl_log() -> None:
    """Clear all log messages."""
    _crawl_state.log_messages.clear()


def get_crawl_log() -> List[str]:
    """Get all log messages."""
    return _crawl_state.log_messages.copy()


def get_registered_sources() -> List[str]:
    """Get list of all registered source names."""
    return list(SCRAPER_REGISTRY.keys())


def get_crawl_state() -> CrawlState:
    """Get the current crawl state."""
    return _crawl_state


def is_crawl_running() -> bool:
    """
    Check if a crawl is currently running.

    Checks both in-memory state (same process) and file lock (other processes).
    """
    # Check in-memory state first
    if _crawl_state.is_running:
        return True
    # Check file lock for cross-process detection
    return is_crawl_locked()


def request_crawl_cancel() -> bool:
    """
    Request cancellation of the currently running crawl.

    Returns:
        True if a crawl was running and cancellation was requested,
        False if no crawl is running.
    """
    if _crawl_state.is_running:
        _crawl_state.cancel_requested = True
        logger.info("Crawl cancellation requested")
        return True
    return False


def prepare_crawl_state(trigger: str = "web") -> bool:
    """
    Prepare the crawl state before starting a background crawl.

    This acquires the file lock, sets is_running=True, clears the log,
    and adds an initial message.
    Must be called BEFORE creating the background task to avoid race conditions.

    Args:
        trigger: What triggered the crawl ('web', 'cli', 'cronjob')

    Returns:
        True if state was prepared successfully,
        False if a crawl is already running (in this process or another).
    """
    global _crawl_state

    # Check in-memory state first (same process)
    if _crawl_state.is_running:
        logger.warning("Crawl already running in this process")
        return False

    # Try to acquire file lock (cross-process)
    if not acquire_crawl_lock(trigger):
        lock_holder = get_lock_holder_info()
        logger.warning(f"Cannot start crawl - lock held by: {lock_holder}")
        return False

    _crawl_state.is_running = True
    _crawl_state.cancel_requested = False
    _crawl_state.current_source = None
    clear_crawl_log()
    add_crawl_log("Crawl wird gestartet...")

    return True


def is_cancel_requested() -> bool:
    """Check if cancellation has been requested."""
    return _crawl_state.cancel_requested


def get_last_crawl_result() -> Optional[CrawlResult]:
    """Get the result of the last completed crawl."""
    return _crawl_state.last_result


def ensure_sources_exist(session: Session) -> Dict[str, int]:
    """
    Ensure all registered sources exist in the database.

    Creates any missing sources with their base URLs.

    Args:
        session: Database session

    Returns:
        Mapping of source name to source ID
    """
    source_map: Dict[str, int] = {}

    for name, base_url in SOURCE_BASE_URLS.items():
        source = get_or_create_source(session, name, base_url)
        source_map[name] = source.id

    return source_map


async def run_single_scraper(
    source_name: str,
    scraper_func: AsyncScraperFunc,
) -> Tuple[ScraperResults, Optional[str]]:
    """
    Run a single scraper with error isolation.

    Args:
        source_name: Name of the source for logging
        scraper_func: Async scraper function to call

    Returns:
        Tuple of (results, error_message). Error is None on success.
    """
    try:
        results = await scraper_func()
        return results, None
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.error(f"Scraper failed for {source_name}: {error_msg}")
        return [], error_msg


async def run_crawl_async(
    session: Session,
    state_prepared: bool = False,
    trigger: str = "manual"
) -> CrawlResult:
    """
    Run complete crawl asynchronously: scrape all active sources, match, and save.

    This is the async version for use with async contexts.

    Args:
        session: Database session
        state_prepared: If True, assumes prepare_crawl_state() was already called.
                       This avoids race conditions when starting crawl in background.
        trigger: 'manual' or 'cronjob' - how the crawl was initiated

    Returns:
        CrawlResult with statistics about the crawl

    Raises:
        RuntimeError: If a crawl is already running (and state not prepared)
    """
    global _crawl_state

    # If state was not prepared by caller, set it up now (including lock)
    if not state_prepared:
        # Check if already running (in-memory)
        if _crawl_state.is_running:
            raise RuntimeError("A crawl is already running in this process")

        # Try to acquire file lock (cross-process)
        if not acquire_crawl_lock(trigger):
            lock_holder = get_lock_holder_info()
            raise RuntimeError(f"A crawl is already running: {lock_holder}")

        # Mark as running, reset cancel flag and clear log
        _crawl_state.is_running = True
        _crawl_state.cancel_requested = False
        _crawl_state.current_source = None
        clear_crawl_log()

    start_time = time.time()
    result = CrawlResult()
    result.started_at = datetime.now(timezone.utc)

    # Initialize progress tracking
    _crawl_state.started_at = result.started_at
    _crawl_state.sources_done = 0
    _crawl_state.sources_total = 0

    # Create crawl log entry
    crawl_log = create_crawl_log(session, trigger=trigger)

    logger.info("Starting crawl run")
    add_crawl_log("Crawl gestartet")

    try:
        # Ensure all sources exist in database and get source_id mapping
        source_map = ensure_sources_exist(session)

        # Get active sources
        active_sources = get_active_sources(session)
        if not active_sources:
            logger.warning("No active sources found")
            add_crawl_log("Keine aktiven Quellen gefunden")
            result.duration_seconds = time.time() - start_time
            result.completed_at = datetime.now(timezone.utc)
            _crawl_state.last_result = result
            # Update crawl log with failed status (no sources)
            update_crawl_log(
                session, crawl_log, status="failed",
                duration_seconds=result.duration_seconds,
            )
            return result

        logger.info(f"Found {len(active_sources)} active sources")
        add_crawl_log(f"{len(active_sources)} aktive Quellen gefunden")

        # Set total for progress tracking
        _crawl_state.sources_total = len(active_sources)

        # Store source info upfront to avoid session expiry issues
        # After commits, ORM objects become stale, so we need plain data
        source_info = [(s.id, s.name) for s in active_sources]

        # Collect all listings from all scrapers
        all_listings: ScraperResults = []

        for source_id, source_name in source_info:
            # Check for cancellation before starting next source
            if _crawl_state.cancel_requested:
                logger.info("Crawl cancelled by user")
                result.duration_seconds = time.time() - start_time
                result.completed_at = datetime.now(timezone.utc)
                _crawl_state.last_result = result
                _log_crawl_summary(result)
                # Update crawl log with cancelled status
                update_crawl_log(
                    session, crawl_log, status="cancelled",
                    sources_attempted=result.sources_attempted,
                    sources_succeeded=result.sources_succeeded,
                    sources_failed=result.sources_failed,
                    total_listings=result.total_listings,
                    new_matches=result.new_matches,
                    duplicate_matches=result.duplicate_matches,
                    duration_seconds=result.duration_seconds,
                )
                return result

            result.sources_attempted += 1

            # Check if scraper exists for this source
            scraper_func = SCRAPER_REGISTRY.get(source_name)
            if not scraper_func:
                logger.warning(f"No scraper registered for source: {source_name}")
                result.sources_failed += 1
                result.failed_sources.append(source_name)
                # Update source status using direct SQL to avoid stale data issues
                update_source_crawl_status(session, source_id, success=False, error_message="No scraper registered")
                continue

            logger.info(f"Running scraper for {source_name}")
            _crawl_state.current_source = source_name
            add_crawl_log(f"Starte {source_name}...")

            # Run scraper with error isolation (await async scraper)
            listings, error = await run_single_scraper(source_name, scraper_func)

            if error:
                result.sources_failed += 1
                result.failed_sources.append(source_name)
                # Update source status using direct SQL to avoid stale data issues
                update_source_crawl_status(session, source_id, success=False, error_message=error)
                add_crawl_log(f"✗ {source_name}: Fehler - {error[:50]}")
            else:
                result.sources_succeeded += 1
                result.total_listings += len(listings)
                all_listings.extend(listings)
                # Update source status using direct SQL to avoid stale data issues
                update_source_crawl_status(session, source_id, success=True)
                logger.info(f"Scraped {len(listings)} listings from {source_name}")
                add_crawl_log(f"✓ {source_name}: {len(listings)} Inserate gefunden")

            # Update progress
            _crawl_state.sources_done += 1

        # Source updates are committed individually in update_source_crawl_status

        # Get active search terms for matching
        search_terms = get_active_search_terms(session)
        if not search_terms:
            logger.warning("No active search terms found, skipping matching")
            add_crawl_log("Keine Suchbegriffe - Matching übersprungen")
            result.duration_seconds = time.time() - start_time
            result.completed_at = datetime.now(timezone.utc)
            _crawl_state.last_result = result
            _log_crawl_summary(result)
            # Update crawl log - partial success (scraped but no matching)
            update_crawl_log(
                session, crawl_log, status="partial",
                sources_attempted=result.sources_attempted,
                sources_succeeded=result.sources_succeeded,
                sources_failed=result.sources_failed,
                total_listings=result.total_listings,
                duration_seconds=result.duration_seconds,
            )
            return result

        # Convert search terms to dict format for matching
        term_dicts = [search_term_to_dict(term) for term in search_terms]

        logger.info(
            f"Matching {len(all_listings)} listings against {len(term_dicts)} search terms"
        )
        add_crawl_log(f"Vergleiche {len(all_listings)} Inserate mit {len(term_dicts)} Suchbegriffen...")

        # Find matches (exclude terms are only applied visually in dashboard, not during crawl)
        match_results = find_matches(all_listings, term_dicts)
        logger.info(f"Found {len(match_results)} potential matches")
        add_crawl_log(f"→ {len(match_results)} potentielle Treffer gefunden")

        # Save matches with deduplication
        new_matches_for_telegram = []
        if match_results:
            add_crawl_log("Speichere Treffer...")
            new_count, dup_count, new_matches_for_telegram = save_matches(
                session, match_results, source_map, return_new_matches=True
            )
            result.new_matches = new_count
            result.duplicate_matches = dup_count
            add_crawl_log(f"✓ {new_count} neue Treffer, {dup_count} Duplikate übersprungen")

        result.duration_seconds = time.time() - start_time
        result.completed_at = datetime.now(timezone.utc)

        # Update global state
        _crawl_state.last_result = result

        _log_crawl_summary(result)

        # Send Telegram notification if configured and there are new matches
        if is_telegram_configured() and result.new_matches > 0:
            add_crawl_log("Sende Telegram-Benachrichtigung...")
            try:
                await notify_new_matches(
                    new_matches_for_telegram,
                    result.new_matches,
                    int(result.duration_seconds)
                )
                add_crawl_log("✓ Telegram-Benachrichtigung gesendet")
            except Exception as e:
                logger.error(f"Failed to send Telegram notification: {e}")
                add_crawl_log(f"✗ Telegram-Fehler: {str(e)[:30]}")
        add_crawl_log(f"Crawl abgeschlossen in {result.duration_seconds:.1f}s")

        # Determine final status
        if result.sources_failed > 0 and result.sources_succeeded > 0:
            status = "partial"
        elif result.sources_failed > 0:
            status = "failed"
        else:
            status = "success"

        # Update crawl log with final results
        update_crawl_log(
            session, crawl_log, status=status,
            sources_attempted=result.sources_attempted,
            sources_succeeded=result.sources_succeeded,
            sources_failed=result.sources_failed,
            total_listings=result.total_listings,
            new_matches=result.new_matches,
            duplicate_matches=result.duplicate_matches,
            duration_seconds=result.duration_seconds,
        )

        return result

    except Exception as e:
        logger.error(f"Crawl failed with exception: {e}")
        add_crawl_log(f"✗ FEHLER: {str(e)}")
        # Update crawl log with failed status
        result.duration_seconds = time.time() - start_time
        update_crawl_log(
            session, crawl_log, status="failed",
            sources_attempted=result.sources_attempted,
            sources_succeeded=result.sources_succeeded,
            sources_failed=result.sources_failed,
            total_listings=result.total_listings,
            duration_seconds=result.duration_seconds,
        )
        raise

    finally:
        # Always reset running state and release lock
        _crawl_state.is_running = False
        _crawl_state.cancel_requested = False
        _crawl_state.current_source = None
        release_crawl_lock()


def run_crawl(session: Session) -> CrawlResult:
    """
    Run complete crawl: scrape all active sources, match, and save.

    This is the main entry point for crawling. It:
    1. Gets active sources from database
    2. Runs each scraper sequentially
    3. Handles failures gracefully
    4. Matches all results against search terms
    5. Saves matches with deduplication
    6. Logs summary

    This is a synchronous wrapper around run_crawl_async for use in
    non-async contexts (like CLI commands).

    Args:
        session: Database session

    Returns:
        CrawlResult with statistics about the crawl
    """
    return asyncio.run(run_crawl_async(session))


def _log_crawl_summary(result: CrawlResult) -> None:
    """Log a summary of the crawl results."""
    logger.info("=" * 60)
    logger.info("CRAWL SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Sources attempted: {result.sources_attempted}")
    logger.info(f"Sources succeeded: {result.sources_succeeded}")
    logger.info(f"Sources failed: {result.sources_failed}")

    if result.failed_sources:
        logger.info(f"Failed sources: {', '.join(result.failed_sources)}")

    logger.info(f"Total listings scraped: {result.total_listings}")
    logger.info(f"New matches saved: {result.new_matches}")
    logger.info(f"Duplicate matches skipped: {result.duplicate_matches}")
    logger.info(f"Duration: {result.duration_seconds:.1f} seconds")
    logger.info("=" * 60)
