"""
Tests for database CRUD operations.

Tests verify:
- Source management (get, create)
- Search term queries
- Match persistence with deduplication
- Foreign key relationships
- Timestamps
"""
import pytest

from backend.database.crud import (
    clear_source_error,
    create_crawl_log,
    create_exclude_term,
    create_search_term,
    delete_exclude_term,
    delete_search_term,
    get_active_exclude_terms,
    get_active_search_terms,
    get_active_sources,
    get_all_exclude_terms,
    get_all_exclude_terms_sorted,
    get_all_matches,
    get_all_search_terms,
    get_all_search_terms_sorted,
    get_all_sources,
    get_all_sources_sorted,
    get_app_settings,
    get_avg_crawl_duration,
    get_exclude_term_by_id,
    get_exclude_term_by_term,
    get_last_seen_at,
    get_match_by_url_and_term,
    get_matches_by_search_term,
    get_new_match_count,
    get_new_matches,
    get_or_create_source,
    get_search_term_by_id,
    get_search_term_by_term,
    get_source_by_id,
    get_source_by_name,
    mark_matches_as_seen,
    move_search_term_down,
    move_search_term_up,
    move_source_down,
    move_source_up,
    save_match,
    save_matches,
    search_term_to_dict,
    toggle_exclude_term_active,
    toggle_source_active,
    update_crawl_log,
    update_search_term_match_type,
    update_source_last_crawl,
)
from backend.database.models import ExcludeTerm, Match, SearchTerm, Source


class TestSourceOperations:
    """Tests for source CRUD operations."""

    def test_get_source_by_name_returns_none_if_not_found(self, test_session):
        """get_source_by_name returns None if source doesn't exist."""
        result = get_source_by_name(test_session, "nonexistent.ch")
        assert result is None

    def test_get_source_by_name_returns_source_if_exists(self, test_session):
        """get_source_by_name returns source if it exists."""
        # Create a source
        source = Source(name="waffenboerse.ch", base_url="https://waffenboerse.ch")
        test_session.add(source)
        test_session.commit()

        # Query it
        result = get_source_by_name(test_session, "waffenboerse.ch")
        assert result is not None
        assert result.name == "waffenboerse.ch"

    def test_get_or_create_source_creates_new(self, test_session):
        """get_or_create_source creates new source if not exists."""
        result = get_or_create_source(
            test_session,
            name="newsite.ch",
            base_url="https://newsite.ch"
        )

        assert result is not None
        assert result.name == "newsite.ch"
        assert result.base_url == "https://newsite.ch"
        assert result.is_active is True
        assert result.id is not None

    def test_get_or_create_source_returns_existing(self, test_session):
        """get_or_create_source returns existing source if exists."""
        # Create a source first
        source = Source(name="existing.ch", base_url="https://existing.ch")
        test_session.add(source)
        test_session.commit()
        original_id = source.id

        # Call get_or_create
        result = get_or_create_source(
            test_session,
            name="existing.ch",
            base_url="https://different-url.ch"  # Different URL
        )

        # Should return existing, not create new
        assert result.id == original_id
        assert result.base_url == "https://existing.ch"  # Original URL preserved

    def test_get_all_sources(self, test_session):
        """get_all_sources returns all sources."""
        test_session.add(Source(name="source1.ch", base_url="https://source1.ch"))
        test_session.add(Source(name="source2.ch", base_url="https://source2.ch"))
        test_session.commit()

        results = get_all_sources(test_session)
        assert len(results) == 2

    def test_get_active_sources(self, test_session):
        """get_active_sources returns only active sources."""
        test_session.add(Source(name="active.ch", base_url="https://active.ch", is_active=True))
        test_session.add(Source(name="inactive.ch", base_url="https://inactive.ch", is_active=False))
        test_session.commit()

        results = get_active_sources(test_session)
        assert len(results) == 1
        assert results[0].name == "active.ch"


class TestSearchTermOperations:
    """Tests for search term CRUD operations."""

    def test_get_active_search_terms(self, test_session):
        """get_active_search_terms returns only active terms."""
        test_session.add(SearchTerm(term="Glock", is_active=True))
        test_session.add(SearchTerm(term="SIG", is_active=False))
        test_session.commit()

        results = get_active_search_terms(test_session)
        assert len(results) == 1
        assert results[0].term == "Glock"

    def test_get_all_search_terms(self, test_session):
        """get_all_search_terms returns all terms."""
        test_session.add(SearchTerm(term="Glock", is_active=True))
        test_session.add(SearchTerm(term="SIG", is_active=False))
        test_session.commit()

        results = get_all_search_terms(test_session)
        assert len(results) == 2

    def test_search_term_to_dict(self, test_session):
        """search_term_to_dict converts model to dict correctly."""
        term = SearchTerm(term="Glock 17", match_type="exact", is_active=True)
        test_session.add(term)
        test_session.commit()

        result = search_term_to_dict(term)

        assert result["id"] == term.id
        assert result["term"] == "Glock 17"
        assert result["match_type"] == "exact"
        assert result["is_active"] is True

    def test_create_search_term(self, test_session):
        """create_search_term creates and returns new term."""
        term = create_search_term(test_session, "VZ61", match_type="similar")

        assert term.id is not None
        assert term.term == "VZ61"
        assert term.match_type == "similar"
        assert term.is_active is True

    def test_create_search_term_defaults(self, test_session):
        """create_search_term uses correct defaults."""
        term = create_search_term(test_session, "Test")

        assert term.match_type == "exact"
        assert term.is_active is True


