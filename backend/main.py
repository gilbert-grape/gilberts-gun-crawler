"""
Gilbert's Yoga Helper - Main FastAPI Application

Database Migrations:
    This application uses Alembic for database migrations.
    Before starting the application, ensure migrations are applied:

        # Apply all pending migrations
        alembic upgrade head

        # Or check current migration status
        alembic current

    The application verifies database connectivity on startup but does NOT
    auto-run migrations to prevent accidental schema changes in production.

Logging:
    Logging is automatically configured on backend package import.
    Logs are written to logs/app.log with rotation (5MB max, 3 backups).
    Console logging is enabled in DEBUG mode.

    Configuration via environment variables:
        - LOG_LEVEL: DEBUG, INFO, WARNING, ERROR (default: INFO)
        - LOG_FILE: Log file path (default: logs/app.log)
        - LOG_MAX_SIZE: Max file size before rotation (default: 5MB)
        - LOG_BACKUP_COUNT: Number of backup files (default: 3)
"""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

# Import from backend package ensures logging is initialized (via backend/__init__.py)
from backend.database import (
    engine,
    get_db,
    get_all_search_terms,
    get_active_search_terms,
    get_search_term_by_id,
    get_search_term_by_term,
    create_search_term,
    delete_search_term,
    update_search_term_match_type,
    toggle_search_term_hide_seen,
    move_search_term_up,
    move_search_term_down,
    get_all_sources,
    get_all_sources_sorted,
    toggle_source_active,
    clear_source_error,
    move_source_up,
    move_source_down,
    get_matches_by_search_term,
    mark_matches_as_seen,
    clear_all_matches,
    get_all_exclude_terms_sorted,
    get_active_exclude_terms,
    get_exclude_term_by_id,
    get_exclude_term_by_term,
    create_exclude_term,
    delete_exclude_term,
    toggle_exclude_term_active,
    get_crawl_logs,
    get_avg_crawl_duration,
    DATABASE_PATH,
)
from backend.services.crawler import (
    run_crawl_async,
    is_crawl_running,
    get_crawl_state,
    get_crawl_log,
    request_crawl_cancel,
    prepare_crawl_state,
    ensure_sources_exist,
    get_lock_holder_info,
)
from backend.utils.logging import get_logger

logger = get_logger(__name__)

# Get project root directory (one level up from backend/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"


