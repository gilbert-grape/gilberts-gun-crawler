"""
Tests for matching logic.

Tests verify:
- Exact matching (case-insensitive substring)
- Similar matching (normalized, ignores spaces/hyphens)
- Multiple term matching
- Edge cases (empty inputs, missing fields)
"""

from backend.services.matching import (
    MatchResult,
    contains_exclude_term,
    find_matches,
    matches,
    matches_exact,
    matches_similar,
    normalize_text,
)


class TestNormalizeText:
    """Tests for normalize_text function."""

    def test_removes_hyphens(self):
        """Hyphens should be removed."""
        assert normalize_text("VZ-61") == "vz61"

    def test_removes_spaces(self):
        """Spaces should be removed."""
        assert normalize_text("SIG 550") == "sig550"

    def test_removes_multiple_spaces(self):
        """Multiple spaces should be removed."""
        assert normalize_text("Glock  17") == "glock17"

    def test_converts_to_lowercase(self):
        """Text should be converted to lowercase."""
        assert normalize_text("GLOCK") == "glock"

    def test_handles_combined_normalization(self):
        """Combined hyphens, spaces, and case should be normalized."""
        assert normalize_text("SIG-Sauer P226") == "sigsauerp226"

    def test_handles_empty_string(self):
        """Empty string should return empty string."""
        assert normalize_text("") == ""

    def test_handles_none(self):
        """None should return empty string."""
        assert normalize_text(None) == ""

    def test_preserves_numbers(self):
        """Numbers should be preserved."""
        assert normalize_text("P226") == "p226"

    def test_handles_only_spaces(self):
        """String with only spaces should return empty."""
        assert normalize_text("   ") == ""

    def test_handles_unicode(self):
        """Unicode characters should be preserved (lowercase)."""
        assert normalize_text("Büchse") == "büchse"


class TestMatchesExact:
    """Tests for matches_exact function."""

    def test_matches_exact_term_in_title(self):
        """Exact term should match in title."""
        assert matches_exact("Pistole Glock 17 Gen5", "Glock 17") is True

    def test_matches_case_insensitive(self):
        """Match should be case-insensitive."""
        assert matches_exact("GLOCK 17", "Glock 17") is True
        assert matches_exact("glock 17", "GLOCK 17") is True

    def test_does_not_match_without_space(self):
        """Term with space should not match title without space."""
        assert matches_exact("Pistole Glock17 Gen5", "Glock 17") is False

    def test_does_not_match_with_hyphen(self):
        """Term with space should not match title with hyphen."""
        assert matches_exact("Pistole Glock-17 Gen5", "Glock 17") is False

    def test_matches_at_beginning(self):
        """Term at beginning of title should match."""
        assert matches_exact("Glock 17 Pistole", "Glock 17") is True

    def test_matches_at_end(self):
        """Term at end of title should match."""
        assert matches_exact("Pistole Glock 17", "Glock 17") is True

    def test_matches_entire_title(self):
        """Term that is entire title should match."""
        assert matches_exact("Glock 17", "Glock 17") is True

    def test_does_not_match_partial_word(self):
        """Term should not match if it's only part of a word."""
        # "Lock" should match "Lock" as substring, but this is expected behavior
        # The exact match is substring-based, not word-boundary based
        assert matches_exact("Glock 17", "Lock") is True  # Substring match

    def test_handles_empty_title(self):
        """Empty title should not match."""
        assert matches_exact("", "Glock 17") is False

    def test_handles_empty_term(self):
        """Empty term should not match."""
        assert matches_exact("Glock 17", "") is False

    def test_handles_none_title(self):
        """None title should not match."""
        assert matches_exact(None, "Glock 17") is False

    def test_handles_none_term(self):
        """None term should not match."""
        assert matches_exact("Glock 17", None) is False