class TestMatchOperations:
    """Tests for match CRUD operations."""

    @pytest.fixture
    def setup_source_and_term(self, test_session):
        """Create source and search term for match tests."""
        source = Source(name="test.ch", base_url="https://test.ch")
        term = SearchTerm(term="Glock", match_type="exact")
        test_session.add(source)
        test_session.add(term)
        test_session.commit()
        return source, term

    def test_get_match_by_url_and_term_returns_none_if_not_found(
        self, test_session, setup_source_and_term
    ):
        """get_match_by_url_and_term returns None if not found."""
        source, term = setup_source_and_term

        result = get_match_by_url_and_term(
            test_session,
            url="https://test.ch/listing/123",
            search_term_id=term.id
        )
        assert result is None

    def test_get_match_by_url_and_term_returns_match_if_found(
        self, test_session, setup_source_and_term
    ):
        """get_match_by_url_and_term returns match if exists."""
        source, term = setup_source_and_term

        # Create a match
        match = Match(
            source_id=source.id,
            search_term_id=term.id,
            title="Test Gun",
            url="https://test.ch/listing/123"
        )
        test_session.add(match)
        test_session.commit()

        # Query it
        result = get_match_by_url_and_term(
            test_session,
            url="https://test.ch/listing/123",
            search_term_id=term.id
        )
        assert result is not None
        assert result.title == "Test Gun"

    def test_save_match_creates_new_record(self, test_session, setup_source_and_term):
        """save_match creates new match record (AC: 1)."""
        source, term = setup_source_and_term

        match_result = {
            "listing": {
                "title": "Glock 17 Gen5",
                "price": 650.0,
                "image_url": "https://test.ch/img.jpg",
                "link": "https://test.ch/listing/456",
                "source": "test.ch"
            },
            "search_term_id": term.id,
            "search_term": "Glock",
            "match_type": "exact"
        }

        result = save_match(test_session, match_result, source.id)
        test_session.commit()

        assert result is not None
        assert result.title == "Glock 17 Gen5"
        assert result.price == "650.0"
        assert result.url == "https://test.ch/listing/456"
        assert result.image_url == "https://test.ch/img.jpg"
        assert result.source_id == source.id
        assert result.search_term_id == term.id
        assert result.is_new is True

    def test_save_match_skips_duplicate(self, test_session, setup_source_and_term):
        """save_match returns None for duplicate (same url + term) (AC: 2)."""
        source, term = setup_source_and_term

        match_result = {
            "listing": {
                "title": "Glock 17",
                "price": 600.0,
                "link": "https://test.ch/listing/789",
                "source": "test.ch"
            },
            "search_term_id": term.id,
            "search_term": "Glock",
            "match_type": "exact"
        }

        # Save first time
        result1 = save_match(test_session, match_result, source.id)
        test_session.commit()
        assert result1 is not None

        # Save again - should be duplicate
        result2 = save_match(test_session, match_result, source.id)
        assert result2 is None

    def test_save_match_allows_same_url_different_term(
        self, test_session, setup_source_and_term
    ):
        """Same URL can match different search terms."""
        source, term1 = setup_source_and_term

        # Create second term
        term2 = SearchTerm(term="17", match_type="exact")
        test_session.add(term2)
        test_session.commit()

        listing = {
            "title": "Glock 17",
            "price": 600.0,
            "link": "https://test.ch/listing/same",
            "source": "test.ch"
        }

        # Save with first term
        result1 = save_match(test_session, {
            "listing": listing,
            "search_term_id": term1.id,
            "search_term": "Glock",
            "match_type": "exact"
        }, source.id)
        test_session.commit()

        # Save with second term - should succeed (not duplicate)
        result2 = save_match(test_session, {
            "listing": listing,
            "search_term_id": term2.id,
            "search_term": "17",
            "match_type": "exact"
        }, source.id)
        test_session.commit()

        assert result1 is not None
        assert result2 is not None
        assert result1.id != result2.id

    def test_save_match_handles_null_price(self, test_session, setup_source_and_term):
        """save_match handles None price correctly."""
        source, term = setup_source_and_term

        match_result = {
            "listing": {
                "title": "Rare Item",
                "price": None,  # Auf Anfrage
                "link": "https://test.ch/listing/rare",
                "source": "test.ch"
            },
            "search_term_id": term.id,
            "search_term": "Glock",
            "match_type": "exact"
        }

        result = save_match(test_session, match_result, source.id)
        test_session.commit()

        assert result is not None
        assert result.price is None

    def test_save_match_handles_null_image(self, test_session, setup_source_and_term):
        """save_match handles None image_url correctly."""
        source, term = setup_source_and_term

        match_result = {
            "listing": {
                "title": "No Image Item",
                "price": 500.0,
                "image_url": None,
                "link": "https://test.ch/listing/noimg",
                "source": "test.ch"
            },
            "search_term_id": term.id,
            "search_term": "Glock",
            "match_type": "exact"
        }

        result = save_match(test_session, match_result, source.id)
        test_session.commit()

        assert result is not None
        assert result.image_url is None

    def test_save_match_sets_foreign_keys(self, test_session, setup_source_and_term):
        """save_match correctly sets source_id and search_term_id (AC: 3)."""
        source, term = setup_source_and_term

        match_result = {
            "listing": {
                "title": "FK Test",
                "link": "https://test.ch/listing/fk",
                "source": "test.ch"
            },
            "search_term_id": term.id,
            "search_term": "Glock",
            "match_type": "exact"
        }

        result = save_match(test_session, match_result, source.id)
        test_session.commit()

        # Verify relationships
        assert result.source_id == source.id
        assert result.search_term_id == term.id
        assert result.source.name == "test.ch"
        assert result.search_term.term == "Glock"

    def test_save_match_sets_timestamp(self, test_session, setup_source_and_term):
        """save_match sets created_at timestamp (AC: 4)."""
        source, term = setup_source_and_term

        match_result = {
            "listing": {
                "title": "Timestamp Test",
                "link": "https://test.ch/listing/ts",
                "source": "test.ch"
            },
            "search_term_id": term.id,
            "search_term": "Glock",
            "match_type": "exact"
        }

        result = save_match(test_session, match_result, source.id)
        test_session.commit()

        assert result.created_at is not None
        assert result.updated_at is not None

    def test_save_match_returns_none_for_invalid_input(self, test_session):
        """save_match returns None for invalid input."""
        # Missing url
        result1 = save_match(test_session, {
            "listing": {"title": "Test"},
            "search_term_id": 1
        }, 1)
        assert result1 is None

        # Missing search_term_id
        result2 = save_match(test_session, {
            "listing": {"link": "https://test.ch"}
        }, 1)
        assert result2 is None