def verify_database() -> None:
    """
    Verify database connectivity and migration status on startup.

    This function checks that:
    1. The database file exists (or can be created)
    2. The database is accessible
    3. Expected tables exist (warns if not)

    Note: This does NOT run migrations automatically. Use 'alembic upgrade head'
    to apply migrations before starting the application.
    """
    # Check if database file exists
    if not DATABASE_PATH.exists():
        logger.error(
            f"Database file not found at {DATABASE_PATH}. "
            "Run 'alembic upgrade head' to create the database. "
            "Application may not function correctly without a database."
        )
        return

    # Verify database connectivity and check for expected tables
    try:
        with engine.connect() as conn:
            # Check for alembic_version table (indicates migrations have been run)
            result = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'")
            )
            if result.fetchone() is None:
                logger.warning(
                    "Alembic version table not found. "
                    "Run 'alembic upgrade head' to apply migrations."
                )
                return

            # Check for expected application tables
            expected_tables = ['search_terms', 'sources', 'matches']
            result = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            existing_tables = {row[0] for row in result.fetchall()}

            missing_tables = set(expected_tables) - existing_tables
            if missing_tables:
                logger.warning(
                    f"Missing tables: {missing_tables}. "
                    "Run 'alembic upgrade head' to apply pending migrations."
                )
            else:
                logger.info("Database verification successful. All expected tables exist.")

    except Exception as e:
        logger.error(f"Database verification failed: {e}")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler for startup and shutdown events.

    Startup:
        - Verifies database connectivity and migration status
        - Creates all registered sources if they don't exist
        - Does NOT auto-run migrations (use 'alembic upgrade head' manually)

    Shutdown:
        - Currently no cleanup required
    """
    # Startup: Verify database (but don't auto-migrate)
    verify_database()

    # Create all registered sources and default terms at startup
    from backend.database import (
        SessionLocal,
        ensure_default_search_terms,
        ensure_default_exclude_terms,
    )
    db = SessionLocal()
    try:
        ensure_sources_exist(db)
        logger.info("All registered sources initialized")
        ensure_default_search_terms(db)
        logger.info("Default search terms initialized")
        ensure_default_exclude_terms(db)
        logger.info("Default exclude terms initialized")
    except Exception as e:
        logger.error(f"Failed to initialize startup data: {e}")
    finally:
        db.close()

    yield
    # Shutdown: cleanup if needed (none currently)


app = FastAPI(
    title="Gilbert's Yoga Helper",
    description="Swiss used firearms marketplace aggregator",
    version="0.1.0",
    lifespan=lifespan,
)

# Ensure static files directory exists
STATIC_DIR = FRONTEND_DIR / "public"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Mount static files with absolute path
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Templates with absolute path
templates = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))

# Custom Jinja2 filter to calculate age in days
def age_in_days_filter(created_at):
    """Calculate age in days from created_at timestamp. Returns 1 for today, 2 for yesterday, etc."""
    if not created_at:
        return 0
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    created_utc = created_at.replace(tzinfo=timezone.utc) if created_at.tzinfo is None else created_at
    days = (now - created_utc).days
    return max(1, days + 1)

templates.env.filters["age_in_days"] = age_in_days_filter


def format_duration(seconds: Optional[float]) -> str:
    """
    Format duration in seconds to a human-readable string.

    Examples:
        45 -> "45s"
        90 -> "1.5min"
        300 -> "5min"
        3600 -> "1h"
        5400 -> "1.5h"
    """
    if seconds is None or seconds == 0:
        return "-"

    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = seconds / 60
        if minutes == int(minutes):
            return f"{int(minutes)}min"
        return f"{minutes:.1f}min"
    else:
        hours = seconds / 3600
        if hours == int(hours):
            return f"{int(hours)}h"
        return f"{hours:.1f}h"


# Register custom Jinja2 filter
templates.env.filters["format_duration"] = format_duration


@app.get("/")
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    filter: Optional[bool] = None,
):
    """
    Dashboard home page showing all matches grouped by search term.

    Displays:
    - Matches grouped by search term with collapsible sections
    - Count of new (unseen) matches per group and total
    - Empty state for search terms with no matches
    - Duplicate filtering based on hide_seen_matches setting
    - Exclude term filtering (matches containing exclude terms are hidden)
    - Source filtering (only show matches from selected sources)

    Args:
        filter: If True, hide matches containing exclude terms.
                If False, show all matches including those with exclude terms.
                If None, read from cookie (default: True).

    After displaying, marks all matches as seen so they won't
    appear as "new" on the next visit.
    """
    # Determine filter state: URL param > cookie > default (True)
    if filter is None:
        filter_cookie = request.cookies.get("filter_mode", "true")
        filter = filter_cookie.lower() != "false"

    # Time filter: "all", "1d", "7d", "1m", "3m" - from URL param or cookie
    time_filter_cookie = request.cookies.get("time_filter", "all")
    time_filter = request.query_params.get("time_filter", time_filter_cookie)
    if time_filter not in ("all", "1d", "7d", "1m", "3m"):
        time_filter = "all"

    # Favorites filter: URL param > cookie > default (False)
    favorites_only_cookie = request.cookies.get("favorites_only", "false")
    favorites_only_param = request.query_params.get("favorites_only", favorites_only_cookie)
    favorites_only = favorites_only_param.lower() == "true"

    # Calculate the cutoff date based on time filter
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    time_filter_days = {
        "1d": 1,
        "7d": 7,
        "1m": 30,
        "3m": 90,
        "all": None,
    }
    filter_days = time_filter_days.get(time_filter)
    recent_cutoff = now - timedelta(days=filter_days) if filter_days else None

    # Get all sources for the filter dropdown
    all_sources = get_all_sources(db)

    # Get selected sources from cookie (default: all sources selected)
    # Note: Cookie value is URL-encoded by JavaScript, so we need to decode it
    # Distinguish between: cookie not set (default all) vs cookie empty (user selected none)
    if "selected_sources" in request.cookies:
        selected_sources_cookie = unquote(request.cookies.get("selected_sources", ""))
        selected_source_ids = set(int(s) for s in selected_sources_cookie.split(",") if s.isdigit())
    else:
        # Cookie not set: default to all sources selected
        selected_source_ids = {s.id for s in all_sources}

    # Get all search terms (including those with no matches), sorted by sort_order
    search_terms = get_all_search_terms(db)

    # Get active exclude terms for filtering
    exclude_terms = get_active_exclude_terms(db)
    exclude_patterns = [et.term.lower() for et in exclude_terms]

    def matches_exclude_term(title: str) -> bool:
        """Check if a title contains any exclude term (case-insensitive)."""
        title_lower = title.lower()
        return any(pattern in title_lower for pattern in exclude_patterns)

    # Build groups with matches, filtering duplicates and optionally exclude terms
    groups = []
    total_count = 0
    total_new_count = 0
    seen_urls = set()  # Track URLs already shown by earlier search terms

    for term in search_terms:
        all_matches = get_matches_by_search_term(db, term.id)

        # Filter by selected sources
        source_filtered_matches = [m for m in all_matches if m.source_id in selected_source_ids]

        # Filter out matches containing exclude terms (only if filter is enabled)
        if filter:
            filtered_matches = [m for m in source_filtered_matches if not matches_exclude_term(m.title)]
        else:
            filtered_matches = list(source_filtered_matches)

        # Filter out duplicates if hide_seen_matches is enabled
        if term.hide_seen_matches:
            matches = [m for m in filtered_matches if m.url not in seen_urls]
        else:
            matches = filtered_matches

        # Add all match URLs from this term to the seen set (for filtering later terms)
        for m in filtered_matches:
            seen_urls.add(m.url)

        # Add is_recent flag and age_days to each match (< 7 days old for badge display)
        for m in matches:
            created_utc = m.created_at.replace(tzinfo=timezone.utc) if m.created_at else None
            if created_utc:
                age = (now - created_utc).days
                setattr(m, 'age_days', max(1, age + 1))  # Today = 1, yesterday = 2, etc.
                m.is_recent = age < 7
            else:
                setattr(m, 'age_days', 0)
                m.is_recent = False

        # Filter by time filter if not "all"
        if recent_cutoff:
            matches = [m for m in matches if m.created_at and m.created_at.replace(tzinfo=timezone.utc) > recent_cutoff]

        # Filter by favorites only if enabled
        if favorites_only:
            matches = [m for m in matches if m.is_favorite]

        new_count = sum(1 for m in matches if m.is_recent)
        groups.append({
            "term": term,
            "matches": matches,
            "total_count": len(matches),
            "new_count": new_count,
        })
        total_count += len(matches)
        total_new_count += new_count

    # Build response first (so matches still show as "new" in this render)
    response = templates.TemplateResponse("dashboard.html", {"request": request,
            "title": "Home",
            "groups": groups,
            "total_count": total_count,
            "new_count": total_new_count,
            "filter_enabled": filter,
            "time_filter": time_filter,
            "favorites_only": favorites_only,
            "all_sources": all_sources,
            "selected_source_ids": selected_source_ids,
            "now": now,  # Pass current time for age calculation in templates
        },
    )

    # Mark matches as seen after building response
    # This ensures the current view shows NEW badges, but next view won't
    mark_matches_as_seen(db)

    return response


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# =============================================================================
# REST API v1 Endpoints
# =============================================================================


@app.get("/api/v1/matches")
async def api_get_matches(
    db: Session = Depends(get_db),
    source_id: Optional[int] = None,
    search_term_id: Optional[int] = None,
    favorites_only: bool = False,
    limit: int = 100,
    offset: int = 0,
):
    """
    Get all matches with optional filters.

    Query params:
        source_id: Filter by source ID
        search_term_id: Filter by search term ID
        favorites_only: Only return favorites
        limit: Max results (default 100)
        offset: Skip first N results

    Returns:
        JSON list of matches
    """
    from sqlalchemy import desc
    from backend.database.models import Match

    query = db.query(Match).order_by(desc(Match.created_at))

    if source_id:
        query = query.filter(Match.source_id == source_id)
    if search_term_id:
        query = query.filter(Match.search_term_id == search_term_id)
    if favorites_only:
        query = query.filter(Match.is_favorite == True)  # noqa: E712

    total = query.count()
    matches = query.offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "matches": [
            {
                "id": m.id,
                "title": m.title,
                "price": m.price,
                "url": m.url,
                "image_url": m.image_url,
                "is_favorite": m.is_favorite,
                "is_new": m.is_new,
                "source_id": m.source_id,
                "source_name": m.source.name if m.source else None,
                "search_term_id": m.search_term_id,
                "search_term": m.search_term.term if m.search_term else None,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in matches
        ],
    }


@app.get("/api/v1/matches/new")
async def api_get_new_matches(
    db: Session = Depends(get_db),
    limit: int = 50,
):
    """
    Get new matches from the last crawl.

    Returns matches where is_new=True (not yet seen by user).

    Query params:
        limit: Max results (default 50)

    Returns:
        JSON list of new matches
    """
    from sqlalchemy import desc
    from backend.database.models import Match

    query = db.query(Match).filter(Match.is_new == True).order_by(desc(Match.created_at))  # noqa: E712
    matches = query.limit(limit).all()

    return {
        "count": len(matches),
        "matches": [
            {
                "id": m.id,
                "title": m.title,
                "price": m.price,
                "url": m.url,
                "image_url": m.image_url,
                "source_id": m.source_id,
                "source_name": m.source.name if m.source else None,
                "search_term_id": m.search_term_id,
                "search_term": m.search_term.term if m.search_term else None,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in matches
        ],
    }


@app.get("/api/v1/sources")
async def api_get_sources(db: Session = Depends(get_db)):
    """
    Get all sources.

    Returns:
        JSON list of sources with status
    """
    sources = get_all_sources(db)

    return {
        "count": len(sources),
        "sources": [
            {
                "id": s.id,
                "name": s.name,
                "base_url": s.base_url,
                "is_active": s.is_active,
                "last_crawl_at": s.last_crawl_at.isoformat() if s.last_crawl_at else None,
                "last_error": s.last_error,
            }
            for s in sources
        ],
    }


@app.get("/api/v1/search-terms")
async def api_get_search_terms(db: Session = Depends(get_db)):
    """
    Get all search terms.

    Returns:
        JSON list of search terms
    """
    terms = get_all_search_terms(db)

    return {
        "count": len(terms),
        "search_terms": [
            {
                "id": t.id,
                "term": t.term,
                "match_type": t.match_type,
                "is_active": t.is_active,
                "sort_order": t.sort_order,
            }
            for t in terms
        ],
    }


@app.post("/api/v1/notifications/test")
async def api_test_notification():
    """
    Send a test Telegram notification.

    Returns:
        JSON with success status
    """
    from backend.services.telegram import send_test_notification, is_telegram_configured

    if not is_telegram_configured():
        return {
            "success": False,
            "error": "Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment.",
        }

    success = await send_test_notification()

    return {
        "success": success,
        "message": "Test notification sent" if success else "Failed to send notification",
    }


@app.post("/api/toggle-favorite/{match_id}")
async def toggle_favorite(match_id: int, db: Session = Depends(get_db)):
    """
    Toggle the favorite status of a match.

    Returns JSON with the new favorite status.
    """
    from backend.database.crud import toggle_favorite as db_toggle_favorite

    new_status = db_toggle_favorite(db, match_id)
    if new_status is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Match not found")

    return {"match_id": match_id, "is_favorite": new_status}


@app.get("/admin/search-terms")
async def admin_search_terms(request: Request, db: Session = Depends(get_db)):
    """
    Admin page for managing search terms.

    Displays all search terms sorted by sort_order with options to:
    - Add new search terms
    - Delete existing search terms
    - Toggle match type (exact/similar)
    - Reorder search terms (move up/down)
    """
    search_terms = get_all_search_terms(db)
    return templates.TemplateResponse("admin/search_terms.html", {"request": request,
            "title": "Begriffe",
            "search_terms": search_terms,
        }
    )


@app.post("/admin/search-terms")
async def add_search_term(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Add a new search term via HTMX form submission.

    Returns the updated search terms list partial for HTMX swap.
    """
    form = await request.form()
    term_text = form.get("term", "").strip()
    match_type = form.get("match_type", "exact")

    error = None

    # Validation
    if not term_text:
        error = "Suchbegriff darf nicht leer sein."
    elif get_search_term_by_term(db, term_text):
        error = f"Suchbegriff '{term_text}' existiert bereits."
    elif match_type not in ("exact", "similar"):
        error = "Ungültiger Matching-Typ."

    if error:
        search_terms = get_all_search_terms(db)
        return templates.TemplateResponse("admin/_partials/_search_terms_list.html", {"request": request, 
                "search_terms": search_terms,
                "error": error,
            }
        )

    # Create the new search term
    create_search_term(db, term_text, match_type)
    search_terms = get_all_search_terms(db)

    return templates.TemplateResponse("admin/_partials/_search_terms_list.html", {"request": request, 
            "search_terms": search_terms,
            "success": f"Suchbegriff '{term_text}' hinzugefügt.",
        }
    )