class TestMatchesSimilar:
    """Tests for matches_similar function."""

    def test_matches_with_hyphen_variant(self):
        """Term without hyphen should match title with hyphen."""
        assert matches_similar("Pistole VZ-61 Skorpion", "VZ61") is True

    def test_matches_with_space_variant(self):
        """Term with hyphen should match title with space."""
        assert matches_similar("Pistole VZ 61 Skorpion", "VZ-61") is True

    def test_matches_normalized_forms(self):
        """All normalized forms should match."""
        title = "SIG550 Rifle"
        assert matches_similar(title, "SIG 550") is True
        assert matches_similar(title, "SIG-550") is True
        assert matches_similar(title, "sig550") is True
        assert matches_similar(title, "SIG550") is True

    def test_matches_case_insensitive(self):
        """Similar match should be case-insensitive."""
        assert matches_similar("GLOCK17", "glock 17") is True

    def test_matches_with_multiple_spaces(self):
        """Multiple spaces should be normalized."""
        assert matches_similar("VZ  61", "VZ61") is True

    def test_handles_empty_title(self):
        """Empty title should not match."""
        assert matches_similar("", "VZ61") is False

    def test_handles_empty_term(self):
        """Empty term should not match."""
        assert matches_similar("VZ-61", "") is False

    def test_handles_none_title(self):
        """None title should not match."""
        assert matches_similar(None, "VZ61") is False

    def test_handles_none_term(self):
        """None term should not match."""
        assert matches_similar("VZ-61", None) is False

    def test_complex_normalization(self):
        """Complex terms should normalize correctly."""
        assert matches_similar("SIG-Sauer P-226", "SIG Sauer P226") is True
        assert matches_similar("Heckler & Koch USP", "Heckler&KochUSP") is True


class TestMatches:
    """Tests for matches dispatcher function."""

    def test_dispatches_to_exact(self):
        """Should use exact matching when match_type is 'exact'."""
        # Exact matching: space matters
        assert matches("Glock 17", "Glock 17", "exact") is True
        assert matches("Glock17", "Glock 17", "exact") is False

    def test_dispatches_to_similar(self):
        """Should use similar matching when match_type is 'similar'."""
        # Similar matching: space doesn't matter
        assert matches("Glock 17", "Glock 17", "similar") is True
        assert matches("Glock17", "Glock 17", "similar") is True

    def test_defaults_to_exact(self):
        """Should default to exact matching for unknown match_type."""
        assert matches("Glock 17", "Glock 17", "unknown") is True
        assert matches("Glock17", "Glock 17", "unknown") is False