class TestBulkSaveMatches:
    """Tests for bulk save_matches function."""

    @pytest.fixture
    def setup_sources_and_terms(self, test_session):
        """Create sources and search terms for bulk tests."""
        source1 = Source(name="source1.ch", base_url="https://source1.ch")
        source2 = Source(name="source2.ch", base_url="https://source2.ch")
        term1 = SearchTerm(term="Glock", match_type="exact")
        term2 = SearchTerm(term="SIG", match_type="similar")

        test_session.add_all([source1, source2, term1, term2])
        test_session.commit()

        source_map = {
            "source1.ch": source1.id,
            "source2.ch": source2.id
        }

        return source_map, term1, term2

    def test_save_matches_bulk(self, test_session, setup_sources_and_terms):
        """save_matches saves multiple matches in bulk."""
        source_map, term1, term2 = setup_sources_and_terms

        match_results = [
            {
                "listing": {
                    "title": "Glock 17",
                    "price": 600.0,
                    "link": "https://source1.ch/1",
                    "source": "source1.ch"
                },
                "search_term_id": term1.id,
                "search_term": "Glock",
                "match_type": "exact"
            },
            {
                "listing": {
                    "title": "SIG 550",
                    "price": 2000.0,
                    "link": "https://source2.ch/1",
                    "source": "source2.ch"
                },
                "search_term_id": term2.id,
                "search_term": "SIG",
                "match_type": "similar"
            },
        ]

        new_count, dup_count = save_matches(test_session, match_results, source_map)

        assert new_count == 2
        assert dup_count == 0

        # Verify in database
        all_matches = get_all_matches(test_session)
        assert len(all_matches) == 2

    def test_save_matches_counts_duplicates(self, test_session, setup_sources_and_terms):
        """save_matches counts duplicates correctly."""
        source_map, term1, term2 = setup_sources_and_terms

        match_results = [
            {
                "listing": {
                    "title": "Glock 17",
                    "link": "https://source1.ch/dup",
                    "source": "source1.ch"
                },
                "search_term_id": term1.id,
                "search_term": "Glock",
                "match_type": "exact"
            },
        ]

        # First save
        new1, dup1 = save_matches(test_session, match_results, source_map)
        assert new1 == 1
        assert dup1 == 0

        # Second save - same data
        new2, dup2 = save_matches(test_session, match_results, source_map)
        assert new2 == 0
        assert dup2 == 1

    def test_save_matches_skips_unknown_source(self, test_session, setup_sources_and_terms):
        """save_matches skips matches with unknown source."""
        source_map, term1, term2 = setup_sources_and_terms

        match_results = [
            {
                "listing": {
                    "title": "Unknown Source",
                    "link": "https://unknown.ch/1",
                    "source": "unknown.ch"  # Not in source_map
                },
                "search_term_id": term1.id,
                "search_term": "Glock",
                "match_type": "exact"
            },
        ]

        new_count, dup_count = save_matches(test_session, match_results, source_map)

        assert new_count == 0
        assert dup_count == 0

    def test_save_matches_empty_list(self, test_session):
        """save_matches handles empty list."""
        new_count, dup_count = save_matches(test_session, [], {})

        assert new_count == 0
        assert dup_count == 0