@app.delete("/admin/search-terms/{term_id}")
async def remove_search_term(
    request: Request,
    term_id: int,
    db: Session = Depends(get_db)
):
    """
    Delete a search term via HTMX request.

    Returns the updated search terms list partial for HTMX swap.
    """
    term = get_search_term_by_id(db, term_id)
    term_text = term.term if term else "Unbekannt"

    success = delete_search_term(db, term_id)
    search_terms = get_all_search_terms(db)

    message = None
    if success:
        message = f"Suchbegriff '{term_text}' gelöscht."

    return templates.TemplateResponse("admin/_partials/_search_terms_list.html", {"request": request, 
            "search_terms": search_terms,
            "success": message,
        }
    )


@app.patch("/admin/search-terms/{term_id}/match-type")
async def toggle_match_type(
    request: Request,
    term_id: int,
    db: Session = Depends(get_db)
):
    """
    Toggle a search term's match type between exact and similar.

    Returns the updated search term row partial for HTMX swap.
    """
    term = get_search_term_by_id(db, term_id)
    if not term:
        return templates.TemplateResponse("admin/_partials/_search_term_row.html", {"request": request, "term": None, "error": "Suchbegriff nicht gefunden."}
        )

    # Toggle the match type
    new_type = "similar" if term.match_type == "exact" else "exact"
    updated_term = update_search_term_match_type(db, term_id, new_type)

    return templates.TemplateResponse("admin/_partials/_search_term_row.html", {"request": request, "term": updated_term}
    )