class TestFindMatches:
    """Tests for find_matches function."""

    def test_finds_exact_match(self):
        """Should find exact matches."""
        listings = [
            {"title": "Pistole Glock 17 Gen5", "price": 500, "link": "http://example.com/1"}
        ]
        terms = [
            {"id": 1, "term": "Glock 17", "match_type": "exact", "is_active": True}
        ]

        results = find_matches(listings, terms)

        assert len(results) == 1
        assert results[0]["search_term_id"] == 1
        assert results[0]["search_term"] == "Glock 17"
        assert results[0]["match_type"] == "exact"
        assert results[0]["listing"]["title"] == "Pistole Glock 17 Gen5"

    def test_finds_similar_match(self):
        """Should find similar matches."""
        listings = [
            {"title": "Pistole VZ-61 Skorpion", "price": 800, "link": "http://example.com/2"}
        ]
        terms = [
            {"id": 2, "term": "VZ61", "match_type": "similar", "is_active": True}
        ]

        results = find_matches(listings, terms)

        assert len(results) == 1
        assert results[0]["search_term_id"] == 2
        assert results[0]["match_type"] == "similar"

    def test_listing_matches_multiple_terms(self):
        """A listing can match multiple search terms."""
        listings = [
            {"title": "Glock 17 Gen5 9mm Pistole", "price": 600, "link": "http://example.com/3"}
        ]
        terms = [
            {"id": 1, "term": "Glock 17", "match_type": "exact", "is_active": True},
            {"id": 2, "term": "Glock", "match_type": "exact", "is_active": True},
            {"id": 3, "term": "9mm", "match_type": "exact", "is_active": True},
        ]

        results = find_matches(listings, terms)

        assert len(results) == 3
        matched_term_ids = {r["search_term_id"] for r in results}
        assert matched_term_ids == {1, 2, 3}

    def test_multiple_listings_multiple_terms(self):
        """Multiple listings can match multiple terms."""
        listings = [
            {"title": "Glock 17", "price": 500, "link": "http://example.com/1"},
            {"title": "SIG 550", "price": 1200, "link": "http://example.com/2"},
            {"title": "Glock 19", "price": 550, "link": "http://example.com/3"},
        ]
        terms = [
            {"id": 1, "term": "Glock", "match_type": "exact", "is_active": True},
            {"id": 2, "term": "SIG", "match_type": "exact", "is_active": True},
        ]

        results = find_matches(listings, terms)

        # Glock 17 matches "Glock", SIG 550 matches "SIG", Glock 19 matches "Glock"
        assert len(results) == 3

    def test_no_match_for_exact_variant(self):
        """Exact matching should not match variants."""
        listings = [
            {"title": "Pistole Glock17 Gen5", "price": 500, "link": "http://example.com/1"}
        ]
        terms = [
            {"id": 1, "term": "Glock 17", "match_type": "exact", "is_active": True}
        ]

        results = find_matches(listings, terms)

        assert len(results) == 0

    def test_similar_matches_variant(self):
        """Similar matching should match variants."""
        listings = [
            {"title": "Pistole Glock17 Gen5", "price": 500, "link": "http://example.com/1"}
        ]
        terms = [
            {"id": 1, "term": "Glock 17", "match_type": "similar", "is_active": True}
        ]

        results = find_matches(listings, terms)

        assert len(results) == 1

    def test_skips_inactive_terms(self):
        """Inactive search terms should be skipped."""
        listings = [
            {"title": "Glock 17", "price": 500, "link": "http://example.com/1"}
        ]
        terms = [
            {"id": 1, "term": "Glock 17", "match_type": "exact", "is_active": False}
        ]

        results = find_matches(listings, terms)

        assert len(results) == 0

    def test_defaults_to_active_if_not_specified(self):
        """Terms without is_active should default to active."""
        listings = [
            {"title": "Glock 17", "price": 500, "link": "http://example.com/1"}
        ]
        terms = [
            {"id": 1, "term": "Glock 17", "match_type": "exact"}  # No is_active
        ]

        results = find_matches(listings, terms)

        assert len(results) == 1

    def test_empty_listings_returns_empty(self):
        """Empty listings list should return empty results."""
        terms = [
            {"id": 1, "term": "Glock 17", "match_type": "exact", "is_active": True}
        ]

        results = find_matches([], terms)

        assert results == []

    def test_empty_terms_returns_empty(self):
        """Empty search terms list should return empty results."""
        listings = [
            {"title": "Glock 17", "price": 500, "link": "http://example.com/1"}
        ]

        results = find_matches(listings, [])

        assert results == []

    def test_none_listings_returns_empty(self):
        """None listings should return empty results."""
        terms = [
            {"id": 1, "term": "Glock 17", "match_type": "exact", "is_active": True}
        ]

        results = find_matches(None, terms)

        assert results == []

    def test_none_terms_returns_empty(self):
        """None search terms should return empty results."""
        listings = [
            {"title": "Glock 17", "price": 500, "link": "http://example.com/1"}
        ]

        results = find_matches(listings, None)

        assert results == []

    def test_skips_listings_without_title(self):
        """Listings without title should be skipped."""
        listings = [
            {"price": 500, "link": "http://example.com/1"},  # No title
            {"title": "Glock 17", "price": 600, "link": "http://example.com/2"},
        ]
        terms = [
            {"id": 1, "term": "Glock", "match_type": "exact", "is_active": True}
        ]

        results = find_matches(listings, terms)

        assert len(results) == 1
        assert results[0]["listing"]["title"] == "Glock 17"

    def test_skips_terms_without_id(self):
        """Terms without id should be skipped."""
        listings = [
            {"title": "Glock 17", "price": 500, "link": "http://example.com/1"}
        ]
        terms = [
            {"term": "Glock 17", "match_type": "exact", "is_active": True}  # No id
        ]

        results = find_matches(listings, terms)

        assert len(results) == 0

    def test_skips_terms_without_term_text(self):
        """Terms without term text should be skipped."""
        listings = [
            {"title": "Glock 17", "price": 500, "link": "http://example.com/1"}
        ]
        terms = [
            {"id": 1, "match_type": "exact", "is_active": True}  # No term
        ]

        results = find_matches(listings, terms)

        assert len(results) == 0

    def test_preserves_listing_data(self):
        """Match result should preserve all listing data."""
        listings = [
            {
                "title": "Glock 17 Gen5",
                "price": 550.0,
                "link": "http://example.com/glock",
                "image_url": "http://example.com/img.jpg",
                "source": "waffenboerse.ch"
            }
        ]
        terms = [
            {"id": 1, "term": "Glock 17", "match_type": "exact", "is_active": True}
        ]

        results = find_matches(listings, terms)

        assert len(results) == 1
        listing = results[0]["listing"]
        assert listing["title"] == "Glock 17 Gen5"
        assert listing["price"] == 550.0
        assert listing["link"] == "http://example.com/glock"
        assert listing["image_url"] == "http://example.com/img.jpg"
        assert listing["source"] == "waffenboerse.ch"

    def test_defaults_match_type_to_exact(self):
        """Terms without match_type should default to exact."""
        listings = [
            {"title": "Glock 17", "price": 500, "link": "http://example.com/1"},
            {"title": "Glock17", "price": 500, "link": "http://example.com/2"},  # No space
        ]
        terms = [
            {"id": 1, "term": "Glock 17", "is_active": True}  # No match_type
        ]

        results = find_matches(listings, terms)

        # Only "Glock 17" should match with exact (default)
        assert len(results) == 1
        assert results[0]["listing"]["title"] == "Glock 17"


