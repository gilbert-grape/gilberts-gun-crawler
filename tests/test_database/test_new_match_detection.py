"""
Tests for new match detection functionality.

Tests the is_new flag behavior and last_seen_at tracking:
- New matches default to is_new=True
- mark_matches_as_seen() sets is_new=False
- Matches created after marking are still new
- last_seen_at is updated when marking seen
"""
from datetime import datetime, timezone

from backend.database.models import AppSettings, Match
from backend.database.crud import (
    get_app_settings,
    mark_matches_as_seen,
    get_last_seen_at,
    get_new_match_count,
    get_new_matches,
    save_match,
    create_search_term,
    get_or_create_source,
)


class TestAppSettings:
    """Tests for AppSettings CRUD operations."""

    def test_get_app_settings_creates_default(self, test_session):
        """Test that get_app_settings creates default settings if not exists."""
        # Should have no settings initially
        assert test_session.query(AppSettings).count() == 0

        # Get settings - should create default
        settings = get_app_settings(test_session)

        assert settings is not None
        assert settings.id == 1
        assert settings.last_seen_at is None
        assert test_session.query(AppSettings).count() == 1

    def test_get_app_settings_returns_existing(self, test_session):
        """Test that get_app_settings returns existing settings."""
        # Create settings
        now = datetime.now(timezone.utc)
        settings = AppSettings(last_seen_at=now)
        test_session.add(settings)
        test_session.commit()

        # Get settings - should return existing
        retrieved = get_app_settings(test_session)

        assert retrieved.id == settings.id
        # SQLite strips timezone info, so compare without tzinfo
        assert retrieved.last_seen_at.replace(tzinfo=timezone.utc) == now

    def test_get_app_settings_only_one_row(self, test_session):
        """Test that only one AppSettings row exists."""
        # Call multiple times
        get_app_settings(test_session)
        get_app_settings(test_session)
        get_app_settings(test_session)

        # Should still have only one row
        assert test_session.query(AppSettings).count() == 1


class TestNewMatchDefault:
    """Tests for default is_new behavior."""

    def test_new_match_has_is_new_true(self, test_session):
        """Test that new matches have is_new=True by default (AC: 4)."""
        # Create source and search term
        source = get_or_create_source(test_session, "test.ch", "https://test.ch")
        term = create_search_term(test_session, "Glock 17")

        # Create match via save_match
        match_result = {
            "listing": {
                "title": "Glock 17 Gen 5",
                "price": 800.0,
                "image_url": "https://test.ch/img.jpg",
                "link": "https://test.ch/glock17",
                "source": "test.ch"
            },
            "search_term_id": term.id,
            "search_term": "Glock 17",
            "match_type": "exact"
        }
        match = save_match(test_session, match_result, source.id)
        test_session.commit()

        assert match is not None
        assert match.is_new is True

    def test_match_model_default_is_new(self, test_session):
        """Test that Match model has is_new=True as default."""
        source = get_or_create_source(test_session, "test.ch", "https://test.ch")
        term = create_search_term(test_session, "SIG 550")

        # Create match directly
        match = Match(
            source_id=source.id,
            search_term_id=term.id,
            title="SIG 550",
            price="1200",
            url="https://test.ch/sig550",
        )
        test_session.add(match)
        test_session.commit()

        assert match.is_new is True