@app.patch("/admin/search-terms/{term_id}/hide-seen")
async def toggle_hide_seen(
    request: Request,
    term_id: int,
    db: Session = Depends(get_db)
):
    """
    Toggle a search term's hide_seen_matches setting.

    Returns the updated search term row partial for HTMX swap.
    """
    updated_term = toggle_search_term_hide_seen(db, term_id)
    if not updated_term:
        return templates.TemplateResponse("admin/_partials/_search_term_row.html", {"request": request, "term": None, "error": "Suchbegriff nicht gefunden."}
        )

    return templates.TemplateResponse("admin/_partials/_search_term_row.html", {"request": request, "term": updated_term}
    )


@app.post("/admin/search-terms/{term_id}/move-up")
async def move_term_up(
    request: Request,
    term_id: int,
    db: Session = Depends(get_db)
):
    """
    Move a search term up in sort order.

    Returns the updated search terms list partial for HTMX swap.
    """
    move_search_term_up(db, term_id)
    search_terms = get_all_search_terms(db)

    return templates.TemplateResponse("admin/_partials/_search_terms_list.html", {"request": request, "search_terms": search_terms}
    )


@app.post("/admin/search-terms/{term_id}/move-down")
async def move_term_down(
    request: Request,
    term_id: int,
    db: Session = Depends(get_db)
):
    """
    Move a search term down in sort order.

    Returns the updated search terms list partial for HTMX swap.
    """
    move_search_term_down(db, term_id)
    search_terms = get_all_search_terms(db)

    return templates.TemplateResponse("admin/_partials/_search_terms_list.html", {"request": request, "search_terms": search_terms}
    )