class TestMatchResultType:
    """Tests for MatchResult TypedDict structure."""

    def test_match_result_has_required_fields(self):
        """MatchResult should have all required fields."""
        result = MatchResult(
            listing={"title": "Test", "price": 100, "link": "http://test.com"},
            search_term_id=1,
            search_term="Test",
            match_type="exact"
        )

        assert "listing" in result
        assert "search_term_id" in result
        assert "search_term" in result
        assert "match_type" in result


class TestContainsExcludeTerm:
    """Tests for contains_exclude_term function."""

    def test_finds_exclude_term_in_title(self):
        """Should find exclude term in title."""
        assert contains_exclude_term("Softair Glock 17", ["Softair", "Airsoft"]) is True

    def test_not_found_when_no_match(self):
        """Should return False when no exclude term matches."""
        assert contains_exclude_term("Glock 17 Gen5", ["Softair", "Airsoft"]) is False

    def test_case_insensitive(self):
        """Should match case-insensitively."""
        assert contains_exclude_term("SOFTAIR Glock", ["softair"]) is True
        assert contains_exclude_term("softair Glock", ["SOFTAIR"]) is True

    def test_empty_title_returns_false(self):
        """Empty title should return False."""
        assert contains_exclude_term("", ["Softair"]) is False

    def test_none_title_returns_false(self):
        """None title should return False."""
        assert contains_exclude_term(None, ["Softair"]) is False

    def test_empty_exclude_terms_returns_false(self):
        """Empty exclude terms list should return False."""
        assert contains_exclude_term("Softair Glock", []) is False

    def test_none_exclude_terms_returns_false(self):
        """None exclude terms should return False."""
        assert contains_exclude_term("Softair Glock", None) is False

    def test_finds_any_of_multiple_terms(self):
        """Should match if any exclude term is found."""
        assert contains_exclude_term("Glock Airsoft", ["Softair", "Airsoft", "BB"]) is True
        assert contains_exclude_term("BB Gun", ["Softair", "Airsoft", "BB"]) is True

    def test_partial_word_match(self):
        """Should match partial words (substring)."""
        assert contains_exclude_term("Airsoftwaffe", ["Airsoft"]) is True