class TestMarkMatchesAsSeen:
    """Tests for mark_matches_as_seen functionality."""

    def test_mark_matches_as_seen_sets_is_new_false(self, test_session):
        """Test that mark_matches_as_seen sets is_new=False (AC: 3)."""
        # Create source, term, and matches
        source = get_or_create_source(test_session, "test.ch", "https://test.ch")
        term = create_search_term(test_session, "Glock 17")

        match1 = Match(
            source_id=source.id,
            search_term_id=term.id,
            title="Glock 17 Gen 4",
            url="https://test.ch/1",
            is_new=True,
        )
        match2 = Match(
            source_id=source.id,
            search_term_id=term.id,
            title="Glock 17 Gen 5",
            url="https://test.ch/2",
            is_new=True,
        )
        test_session.add_all([match1, match2])
        test_session.commit()

        # Verify both are new
        assert match1.is_new is True
        assert match2.is_new is True

        # Mark as seen
        count = mark_matches_as_seen(test_session)

        # Refresh from database
        test_session.refresh(match1)
        test_session.refresh(match2)

        assert count == 2
        assert match1.is_new is False
        assert match2.is_new is False

    def test_mark_matches_as_seen_updates_last_seen_at(self, test_session):
        """Test that mark_matches_as_seen updates last_seen_at (AC: 1)."""
        # Create a match
        source = get_or_create_source(test_session, "test.ch", "https://test.ch")
        term = create_search_term(test_session, "SIG")
        match = Match(
            source_id=source.id,
            search_term_id=term.id,
            title="SIG P226",
            url="https://test.ch/sig",
        )
        test_session.add(match)
        test_session.commit()

        # Get initial last_seen_at
        initial = get_last_seen_at(test_session)
        assert initial is None

        # Mark as seen
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        mark_matches_as_seen(test_session)
        after = datetime.now(timezone.utc).replace(tzinfo=None)

        # Check last_seen_at was updated
        # SQLite returns naive datetimes, so compare without timezone
        last_seen = get_last_seen_at(test_session)
        assert last_seen is not None
        assert before <= last_seen <= after

    def test_mark_matches_as_seen_returns_count(self, test_session):
        """Test that mark_matches_as_seen returns correct count."""
        source = get_or_create_source(test_session, "test.ch", "https://test.ch")
        term = create_search_term(test_session, "Test")

        # Create 3 new matches
        for i in range(3):
            match = Match(
                source_id=source.id,
                search_term_id=term.id,
                title=f"Test {i}",
                url=f"https://test.ch/{i}",
                is_new=True,
            )
            test_session.add(match)
        test_session.commit()

        count = mark_matches_as_seen(test_session)
        assert count == 3

        # Mark again - should return 0
        count = mark_matches_as_seen(test_session)
        assert count == 0

    def test_mark_matches_as_seen_only_affects_new_matches(self, test_session):
        """Test that mark_matches_as_seen only affects is_new=True matches."""
        source = get_or_create_source(test_session, "test.ch", "https://test.ch")
        term = create_search_term(test_session, "Test")

        # Create mix of new and seen matches
        new_match = Match(
            source_id=source.id,
            search_term_id=term.id,
            title="New Match",
            url="https://test.ch/new",
            is_new=True,
        )
        seen_match = Match(
            source_id=source.id,
            search_term_id=term.id,
            title="Seen Match",
            url="https://test.ch/seen",
            is_new=False,
        )
        test_session.add_all([new_match, seen_match])
        test_session.commit()

        count = mark_matches_as_seen(test_session)
        assert count == 1  # Only the new match was affected


class TestNewMatchesAfterSeen:
    """Tests for new matches created after marking as seen."""

    def test_matches_after_mark_are_new(self, test_session):
        """Test that matches created after mark_matches_as_seen are new (AC: 2)."""
        source = get_or_create_source(test_session, "test.ch", "https://test.ch")
        term = create_search_term(test_session, "Glock")

        # Create initial match
        match1 = Match(
            source_id=source.id,
            search_term_id=term.id,
            title="Glock 17",
            url="https://test.ch/1",
        )
        test_session.add(match1)
        test_session.commit()

        # Mark as seen
        mark_matches_as_seen(test_session)

        # Create new match after marking
        match2 = Match(
            source_id=source.id,
            search_term_id=term.id,
            title="Glock 19",
            url="https://test.ch/2",
        )
        test_session.add(match2)
        test_session.commit()

        # Refresh match1 from database
        test_session.refresh(match1)

        # First match should be seen, second should be new
        assert match1.is_new is False
        assert match2.is_new is True

    def test_save_match_after_mark_is_new(self, test_session):
        """Test that save_match creates new matches after marking."""
        source = get_or_create_source(test_session, "test.ch", "https://test.ch")
        term = create_search_term(test_session, "SIG")

        # Mark as seen (no matches yet, but updates last_seen_at)
        mark_matches_as_seen(test_session)

        # Create match via save_match
        match_result = {
            "listing": {
                "title": "SIG P320",
                "price": 900.0,
                "link": "https://test.ch/sig",
                "source": "test.ch"
            },
            "search_term_id": term.id,
            "search_term": "SIG",
            "match_type": "exact"
        }
        match = save_match(test_session, match_result, source.id)
        test_session.commit()

        assert match.is_new is True