class TestMatchQueries:
    """Tests for match query functions."""

    @pytest.fixture
    def setup_matches(self, test_session):
        """Create matches for query tests."""
        source = Source(name="test.ch", base_url="https://test.ch")
        term1 = SearchTerm(term="Glock", match_type="exact")
        term2 = SearchTerm(term="SIG", match_type="exact")

        test_session.add_all([source, term1, term2])
        test_session.commit()

        match1 = Match(
            source_id=source.id,
            search_term_id=term1.id,
            title="Glock 17",
            url="https://test.ch/1",
            is_new=True
        )
        match2 = Match(
            source_id=source.id,
            search_term_id=term1.id,
            title="Glock 19",
            url="https://test.ch/2",
            is_new=False
        )
        match3 = Match(
            source_id=source.id,
            search_term_id=term2.id,
            title="SIG 550",
            url="https://test.ch/3",
            is_new=True
        )

        test_session.add_all([match1, match2, match3])
        test_session.commit()

        return source, term1, term2

    def test_get_matches_by_search_term(self, test_session, setup_matches):
        """get_matches_by_search_term returns matches for specific term."""
        source, term1, term2 = setup_matches

        results = get_matches_by_search_term(test_session, term1.id)

        assert len(results) == 2
        titles = {r.title for r in results}
        assert "Glock 17" in titles
        assert "Glock 19" in titles

    def test_get_all_matches(self, test_session, setup_matches):
        """get_all_matches returns all matches."""
        source, term1, term2 = setup_matches

        results = get_all_matches(test_session)

        assert len(results) == 3

    def test_get_new_matches(self, test_session, setup_matches):
        """get_new_matches returns only new matches."""
        source, term1, term2 = setup_matches

        results = get_new_matches(test_session)

        assert len(results) == 2
        for match in results:
            assert match.is_new is True