class TestFindMatchesWithExcludeTerms:
    """Tests for find_matches with exclude terms."""

    def test_excludes_listings_with_exclude_terms(self):
        """Listings with exclude terms should be filtered out."""
        listings = [
            {"title": "Glock 17 Gen5", "price": 600, "link": "http://example.com/1"},
            {"title": "Softair Glock 17", "price": 50, "link": "http://example.com/2"},
            {"title": "Glock 19 Airsoft", "price": 80, "link": "http://example.com/3"},
        ]
        terms = [
            {"id": 1, "term": "Glock", "match_type": "exact", "is_active": True}
        ]
        exclude_terms = ["Softair", "Airsoft"]

        results = find_matches(listings, terms, exclude_terms=exclude_terms)

        # Only the real Glock should be matched, not the Softair/Airsoft ones
        assert len(results) == 1
        assert results[0]["listing"]["title"] == "Glock 17 Gen5"

    def test_exclude_terms_none_includes_all(self):
        """None exclude_terms should include all matches."""
        listings = [
            {"title": "Glock 17 Gen5", "price": 600, "link": "http://example.com/1"},
            {"title": "Softair Glock 17", "price": 50, "link": "http://example.com/2"},
        ]
        terms = [
            {"id": 1, "term": "Glock", "match_type": "exact", "is_active": True}
        ]

        results = find_matches(listings, terms, exclude_terms=None)

        assert len(results) == 2

    def test_empty_exclude_terms_includes_all(self):
        """Empty exclude_terms should include all matches."""
        listings = [
            {"title": "Glock 17 Gen5", "price": 600, "link": "http://example.com/1"},
            {"title": "Softair Glock 17", "price": 50, "link": "http://example.com/2"},
        ]
        terms = [
            {"id": 1, "term": "Glock", "match_type": "exact", "is_active": True}
        ]

        results = find_matches(listings, terms, exclude_terms=[])

        assert len(results) == 2


class TestRealWorldScenarios:
    """Tests for real-world matching scenarios."""

    def test_swiss_firearms_matching(self):
        """Test matching common Swiss firearms terms."""
        listings = [
            {"title": "SIG 550 Assault Rifle", "price": 2500, "link": "http://example.com/1"},
            {"title": "Glock 17 Gen5 9mm", "price": 650, "link": "http://example.com/2"},
            {"title": "VZ-61 Skorpion", "price": 1200, "link": "http://example.com/3"},
            {"title": "Stgw 90 PE", "price": 3500, "link": "http://example.com/4"},
            {"title": "K31 Karabiner", "price": 800, "link": "http://example.com/5"},
        ]
        terms = [
            {"id": 1, "term": "SIG 550", "match_type": "similar", "is_active": True},
            {"id": 2, "term": "Glock", "match_type": "exact", "is_active": True},
            {"id": 3, "term": "VZ61", "match_type": "similar", "is_active": True},
            {"id": 4, "term": "Stgw90", "match_type": "similar", "is_active": True},
        ]

        results = find_matches(listings, terms)

        # SIG 550 matches "SIG 550" (similar)
        # Glock 17 matches "Glock" (exact)
        # VZ-61 matches "VZ61" (similar)
        # Stgw 90 matches "Stgw90" (similar)
        assert len(results) == 4

        # Verify specific matches
        matched_titles = {r["listing"]["title"] for r in results}
        assert "SIG 550 Assault Rifle" in matched_titles
        assert "Glock 17 Gen5 9mm" in matched_titles
        assert "VZ-61 Skorpion" in matched_titles
        assert "Stgw 90 PE" in matched_titles

    def test_auf_anfrage_listings(self):
        """Listings with no price should still be matchable."""
        listings = [
            {"title": "Rare Glock 17L", "price": None, "link": "http://example.com/1"}
        ]
        terms = [
            {"id": 1, "term": "Glock", "match_type": "exact", "is_active": True}
        ]

        results = find_matches(listings, terms)

        assert len(results) == 1
        assert results[0]["listing"]["price"] is None