class TestGetNewMatchCount:
    """Tests for get_new_match_count function."""

    def test_get_new_match_count_empty(self, test_session):
        """Test get_new_match_count with no matches."""
        count = get_new_match_count(test_session)
        assert count == 0

    def test_get_new_match_count_all_new(self, test_session):
        """Test get_new_match_count with all new matches."""
        source = get_or_create_source(test_session, "test.ch", "https://test.ch")
        term = create_search_term(test_session, "Test")

        for i in range(5):
            match = Match(
                source_id=source.id,
                search_term_id=term.id,
                title=f"Test {i}",
                url=f"https://test.ch/{i}",
                is_new=True,
            )
            test_session.add(match)
        test_session.commit()

        count = get_new_match_count(test_session)
        assert count == 5

    def test_get_new_match_count_mixed(self, test_session):
        """Test get_new_match_count with mix of new and seen."""
        source = get_or_create_source(test_session, "test.ch", "https://test.ch")
        term = create_search_term(test_session, "Test")

        # Create 3 new and 2 seen
        for i in range(3):
            match = Match(
                source_id=source.id,
                search_term_id=term.id,
                title=f"New {i}",
                url=f"https://test.ch/new{i}",
                is_new=True,
            )
            test_session.add(match)

        for i in range(2):
            match = Match(
                source_id=source.id,
                search_term_id=term.id,
                title=f"Seen {i}",
                url=f"https://test.ch/seen{i}",
                is_new=False,
            )
            test_session.add(match)

        test_session.commit()

        count = get_new_match_count(test_session)
        assert count == 3

    def test_get_new_match_count_after_mark(self, test_session):
        """Test get_new_match_count after mark_matches_as_seen."""
        source = get_or_create_source(test_session, "test.ch", "https://test.ch")
        term = create_search_term(test_session, "Test")

        for i in range(3):
            match = Match(
                source_id=source.id,
                search_term_id=term.id,
                title=f"Test {i}",
                url=f"https://test.ch/{i}",
            )
            test_session.add(match)
        test_session.commit()

        assert get_new_match_count(test_session) == 3

        mark_matches_as_seen(test_session)

        assert get_new_match_count(test_session) == 0


class TestGetLastSeenAt:
    """Tests for get_last_seen_at function."""

    def test_get_last_seen_at_initial_none(self, test_session):
        """Test that initial last_seen_at is None."""
        last_seen = get_last_seen_at(test_session)
        assert last_seen is None

    def test_get_last_seen_at_after_mark(self, test_session):
        """Test last_seen_at is set after mark_matches_as_seen."""
        # SQLite returns naive datetimes, so compare without timezone
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        mark_matches_as_seen(test_session)
        after = datetime.now(timezone.utc).replace(tzinfo=None)

        last_seen = get_last_seen_at(test_session)

        assert last_seen is not None
        assert before <= last_seen <= after

    def test_get_last_seen_at_updates_each_mark(self, test_session):
        """Test that last_seen_at updates on each mark_matches_as_seen call."""
        mark_matches_as_seen(test_session)
        first_seen = get_last_seen_at(test_session)

        # Small delay to ensure timestamp difference
        import time
        time.sleep(0.01)

        mark_matches_as_seen(test_session)
        second_seen = get_last_seen_at(test_session)

        assert second_seen > first_seen


class TestIntegrationWorkflow:
    """Integration tests for typical workflow."""

    def test_full_workflow(self, test_session):
        """Test complete new match detection workflow."""
        source = get_or_create_source(test_session, "waffenboerse.ch", "https://waffenboerse.ch")
        term = create_search_term(test_session, "Glock 17")

        # Step 1: First crawl - create matches
        for i in range(3):
            match_result = {
                "listing": {
                    "title": f"Glock 17 #{i}",
                    "price": 800 + i * 100,
                    "link": f"https://waffenboerse.ch/glock{i}",
                    "source": "waffenboerse.ch"
                },
                "search_term_id": term.id,
                "search_term": "Glock 17",
                "match_type": "exact"
            }
            save_match(test_session, match_result, source.id)
        test_session.commit()

        # All 3 should be new
        assert get_new_match_count(test_session) == 3
        assert len(get_new_matches(test_session)) == 3

        # Step 2: User views dashboard
        mark_matches_as_seen(test_session)

        # No new matches
        assert get_new_match_count(test_session) == 0
        assert len(get_new_matches(test_session)) == 0

        # Step 3: Second crawl - new listings
        for i in range(2):
            match_result = {
                "listing": {
                    "title": f"Glock 17 New #{i}",
                    "price": 1000 + i * 100,
                    "link": f"https://waffenboerse.ch/glocknew{i}",
                    "source": "waffenboerse.ch"
                },
                "search_term_id": term.id,
                "search_term": "Glock 17",
                "match_type": "exact"
            }
            save_match(test_session, match_result, source.id)
        test_session.commit()

        # Only 2 new matches (from second crawl)
        assert get_new_match_count(test_session) == 2
        assert len(get_new_matches(test_session)) == 2

        # Total matches should be 5
        assert test_session.query(Match).count() == 5

    def test_user_never_checked_all_new(self, test_session):
        """Test AC: 4 - if user hasn't checked, all matches are new."""
        source = get_or_create_source(test_session, "test.ch", "https://test.ch")
        term = create_search_term(test_session, "Test")

        # Multiple crawls without user viewing dashboard
        for i in range(10):
            match = Match(
                source_id=source.id,
                search_term_id=term.id,
                title=f"Test {i}",
                url=f"https://test.ch/{i}",
            )
            test_session.add(match)
        test_session.commit()

        # All should be new
        assert get_new_match_count(test_session) == 10
        assert get_last_seen_at(test_session) is None