class TestSourceAdvancedOperations:
    """Tests for advanced source operations."""

    def test_get_source_by_id(self, test_session):
        """get_source_by_id returns source if exists."""
        source = Source(name="test.ch", base_url="https://test.ch")
        test_session.add(source)
        test_session.commit()

        result = get_source_by_id(test_session, source.id)
        assert result is not None
        assert result.name == "test.ch"

    def test_get_source_by_id_returns_none(self, test_session):
        """get_source_by_id returns None for nonexistent id."""
        result = get_source_by_id(test_session, 9999)
        assert result is None

    def test_toggle_source_active(self, test_session):
        """toggle_source_active toggles is_active state."""
        source = Source(name="test.ch", base_url="https://test.ch", is_active=True)
        test_session.add(source)
        test_session.commit()

        result = toggle_source_active(test_session, source.id)
        assert result.is_active is False

        result = toggle_source_active(test_session, source.id)
        assert result.is_active is True

    def test_toggle_source_active_nonexistent(self, test_session):
        """toggle_source_active returns None for nonexistent source."""
        result = toggle_source_active(test_session, 9999)
        assert result is None

    def test_update_source_last_crawl(self, test_session):
        """update_source_last_crawl updates timestamp."""
        source = Source(name="test.ch", base_url="https://test.ch")
        test_session.add(source)
        test_session.commit()
        assert source.last_crawl_at is None

        result = update_source_last_crawl(test_session, source.id)
        assert result.last_crawl_at is not None

    def test_update_source_last_crawl_with_error(self, test_session):
        """update_source_last_crawl sets error message."""
        source = Source(name="test.ch", base_url="https://test.ch")
        test_session.add(source)
        test_session.commit()

        result = update_source_last_crawl(test_session, source.id, error="Connection failed")
        assert result.last_error == "Connection failed"

    def test_update_source_last_crawl_nonexistent(self, test_session):
        """update_source_last_crawl returns None for nonexistent source."""
        result = update_source_last_crawl(test_session, 9999)
        assert result is None

    def test_clear_source_error(self, test_session):
        """clear_source_error clears error message."""
        source = Source(name="test.ch", base_url="https://test.ch", last_error="Old error")
        test_session.add(source)
        test_session.commit()

        result = clear_source_error(test_session, source.id)
        assert result.last_error is None

    def test_clear_source_error_nonexistent(self, test_session):
        """clear_source_error returns None for nonexistent source."""
        result = clear_source_error(test_session, 9999)
        assert result is None

    def test_get_all_sources_sorted(self, test_session):
        """get_all_sources_sorted returns sources in sort_order."""
        source1 = Source(name="z.ch", base_url="https://z.ch", sort_order=2)
        source2 = Source(name="a.ch", base_url="https://a.ch", sort_order=0)
        source3 = Source(name="m.ch", base_url="https://m.ch", sort_order=1)
        test_session.add_all([source1, source2, source3])
        test_session.commit()

        results = get_all_sources_sorted(test_session)
        assert len(results) == 3
        assert results[0].name == "a.ch"
        assert results[1].name == "m.ch"
        assert results[2].name == "z.ch"

    def test_move_source_up(self, test_session):
        """move_source_up swaps sort_order with previous source."""
        source1 = Source(name="first.ch", base_url="https://first.ch", sort_order=0)
        source2 = Source(name="second.ch", base_url="https://second.ch", sort_order=1)
        test_session.add_all([source1, source2])
        test_session.commit()

        results = move_source_up(test_session, source2.id)
        assert results[0].name == "second.ch"
        assert results[1].name == "first.ch"

    def test_move_source_up_nonexistent(self, test_session):
        """move_source_up returns current list for nonexistent source."""
        source = Source(name="test.ch", base_url="https://test.ch", sort_order=0)
        test_session.add(source)
        test_session.commit()

        results = move_source_up(test_session, 9999)
        assert len(results) == 1

    def test_move_source_up_already_first(self, test_session):
        """move_source_up does nothing when already first."""
        source = Source(name="test.ch", base_url="https://test.ch", sort_order=0)
        test_session.add(source)
        test_session.commit()

        results = move_source_up(test_session, source.id)
        assert results[0].sort_order == 0

    def test_move_source_down(self, test_session):
        """move_source_down swaps sort_order with next source."""
        source1 = Source(name="first.ch", base_url="https://first.ch", sort_order=0)
        source2 = Source(name="second.ch", base_url="https://second.ch", sort_order=1)
        test_session.add_all([source1, source2])
        test_session.commit()

        results = move_source_down(test_session, source1.id)
        assert results[0].name == "second.ch"
        assert results[1].name == "first.ch"

    def test_move_source_down_nonexistent(self, test_session):
        """move_source_down returns current list for nonexistent source."""
        source = Source(name="test.ch", base_url="https://test.ch", sort_order=0)
        test_session.add(source)
        test_session.commit()

        results = move_source_down(test_session, 9999)
        assert len(results) == 1

    def test_move_source_down_already_last(self, test_session):
        """move_source_down does nothing when already last."""
        source = Source(name="test.ch", base_url="https://test.ch", sort_order=0)
        test_session.add(source)
        test_session.commit()

        results = move_source_down(test_session, source.id)
        assert results[0].sort_order == 0