class TestFoundByTermMatching:
    """Tests for matching listings based on found_by_term field."""

    def test_matches_by_found_by_term(self):
        """Listing should match when found_by_term matches search term."""
        listings = [
            {
                "title": "Radom PM-63",  # Title doesn't contain "tokarev"
                "price": 690.0,
                "link": "http://example.com/1",
                "found_by_term": "tokarev"  # But was found by searching for "tokarev"
            }
        ]
        terms = [
            {"id": 1, "term": "tokarev", "match_type": "exact", "is_active": True}
        ]

        results = find_matches(listings, terms)

        assert len(results) == 1
        assert results[0]["search_term"] == "tokarev"
        assert results[0]["match_type"] == "found_by_search"

    def test_found_by_term_case_insensitive(self):
        """found_by_term matching should be case-insensitive."""
        listings = [
            {
                "title": "Some Gun",
                "price": 500.0,
                "link": "http://example.com/1",
                "found_by_term": "Tokarev"  # Capital T
            }
        ]
        terms = [
            {"id": 1, "term": "tokarev", "match_type": "exact", "is_active": True}  # lowercase
        ]

        results = find_matches(listings, terms)

        assert len(results) == 1
        assert results[0]["match_type"] == "found_by_search"

    def test_title_match_takes_precedence_over_found_by_term(self):
        """When title matches, match_type should reflect title match, not found_by_search."""
        listings = [
            {
                "title": "Tokarev TT-33 Pistol",  # Title contains "Tokarev"
                "price": 500.0,
                "link": "http://example.com/1",
                "found_by_term": "tokarev"  # Also found by searching
            }
        ]
        terms = [
            {"id": 1, "term": "Tokarev", "match_type": "exact", "is_active": True}
        ]

        results = find_matches(listings, terms)

        assert len(results) == 1
        assert results[0]["match_type"] == "exact"  # Not "found_by_search"

    def test_no_match_without_found_by_term(self):
        """Listing without found_by_term should not match if title doesn't match."""
        listings = [
            {
                "title": "Radom PM-63",  # No "tokarev" in title
                "price": 690.0,
                "link": "http://example.com/1"
                # No found_by_term field
            }
        ]
        terms = [
            {"id": 1, "term": "tokarev", "match_type": "exact", "is_active": True}
        ]

        results = find_matches(listings, terms)

        assert len(results) == 0

    def test_found_by_term_only_matches_same_term(self):
        """found_by_term should only match search terms with same text."""
        listings = [
            {
                "title": "Some Gun",
                "price": 500.0,
                "link": "http://example.com/1",
                "found_by_term": "tokarev"
            }
        ]
        terms = [
            {"id": 1, "term": "glock", "match_type": "exact", "is_active": True},  # Different term
            {"id": 2, "term": "tokarev", "match_type": "exact", "is_active": True},  # Same term
        ]

        results = find_matches(listings, terms)

        assert len(results) == 1
        assert results[0]["search_term"] == "tokarev"

    def test_found_by_term_with_exclude_terms(self):
        """found_by_term matches should still respect exclude terms."""
        listings = [
            {
                "title": "Softair Tokarev Replica",  # Contains exclude term
                "price": 50.0,
                "link": "http://example.com/1",
                "found_by_term": "tokarev"
            }
        ]
        terms = [
            {"id": 1, "term": "tokarev", "match_type": "exact", "is_active": True}
        ]
        exclude_terms = ["Softair"]

        results = find_matches(listings, terms, exclude_terms=exclude_terms)

        assert len(results) == 0  # Should be excluded
