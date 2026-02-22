"""
Tests for dashboard route.

Tests the dashboard page display:
- Dashboard with matches
- Dashboard with no matches (empty state)
- Match count display
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal, Base, engine
from backend.database.models import Match, SearchTerm, Source


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def db_session():
    """Create a fresh database session for each test."""
    # Create all tables
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        # Clean up tables after test
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)


@pytest.fixture
def sample_data(db_session):
    """Create sample data for testing."""
    # Create source
    source = Source(
        name="waffenboerse.ch",
        base_url="https://waffenboerse.ch",
        is_active=True,
    )
    db_session.add(source)

    # Create search term
    term = SearchTerm(
        term="Glock 17",
        match_type="exact",
        is_active=True,
    )
    db_session.add(term)
    db_session.commit()

    # Create matches
    matches = []
    for i in range(3):
        match = Match(
            source_id=source.id,
            search_term_id=term.id,
            title=f"Glock 17 Gen {i + 4}",
            price=f"{800 + i * 100}",
            url=f"https://waffenboerse.ch/glock{i}",
            image_url=f"https://waffenboerse.ch/img{i}.jpg",
            is_new=(i == 0),  # First one is new
        )
        matches.append(match)
        db_session.add(match)

    db_session.commit()

    return {
        "source": source,
        "term": term,
        "matches": matches,
    }


class TestDashboardRoute:
    """Tests for dashboard route."""

    def test_dashboard_returns_200(self, client):
        """Test that dashboard returns 200 status."""
        response = client.get("/")
        assert response.status_code == 200

    def test_dashboard_is_html(self, client):
        """Test that dashboard returns HTML."""
        response = client.get("/")
        assert "text/html" in response.headers["content-type"]

    def test_dashboard_has_title(self, client):
        """Test that dashboard has correct title."""
        response = client.get("/")
        assert "Home" in response.text
        assert "Gilbert's Yoga Helper" in response.text


class TestDashboardEmptyState:
    """Tests for dashboard empty state (AC: 2)."""

    def test_empty_state_shown_when_no_search_terms(self, client):
        """Test that empty state is shown when no search terms configured."""
        response = client.get("/")

        # Should show empty state message for no search terms
        assert "Keine Suchbegriffe" in response.text
        assert "Suchbegriffe verwalten" in response.text

    def test_empty_state_has_search_terms_link(self, client):
        """Test that empty state has link to search terms page."""
        response = client.get("/")
        assert '/admin/search-terms' in response.text


class TestDashboardWithMatches:
    """Tests for dashboard with matches (AC: 1)."""

    def test_matches_displayed(self, client, sample_data):
        """Test that matches are displayed when they exist."""
        response = client.get("/")

        # Should show matches
        assert "Glock 17 Gen 4" in response.text
        assert "Glock 17 Gen 5" in response.text
        assert "Glock 17 Gen 6" in response.text

    def test_match_count_displayed(self, client, sample_data):
        """Test that match count is displayed."""
        response = client.get("/")

        # Should show count in header and in group
        assert "3 Treffer" in response.text

    def test_new_match_count_displayed(self, client, sample_data):
        """Test that new match count is displayed."""
        response = client.get("/")

        # Should show new count (1 match is marked as new)
        assert "1 neue" in response.text

    def test_no_empty_state_when_matches_exist(self, client, sample_data):
        """Test that empty state is not shown when search terms exist."""
        response = client.get("/")

        # Should NOT show empty state for no search terms
        assert "Keine Suchbegriffe" not in response.text

    def test_match_prices_displayed(self, client, sample_data):
        """Test that match prices are displayed."""
        response = client.get("/")

        # Should show prices
        assert "CHF 800" in response.text
        assert "CHF 900" in response.text
        assert "CHF 1000" in response.text

    def test_source_name_displayed(self, client, sample_data):
        """Test that source name is displayed."""
        response = client.get("/")
        assert "waffenboerse.ch" in response.text

    def test_search_term_displayed_as_group_header(self, client, sample_data):
        """Test that search term is displayed as group header."""
        response = client.get("/")
        # Search term should appear as group header
        assert "Glock 17" in response.text


class TestDashboardGrouping:
    """Tests for match grouping by search term (Story 3.4)."""

    def test_matches_grouped_by_search_term(self, client, db_session):
        """Test that matches are grouped under search term headers."""
        # Create two search terms
        term1 = SearchTerm(term="Glock", match_type="exact", is_active=True)
        term2 = SearchTerm(term="SIG", match_type="similar", is_active=True)
        db_session.add_all([term1, term2])

        source = Source(name="test.ch", base_url="https://test.ch", is_active=True)
        db_session.add(source)
        db_session.commit()

        # Create matches for both terms
        match1 = Match(source_id=source.id, search_term_id=term1.id,
                      title="Glock 17", url="https://test.ch/1", is_new=True)
        match2 = Match(source_id=source.id, search_term_id=term2.id,
                      title="SIG P226", url="https://test.ch/2", is_new=False)
        db_session.add_all([match1, match2])
        db_session.commit()

        response = client.get("/")

        # Both group headers should be visible
        assert "Glock" in response.text
        assert "SIG" in response.text
        # Matches should be displayed
        assert "Glock 17" in response.text
        assert "SIG P226" in response.text

    def test_empty_group_shows_message(self, client, db_session):
        """Test that groups with no matches show empty message."""
        # Create search term with no matches
        term = SearchTerm(term="Beretta", match_type="exact", is_active=True)
        db_session.add(term)
        db_session.commit()

        response = client.get("/")

        # Should show the term and empty message
        assert "Beretta" in response.text
        assert 'Keine Treffer für "Beretta"' in response.text

    def test_new_count_shown_per_group(self, client, db_session):
        """Test that new match count is shown for each group."""
        term = SearchTerm(term="CZ", match_type="exact", is_active=True)
        source = Source(name="test.ch", base_url="https://test.ch", is_active=True)
        db_session.add_all([term, source])
        db_session.commit()

        # Create 2 new matches
        for i in range(2):
            match = Match(source_id=source.id, search_term_id=term.id,
                         title=f"CZ 75 #{i}", url=f"https://test.ch/{i}", is_new=True)
            db_session.add(match)
        db_session.commit()

        response = client.get("/")

        # Should show "2 neue" for this group
        assert "2 neue" in response.text

    def test_match_type_badge_shown(self, client, db_session):
        """Test that match type badge is shown in group header."""
        term1 = SearchTerm(term="Exact Term", match_type="exact", is_active=True)
        term2 = SearchTerm(term="Similar Term", match_type="similar", is_active=True)
        db_session.add_all([term1, term2])
        db_session.commit()

        response = client.get("/")

        # Should show match type badges
        assert "exact" in response.text
        assert "similar" in response.text


class TestDashboardPerformance:
    """Tests related to performance (AC: 3)."""

    def test_dashboard_loads_quickly(self, client):
        """Test that dashboard loads in reasonable time.

        Note: <2 seconds requirement is for production. Test verifies
        it completes without timeout.
        """
        import time

        start = time.time()
        response = client.get("/")
        elapsed = time.time() - start

        assert response.status_code == 200
        # Should be very fast in test environment
        assert elapsed < 5.0  # Give some buffer for test environment


class TestDashboardMarkAsSeen:
    """Tests for recent matches display (based on created_at date)."""

    def test_recent_matches_shown_as_new(self, client, sample_data, db_session):
        """Test that recent matches (< 7 days) show as new regardless of views.

        Note: The NEU badge is now based on created_at < 7 days, not is_new flag.
        This means viewing the dashboard does NOT reset the new status.
        """

        # First visit - recent matches should show
        response = client.get("/")
        # All sample_data matches are created "now" so all are recent
        assert "neue" in response.text

        # Second visit - still shows as new (date-based, not view-based)
        response = client.get("/")
        assert "neue" in response.text

    def test_new_badge_shown_for_recent_matches(self, client, sample_data):
        """Test that NEU badge is shown for matches created within 7 days."""
        response = client.get("/")
        # The NEU badge should be visible for recent matches
        assert "NEU" in response.text


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_returns_200(self, client):
        """Test that health check returns 200."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_json(self, client):
        """Test that health check returns JSON."""
        response = client.get("/health")
        assert response.json() == {"status": "healthy"}