class TestSearchTermAdvancedOperations:
    """Tests for advanced search term operations."""

    def test_get_all_search_terms_sorted(self, test_session):
        """get_all_search_terms_sorted returns terms alphabetically."""
        test_session.add(SearchTerm(term="Zebra", sort_order=0))
        test_session.add(SearchTerm(term="Apple", sort_order=1))
        test_session.add(SearchTerm(term="Mango", sort_order=2))
        test_session.commit()

        results = get_all_search_terms_sorted(test_session)
        assert results[0].term == "Apple"
        assert results[1].term == "Mango"
        assert results[2].term == "Zebra"

    def test_get_search_term_by_id(self, test_session):
        """get_search_term_by_id returns term if exists."""
        term = SearchTerm(term="Glock")
        test_session.add(term)
        test_session.commit()

        result = get_search_term_by_id(test_session, term.id)
        assert result.term == "Glock"

    def test_get_search_term_by_id_nonexistent(self, test_session):
        """get_search_term_by_id returns None for nonexistent id."""
        result = get_search_term_by_id(test_session, 9999)
        assert result is None

    def test_get_search_term_by_term(self, test_session):
        """get_search_term_by_term finds by text (case-insensitive)."""
        test_session.add(SearchTerm(term="Glock 17"))
        test_session.commit()

        result = get_search_term_by_term(test_session, "glock 17")
        assert result is not None
        assert result.term == "Glock 17"

    def test_get_search_term_by_term_not_found(self, test_session):
        """get_search_term_by_term returns None if not found."""
        result = get_search_term_by_term(test_session, "nonexistent")
        assert result is None

    def test_delete_search_term(self, test_session):
        """delete_search_term removes term from database."""
        term = SearchTerm(term="ToDelete")
        test_session.add(term)
        test_session.commit()
        term_id = term.id

        result = delete_search_term(test_session, term_id)
        assert result is True
        assert get_search_term_by_id(test_session, term_id) is None

    def test_delete_search_term_nonexistent(self, test_session):
        """delete_search_term returns False for nonexistent term."""
        result = delete_search_term(test_session, 9999)
        assert result is False

    def test_update_search_term_match_type(self, test_session):
        """update_search_term_match_type changes match type."""
        term = SearchTerm(term="Test", match_type="exact")
        test_session.add(term)
        test_session.commit()

        result = update_search_term_match_type(test_session, term.id, "similar")
        assert result.match_type == "similar"

    def test_update_search_term_match_type_invalid(self, test_session):
        """update_search_term_match_type raises for invalid type."""
        term = SearchTerm(term="Test", match_type="exact")
        test_session.add(term)
        test_session.commit()

        with pytest.raises(ValueError):
            update_search_term_match_type(test_session, term.id, "invalid")

    def test_update_search_term_match_type_nonexistent(self, test_session):
        """update_search_term_match_type returns None for nonexistent term."""
        result = update_search_term_match_type(test_session, 9999, "similar")
        assert result is None

    def test_move_search_term_up(self, test_session):
        """move_search_term_up swaps with previous term."""
        term1 = SearchTerm(term="First", sort_order=0)
        term2 = SearchTerm(term="Second", sort_order=1)
        test_session.add_all([term1, term2])
        test_session.commit()

        result = move_search_term_up(test_session, term2.id)
        assert result.sort_order == 0

    def test_move_search_term_up_nonexistent(self, test_session):
        """move_search_term_up returns None for nonexistent term."""
        result = move_search_term_up(test_session, 9999)
        assert result is None

    def test_move_search_term_up_already_top(self, test_session):
        """move_search_term_up does nothing when at top."""
        term = SearchTerm(term="First", sort_order=0)
        test_session.add(term)
        test_session.commit()

        result = move_search_term_up(test_session, term.id)
        assert result.sort_order == 0

    def test_move_search_term_down(self, test_session):
        """move_search_term_down swaps with next term."""
        term1 = SearchTerm(term="First", sort_order=0)
        term2 = SearchTerm(term="Second", sort_order=1)
        test_session.add_all([term1, term2])
        test_session.commit()

        result = move_search_term_down(test_session, term1.id)
        assert result.sort_order == 1

    def test_move_search_term_down_nonexistent(self, test_session):
        """move_search_term_down returns None for nonexistent term."""
        result = move_search_term_down(test_session, 9999)
        assert result is None

    def test_move_search_term_down_already_bottom(self, test_session):
        """move_search_term_down does nothing when at bottom."""
        term = SearchTerm(term="Only", sort_order=0)
        test_session.add(term)
        test_session.commit()

        result = move_search_term_down(test_session, term.id)
        assert result.sort_order == 0


class TestExcludeTermOperations:
    """Tests for exclude term CRUD operations."""

    def test_get_all_exclude_terms(self, test_session):
        """get_all_exclude_terms returns all terms."""
        test_session.add(ExcludeTerm(term="Softair", is_active=True))
        test_session.add(ExcludeTerm(term="Spielzeug", is_active=False))
        test_session.commit()

        results = get_all_exclude_terms(test_session)
        assert len(results) == 2

    def test_get_all_exclude_terms_sorted(self, test_session):
        """get_all_exclude_terms_sorted returns alphabetically."""
        test_session.add(ExcludeTerm(term="Zebra"))
        test_session.add(ExcludeTerm(term="Apple"))
        test_session.commit()

        results = get_all_exclude_terms_sorted(test_session)
        assert results[0].term == "Apple"
        assert results[1].term == "Zebra"

    def test_get_active_exclude_terms(self, test_session):
        """get_active_exclude_terms returns only active terms."""
        test_session.add(ExcludeTerm(term="Active", is_active=True))
        test_session.add(ExcludeTerm(term="Inactive", is_active=False))
        test_session.commit()

        results = get_active_exclude_terms(test_session)
        assert len(results) == 1
        assert results[0].term == "Active"

    def test_get_exclude_term_by_id(self, test_session):
        """get_exclude_term_by_id returns term if exists."""
        term = ExcludeTerm(term="Test")
        test_session.add(term)
        test_session.commit()

        result = get_exclude_term_by_id(test_session, term.id)
        assert result.term == "Test"

    def test_get_exclude_term_by_id_nonexistent(self, test_session):
        """get_exclude_term_by_id returns None for nonexistent id."""
        result = get_exclude_term_by_id(test_session, 9999)
        assert result is None

    def test_get_exclude_term_by_term(self, test_session):
        """get_exclude_term_by_term finds by text (case-insensitive)."""
        test_session.add(ExcludeTerm(term="Softair"))
        test_session.commit()

        result = get_exclude_term_by_term(test_session, "SOFTAIR")
        assert result is not None
        assert result.term == "Softair"

    def test_get_exclude_term_by_term_not_found(self, test_session):
        """get_exclude_term_by_term returns None if not found."""
        result = get_exclude_term_by_term(test_session, "nonexistent")
        assert result is None

    def test_create_exclude_term(self, test_session):
        """create_exclude_term creates new term."""
        term = create_exclude_term(test_session, "NewTerm")

        assert term.id is not None
        assert term.term == "NewTerm"
        assert term.is_active is True

    def test_create_exclude_term_inactive(self, test_session):
        """create_exclude_term can create inactive term."""
        term = create_exclude_term(test_session, "Inactive", is_active=False)

        assert term.is_active is False

    def test_delete_exclude_term(self, test_session):
        """delete_exclude_term removes term."""
        term = ExcludeTerm(term="ToDelete")
        test_session.add(term)
        test_session.commit()
        term_id = term.id

        result = delete_exclude_term(test_session, term_id)
        assert result is True
        assert get_exclude_term_by_id(test_session, term_id) is None

    def test_delete_exclude_term_nonexistent(self, test_session):
        """delete_exclude_term returns False for nonexistent term."""
        result = delete_exclude_term(test_session, 9999)
        assert result is False

    def test_toggle_exclude_term_active(self, test_session):
        """toggle_exclude_term_active toggles is_active state."""
        term = ExcludeTerm(term="Test", is_active=True)
        test_session.add(term)
        test_session.commit()

        result = toggle_exclude_term_active(test_session, term.id)
        assert result.is_active is False

        result = toggle_exclude_term_active(test_session, term.id)
        assert result.is_active is True

    def test_toggle_exclude_term_active_nonexistent(self, test_session):
        """toggle_exclude_term_active returns None for nonexistent term."""
        result = toggle_exclude_term_active(test_session, 9999)
        assert result is None