# =============================================================================
# Exclude Terms Admin Routes
# =============================================================================


@app.get("/admin/exclude-terms")
async def admin_exclude_terms(request: Request, db: Session = Depends(get_db)):
    """
    Admin page for managing exclude terms (negative keywords).

    Displays all exclude terms sorted alphabetically with options to:
    - Add new exclude terms
    - Delete existing exclude terms
    - Toggle active state
    """
    exclude_terms = get_all_exclude_terms_sorted(db)
    return templates.TemplateResponse("admin/exclude_terms.html", {"request": request, 
            "title": "Ausschlüsse",
            "exclude_terms": exclude_terms,
        }
    )


@app.post("/admin/exclude-terms")
async def add_exclude_term(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Add a new exclude term via HTMX form submission.

    Returns the updated exclude terms list partial for HTMX swap.
    """
    form = await request.form()
    term_text = form.get("term", "").strip()

    error = None

    # Validation
    if not term_text:
        error = "Ausschlussbegriff darf nicht leer sein."
    elif get_exclude_term_by_term(db, term_text):
        error = f"Ausschlussbegriff '{term_text}' existiert bereits."

    if error:
        exclude_terms = get_all_exclude_terms_sorted(db)
        return templates.TemplateResponse("admin/_partials/_exclude_terms_list.html", {"request": request, 
                "exclude_terms": exclude_terms,
                "error": error,
            }
        )

    # Create the new exclude term
    create_exclude_term(db, term_text)
    exclude_terms = get_all_exclude_terms_sorted(db)

    return templates.TemplateResponse("admin/_partials/_exclude_terms_list.html", {"request": request, 
            "exclude_terms": exclude_terms,
            "success": f"Ausschlussbegriff '{term_text}' hinzugefügt.",
        }
    )


@app.delete("/admin/exclude-terms/{term_id}")
async def remove_exclude_term(
    request: Request,
    term_id: int,
    db: Session = Depends(get_db)
):
    """
    Delete an exclude term via HTMX request.

    Returns the updated exclude terms list partial for HTMX swap.
    """
    term = get_exclude_term_by_id(db, term_id)
    term_text = term.term if term else "Unbekannt"

    success = delete_exclude_term(db, term_id)
    exclude_terms = get_all_exclude_terms_sorted(db)

    message = None
    if success:
        message = f"Ausschlussbegriff '{term_text}' gelöscht."

    return templates.TemplateResponse("admin/_partials/_exclude_terms_list.html", {"request": request, 
            "exclude_terms": exclude_terms,
            "success": message,
        }
    )


@app.patch("/admin/exclude-terms/{term_id}/toggle")
async def toggle_exclude_term(
    request: Request,
    term_id: int,
    db: Session = Depends(get_db)
):
    """
    Toggle an exclude term's active state via HTMX request.

    Returns the updated exclude term row partial for HTMX swap.
    """
    term = toggle_exclude_term_active(db, term_id)
    if not term:
        return templates.TemplateResponse("admin/_partials/_exclude_term_row.html", {"request": request, "term": None, "error": "Ausschlussbegriff nicht gefunden."}
        )

    return templates.TemplateResponse("admin/_partials/_exclude_term_row.html", {"request": request, "term": term}
    )


@app.get("/admin/sources")
async def admin_sources(request: Request, db: Session = Depends(get_db)):
    """
    Admin page for managing sources.

    Displays all sources sorted alphabetically with:
    - Active/inactive status toggle
    - Last crawl timestamp
    - Error status if any
    """
    sources = get_all_sources_sorted(db)
    return templates.TemplateResponse("admin/sources.html", {"request": request, 
            "title": "Quellen",
            "sources": sources,
        }
    )


@app.patch("/admin/sources/{source_id}/toggle")
async def toggle_source(
    request: Request,
    source_id: int,
    db: Session = Depends(get_db)
):
    """
    Toggle a source's active state via HTMX request.

    Returns the updated source row partial for HTMX swap.
    """
    source = toggle_source_active(db, source_id)
    if not source:
        return templates.TemplateResponse("admin/_partials/_source_row.html", {"request": request, "source": None, "error": "Quelle nicht gefunden."}
        )

    return templates.TemplateResponse("admin/_partials/_source_row.html", {"request": request, "source": source}
    )


@app.delete("/admin/sources/{source_id}/error")
async def clear_source_error_route(
    request: Request,
    source_id: int,
    db: Session = Depends(get_db)
):
    """
    Clear a source's error state via HTMX request.

    Returns the updated source row partial for HTMX swap.
    """
    source = clear_source_error(db, source_id)
    if not source:
        return templates.TemplateResponse("admin/_partials/_source_row.html", {"request": request, "source": None, "error": "Quelle nicht gefunden."}
        )

    return templates.TemplateResponse("admin/_partials/_source_row.html", {"request": request, "source": source}
    )


@app.patch("/admin/sources/{source_id}/move-up")
async def move_source_up_route(
    request: Request,
    source_id: int,
    db: Session = Depends(get_db)
):
    """
    Move a source up in the crawl order via HTMX request.

    Returns the updated sources list partial for HTMX swap.
    """
    sources = move_source_up(db, source_id)
    return templates.TemplateResponse("admin/_partials/_sources_list.html", {"request": request, "sources": sources}
    )


@app.patch("/admin/sources/{source_id}/move-down")
async def move_source_down_route(
    request: Request,
    source_id: int,
    db: Session = Depends(get_db)
):
    """
    Move a source down in the crawl order via HTMX request.

    Returns the updated sources list partial for HTMX swap.
    """
    sources = move_source_down(db, source_id)
    return templates.TemplateResponse("admin/_partials/_sources_list.html", {"request": request, "sources": sources}
    )


@app.get("/admin/crawl")
async def admin_crawl_status(request: Request, db: Session = Depends(get_db)):
    """
    Admin page for crawl control and status.

    Displays:
    - Current crawl status (running/idle)
    - Last crawl result (if any)
    - Manual crawl trigger button
    - Crawl history (Letzte Crawls tab)
    """
    crawl_state = get_crawl_state()
    crawl_logs = get_crawl_logs(db, limit=50)
    return templates.TemplateResponse("admin/crawl_status.html", {"request": request,
            "title": "Crawl-Status",
            "is_running": crawl_state.is_running,
            "current_source": crawl_state.current_source,
            "last_result": crawl_state.last_result,
            "log_messages": get_crawl_log(),
            "crawl_logs": crawl_logs,
        }
    )


@app.post("/admin/crawl/start")
async def start_crawl(request: Request, db: Session = Depends(get_db)):
    """
    Start a manual crawl via HTMX request.

    Starts the crawl in the background and returns immediately so the UI
    can show the running state with cancel button.
    """
    import asyncio

    # Check if already running
    if is_crawl_running():
        crawl_state = get_crawl_state()
        # Get info about who holds the lock (for cross-process detection)
        lock_holder = get_lock_holder_info()
        if lock_holder:
            error_msg = f"Ein Crawl läuft bereits ({lock_holder})."
        else:
            error_msg = "Ein Crawl läuft bereits."
        crawl_logs = get_crawl_logs(db, limit=50)
        return templates.TemplateResponse("admin/_partials/_crawl_status.html", {"request": request,
                "is_running": True,
                "current_source": crawl_state.current_source,
                "last_result": crawl_state.last_result,
                "log_messages": get_crawl_log(),
                "crawl_logs": crawl_logs,
                "error": error_msg,
            }
        )

    # Check if there are active search terms
    active_terms = get_active_search_terms(db)
    if not active_terms:
        crawl_state = get_crawl_state()
        crawl_logs = get_crawl_logs(db, limit=50)
        return templates.TemplateResponse("admin/_partials/_crawl_status.html", {"request": request,
                "is_running": False,
                "current_source": None,
                "last_result": crawl_state.last_result,
                "log_messages": get_crawl_log(),
                "crawl_logs": crawl_logs,
                "error": "Kein Crawl möglich: Bitte zuerst Suchbegriffe erfassen.",
            }
        )

    # Prepare crawl state BEFORE creating background task to avoid race conditions
    # This ensures polling sees is_running=True immediately
    prepare_crawl_state()

    # Start crawl in background task
    async def run_crawl_background():
        # Create a new database session for the background task
        from backend.database import SessionLocal
        background_db = SessionLocal()
        try:
            # Pass state_prepared=True since we already set up the state
            await run_crawl_async(background_db, state_prepared=True)
        except Exception as e:
            logger.error(f"Background crawl failed: {e}")
        finally:
            background_db.close()

    asyncio.create_task(run_crawl_background())

    # Return immediately with running state
    crawl_state = get_crawl_state()
    crawl_logs = get_crawl_logs(db, limit=50)
    return templates.TemplateResponse("admin/_partials/_crawl_status.html", {"request": request,
            "is_running": crawl_state.is_running,
            "current_source": crawl_state.current_source,
            "last_result": crawl_state.last_result,
            "log_messages": get_crawl_log(),
            "crawl_logs": crawl_logs,
        }
    )


@app.get("/admin/crawl/status")
async def get_crawl_status_partial(request: Request, db: Session = Depends(get_db)):
    """
    Get current crawl status partial for HTMX polling.

    Used for real-time status updates during crawl.
    Includes progress tracking (sources done/total) and ETA estimation.
    """
    crawl_state = get_crawl_state()
    crawl_logs = get_crawl_logs(db, limit=50)

    # Get average crawl duration for ETA calculation
    avg_duration = get_avg_crawl_duration(db, limit=3) if crawl_state.is_running else None

    return templates.TemplateResponse("admin/_partials/_crawl_status.html", {
            "request": request,
            "is_running": crawl_state.is_running,
            "current_source": crawl_state.current_source,
            "last_result": crawl_state.last_result,
            "log_messages": get_crawl_log(),
            "crawl_logs": crawl_logs,
            # Progress tracking
            "sources_total": crawl_state.sources_total,
            "sources_done": crawl_state.sources_done,
            "started_at": crawl_state.started_at.isoformat() if crawl_state.started_at else None,
            "avg_duration": avg_duration,
        }
    )


@app.post("/admin/crawl/cancel")
async def cancel_crawl(request: Request, db: Session = Depends(get_db)):
    """
    Cancel a running crawl via HTMX request.

    Returns the updated status partial for HTMX swap.
    """
    crawl_logs = get_crawl_logs(db, limit=50)
    if not is_crawl_running():
        crawl_state = get_crawl_state()
        return templates.TemplateResponse("admin/_partials/_crawl_status.html", {"request": request,
                "is_running": False,
                "current_source": None,
                "last_result": crawl_state.last_result,
                "crawl_logs": crawl_logs,
                "error": "Kein Crawl läuft.",
            }
        )

    # Request cancellation
    request_crawl_cancel()

    crawl_state = get_crawl_state()
    return templates.TemplateResponse("admin/_partials/_crawl_status.html", {"request": request,
            "is_running": crawl_state.is_running,
            "current_source": crawl_state.current_source,
            "last_result": crawl_state.last_result,
            "crawl_logs": crawl_logs,
            "success": "Abbruch angefordert...",
        }
    )


@app.post("/admin/crawl/clear-db")
async def clear_matches_db(request: Request, db: Session = Depends(get_db)):
    """
    Clear all matches from the database via HTMX request.

    This allows a fresh crawl to reload everything.
    Returns the updated status partial for HTMX swap.
    """
    crawl_logs = get_crawl_logs(db, limit=50)
    if is_crawl_running():
        crawl_state = get_crawl_state()
        return templates.TemplateResponse("admin/_partials/_crawl_status.html", {"request": request,
                "is_running": True,
                "current_source": crawl_state.current_source,
                "last_result": crawl_state.last_result,
                "log_messages": get_crawl_log(),
                "crawl_logs": crawl_logs,
                "error": "Kann Datenbank nicht leeren während ein Crawl läuft.",
            }
        )

    count = clear_all_matches(db)

    crawl_state = get_crawl_state()
    return templates.TemplateResponse("admin/_partials/_crawl_status.html", {"request": request,
            "is_running": False,
            "current_source": None,
            "last_result": crawl_state.last_result,
            "log_messages": get_crawl_log(),
            "crawl_logs": crawl_logs,
            "success": f"Datenbank geleert ({count} Treffer gelöscht).",
        }
    )


# =============================================================================
# Image Proxy API
# =============================================================================


@app.get("/api/fetch-image")
async def fetch_image_from_url(url: str):
    """
    Fetch og:image or first product image from a given URL.

    Used to lazy-load images for listings that don't have images
    (e.g., from sources that are JavaScript SPAs).

    Args:
        url: The URL to fetch the image from

    Returns:
        JSON with image_url if found, or null if not
    """
    import httpx
    import re
    from urllib.parse import urljoin

    if not url:
        return {"image_url": None, "error": "No URL provided"}

    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ImageFetcher/1.0)"}
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text

            # Try og:image first (most reliable for product pages)
            og_match = re.search(
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                html, re.IGNORECASE
            )
            if not og_match:
                # Try alternate format
                og_match = re.search(
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                    html, re.IGNORECASE
                )

            if og_match:
                image_url = og_match.group(1)
                # Make absolute URL if relative
                if not image_url.startswith(('http://', 'https://')):
                    image_url = urljoin(url, image_url)
                return {"image_url": image_url}

            # Try twitter:image
            twitter_match = re.search(
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
                html, re.IGNORECASE
            )
            if twitter_match:
                image_url = twitter_match.group(1)
                if not image_url.startswith(('http://', 'https://')):
                    image_url = urljoin(url, image_url)
                return {"image_url": image_url}

            # Try to find first product image (common patterns)
            # Look for images with common product-related classes or attributes
            img_patterns = [
                # Images with product-related src patterns
                r'<img[^>]+src=["\']([^"\']+(?:product|item|artikel|waffe|gun)[^"\']*\.(?:jpg|jpeg|png|webp))["\']',
                # Images hosted on common image hosts (like postimg for egun.de)
                r'<img[^>]+src=["\'](https?://(?:i\.postimg\.cc|imgur\.com|cloudinary\.com)[^"\']+)["\']',
                # Any image that's not a logo, icon, or tiny
                r'<img[^>]+src=["\']([^"\']+\.(?:jpg|jpeg|png|webp))["\']',
            ]

            for pattern in img_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for img_url in matches:
                    # Skip logos, icons, placeholders
                    lower_url = img_url.lower()
                    if any(skip in lower_url for skip in ['logo', 'icon', 'placeholder', 'avatar', 'favicon', 'sprite', 'banner', 'ad-', 'ads/']):
                        continue
                    # Make absolute URL
                    if not img_url.startswith(('http://', 'https://')):
                        img_url = urljoin(url, img_url)
                    return {"image_url": img_url}

            return {"image_url": None}

    except httpx.TimeoutException:
        logger.warning(f"Timeout fetching image from {url}")
        return {"image_url": None, "error": "Timeout"}
    except Exception as e:
        logger.warning(f"Error fetching image from {url}: {e}")
        return {"image_url": None, "error": str(e)}