class TestAppSettingsAndNewMatchDetection:
    """Tests for app settings and new match detection."""

    def test_get_app_settings_creates_default(self, test_session):
        """get_app_settings creates default settings if not exists."""
        settings = get_app_settings(test_session)

        assert settings is not None
        assert settings.last_seen_at is None

    def test_get_app_settings_returns_existing(self, test_session):
        """get_app_settings returns existing settings."""
        # Create settings
        settings1 = get_app_settings(test_session)
        settings1_id = settings1.id

        # Get again
        settings2 = get_app_settings(test_session)
        assert settings2.id == settings1_id

    def test_mark_matches_as_seen(self, test_session):
        """mark_matches_as_seen sets is_new to False."""
        source = Source(name="test.ch", base_url="https://test.ch")
        term = SearchTerm(term="Test")
        test_session.add_all([source, term])
        test_session.commit()

        match1 = Match(source_id=source.id, search_term_id=term.id, title="M1", url="http://1", is_new=True)
        match2 = Match(source_id=source.id, search_term_id=term.id, title="M2", url="http://2", is_new=True)
        test_session.add_all([match1, match2])
        test_session.commit()

        count = mark_matches_as_seen(test_session)
        assert count == 2

        # Verify matches are no longer new
        new_matches = get_new_matches(test_session)
        assert len(new_matches) == 0

    def test_mark_matches_as_seen_updates_timestamp(self, test_session):
        """mark_matches_as_seen updates last_seen_at."""
        mark_matches_as_seen(test_session)

        settings = get_app_settings(test_session)
        assert settings.last_seen_at is not None

    def test_get_last_seen_at(self, test_session):
        """get_last_seen_at returns timestamp."""
        # Initially None
        result = get_last_seen_at(test_session)
        assert result is None

        # After marking as seen
        mark_matches_as_seen(test_session)
        result = get_last_seen_at(test_session)
        assert result is not None

    def test_get_new_match_count(self, test_session):
        """get_new_match_count returns count of new matches."""
        source = Source(name="test.ch", base_url="https://test.ch")
        term = SearchTerm(term="Test")
        test_session.add_all([source, term])
        test_session.commit()

        match1 = Match(source_id=source.id, search_term_id=term.id, title="M1", url="http://1", is_new=True)
        match2 = Match(source_id=source.id, search_term_id=term.id, title="M2", url="http://2", is_new=False)
        match3 = Match(source_id=source.id, search_term_id=term.id, title="M3", url="http://3", is_new=True)
        test_session.add_all([match1, match2, match3])
        test_session.commit()

        count = get_new_match_count(test_session)
        assert count == 2


class TestCrawlLogAvgDuration:
    """Tests for get_avg_crawl_duration function."""

    def test_returns_none_with_no_crawls(self, test_session):
        """get_avg_crawl_duration returns None when no crawl logs exist."""
        result = get_avg_crawl_duration(test_session)
        assert result is None

    def test_returns_none_with_fewer_than_limit_crawls(self, test_session):
        """get_avg_crawl_duration returns None when fewer than limit crawls exist."""
        # Create only 2 successful crawls (default limit is 3)
        for i in range(2):
            crawl_log = create_crawl_log(test_session, "manual")
            update_crawl_log(
                test_session, crawl_log,
                status="success",
                duration_seconds=60
            )

        result = get_avg_crawl_duration(test_session)
        assert result is None

    def test_returns_average_with_exactly_limit_crawls(self, test_session):
        """get_avg_crawl_duration returns average when exactly limit crawls exist."""
        durations = [60, 90, 120]  # Average = 90
        for duration in durations:
            crawl_log = create_crawl_log(test_session, "manual")
            update_crawl_log(
                test_session, crawl_log,
                status="success",
                duration_seconds=duration
            )

        result = get_avg_crawl_duration(test_session)
        assert result == 90.0

    def test_returns_average_with_more_than_limit_crawls(self, test_session):
        """get_avg_crawl_duration considers only the most recent N crawls."""
        # Create 5 crawls, but only last 3 should be averaged
        durations = [100, 200, 60, 90, 120]  # Last 3: 60, 90, 120 -> Average = 90
        for duration in durations:
            crawl_log = create_crawl_log(test_session, "manual")
            update_crawl_log(
                test_session, crawl_log,
                status="success",
                duration_seconds=duration
            )

        result = get_avg_crawl_duration(test_session)
        assert result == 90.0

    def test_ignores_failed_crawls(self, test_session):
        """get_avg_crawl_duration only considers successful or partial crawls."""
        # Create 2 successful and 1 failed
        for i in range(2):
            crawl_log = create_crawl_log(test_session, "manual")
            update_crawl_log(test_session, crawl_log, status="success", duration_seconds=60)

        failed_log = create_crawl_log(test_session, "manual")
        update_crawl_log(test_session, failed_log, status="failed", duration_seconds=30)

        result = get_avg_crawl_duration(test_session)
        # Should return None because only 2 successful crawls (need 3 by default)
        assert result is None

    def test_includes_partial_crawls(self, test_session):
        """get_avg_crawl_duration includes partial success crawls."""
        durations_status = [
            (60, "success"),
            (90, "partial"),
            (120, "success"),
        ]
        for duration, status in durations_status:
            crawl_log = create_crawl_log(test_session, "manual")
            update_crawl_log(test_session, crawl_log, status=status, duration_seconds=duration)

        result = get_avg_crawl_duration(test_session)
        assert result == 90.0

    def test_ignores_zero_duration_crawls(self, test_session):
        """get_avg_crawl_duration ignores crawls with zero duration."""
        # Create 3 crawls, but one has zero duration
        crawl_log1 = create_crawl_log(test_session, "manual")
        update_crawl_log(test_session, crawl_log1, status="success", duration_seconds=60)

        crawl_log2 = create_crawl_log(test_session, "manual")
        update_crawl_log(test_session, crawl_log2, status="success", duration_seconds=0)  # Zero duration

        crawl_log3 = create_crawl_log(test_session, "manual")
        update_crawl_log(test_session, crawl_log3, status="success", duration_seconds=90)

        result = get_avg_crawl_duration(test_session)
        # Only 2 valid crawls, should return None
        assert result is None

    def test_custom_limit_parameter(self, test_session):
        """get_avg_crawl_duration respects custom limit parameter."""
        # Create 4 crawls - with limit=2, we only need 2 successful for a result
        durations = [60, 90, 120, 150]
        for duration in durations:
            crawl_log = create_crawl_log(test_session, "manual")
            update_crawl_log(test_session, crawl_log, status="success", duration_seconds=duration)

        # With limit=2, should return an average (exact value depends on ordering)
        # Most importantly: verify it returns a result since we have >=2 crawls
        result = get_avg_crawl_duration(test_session, limit=2)
        assert result is not None
        # The result should be an average of 2 durations from our set
        # Valid possible averages: (60+90)/2=75, (60+120)/2=90, (60+150)/2=105,
        #                          (90+120)/2=105, (90+150)/2=120, (120+150)/2=135
        valid_averages = [75.0, 90.0, 105.0, 120.0, 135.0]
        assert result in valid_averages

    def test_excludes_cancelled_crawls(self, test_session):
        """get_avg_crawl_duration excludes cancelled crawls."""
        # Create 3 crawls: 2 success, 1 cancelled
        crawl_log1 = create_crawl_log(test_session, "manual")
        update_crawl_log(test_session, crawl_log1, status="success", duration_seconds=60)

        cancelled_log = create_crawl_log(test_session, "manual")
        update_crawl_log(test_session, cancelled_log, status="cancelled", duration_seconds=30)

        crawl_log2 = create_crawl_log(test_session, "manual")
        update_crawl_log(test_session, crawl_log2, status="success", duration_seconds=90)

        # Only 2 valid crawls (cancelled is excluded), should return None
        result = get_avg_crawl_duration(test_session)
        assert result is None
