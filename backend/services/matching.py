"""
Matching Logic for Gilbert's Yoga Helper

Provides functions to match scraped listings against user search terms.
Supports two matching modes:
- exact: Case-insensitive substring match (preserves spaces/hyphens)
- similar: Normalized match (ignores spaces, hyphens, case)
"""
import re
import sys
from typing import List, Optional

if sys.version_info >= (3, 8):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict


class MatchResult(TypedDict):
    """Result of matching a listing against a search term.

    Attributes:
        listing: The original scraped listing dict
        search_term_id: Database ID of the matched search term
        search_term: The search term text
        match_type: How the match was made ("exact" or "similar")
    """
    listing: dict
    search_term_id: int
    search_term: str
    match_type: str


def normalize_text(text: str) -> str:
    """
    Normalize text for similar matching.

    Removes hyphens, spaces, and converts to lowercase.
    This allows "VZ61", "VZ-61", "VZ 61" to all normalize to "vz61".

    Args:
        text: Text to normalize

    Returns:
        Normalized text (lowercase, no spaces/hyphens)

    Examples:
        >>> normalize_text("VZ-61")
        'vz61'
        >>> normalize_text("SIG 550")
        'sig550'
        >>> normalize_text("Glock  17")
        'glock17'
    """
    if not text:
        return ""

    # Convert to lowercase
    normalized = text.lower()

    # Remove hyphens and spaces (including multiple spaces)
    normalized = re.sub(r"[-\s]+", "", normalized)

    return normalized


def matches_exact(title: str, term: str) -> bool:
    """
    Check if title contains the exact term (case-insensitive).

    The term must appear exactly as specified (preserving spaces/hyphens).
    This is a case-insensitive substring match.

    Args:
        title: Listing title to search in
        term: Search term to find

    Returns:
        True if term is found in title (case-insensitive)

    Examples:
        >>> matches_exact("Pistole Glock 17 Gen5", "Glock 17")
        True
        >>> matches_exact("Pistole Glock17 Gen5", "Glock 17")
        False
        >>> matches_exact("GLOCK 17", "Glock 17")
        True
    """
    if not title or not term:
        return False

    return term.lower() in title.lower()


def matches_similar(title: str, term: str) -> bool:
    """
    Check if normalized title contains normalized term.

    Both title and term are normalized (lowercase, no spaces/hyphens)
    before comparison. This allows matching variants like:
    - "VZ61", "VZ-61", "VZ 61" all match each other
    - "SIG 550", "SIG-550", "sig550" all match each other

    Args:
        title: Listing title to search in
        term: Search term to find

    Returns:
        True if normalized term is found in normalized title

    Examples:
        >>> matches_similar("Pistole VZ-61 Skorpion", "VZ61")
        True
        >>> matches_similar("Pistole VZ 61 Skorpion", "VZ-61")
        True
        >>> matches_similar("SIG550 Rifle", "SIG 550")
        True
    """
    if not title or not term:
        return False

    normalized_title = normalize_text(title)
    normalized_term = normalize_text(term)

    return normalized_term in normalized_title


def matches(title: str, term: str, match_type: str) -> bool:
    """
    Check if title matches term using specified match type.

    Args:
        title: Listing title to search in
        term: Search term to find
        match_type: "exact" or "similar"

    Returns:
        True if title matches term according to match_type
    """
    if match_type == "similar":
        return matches_similar(title, term)
    else:
        # Default to exact matching
        return matches_exact(title, term)


def contains_exclude_term(title: str, exclude_terms: List[str]) -> bool:
    """
    Check if title contains any of the exclude terms (case-insensitive).

    Args:
        title: Listing title to check
        exclude_terms: List of terms that should exclude the listing

    Returns:
        True if any exclude term is found in the title

    Examples:
        >>> contains_exclude_term("Softair Glock 17", ["Softair", "Airsoft"])
        True
        >>> contains_exclude_term("Glock 17 Gen5", ["Softair", "Airsoft"])
        False
    """
    if not title or not exclude_terms:
        return False

    title_lower = title.lower()
    for term in exclude_terms:
        if term.lower() in title_lower:
            return True
    return False


def find_matches(
    listings: List[dict],
    search_terms: List[dict],
    exclude_terms: Optional[List[str]] = None,
) -> List[MatchResult]:
    """
    Find all matches between listings and search terms.

    Each listing is checked against each active search term.
    A listing can match multiple terms and will produce multiple
    MatchResult entries. Listings containing exclude terms are filtered out.

    Args:
        listings: List of scraped listing dicts with at least 'title' field
        search_terms: List of search term dicts with 'id', 'term', 'match_type',
                     and optionally 'is_active' fields
        exclude_terms: Optional list of terms that exclude a listing if found
                      in its title (case-insensitive)

    Returns:
        List of MatchResult dicts, one for each listing-term match.
        Returns empty list if no matches found or on error.

    Examples:
        >>> listings = [{"title": "Glock 17 Gen5", "price": 500, ...}]
        >>> terms = [{"id": 1, "term": "Glock 17", "match_type": "exact"}]
        >>> results = find_matches(listings, terms)
        >>> len(results)
        1
        >>> results[0]["search_term"]
        'Glock 17'
    """
    results: List[MatchResult] = []

    # Handle empty inputs
    if not listings or not search_terms:
        return results

    # Filter to active search terms only
    active_terms = [
        t for t in search_terms
        if t.get("is_active", True)  # Default to active if not specified
    ]

    if not active_terms:
        return results

    # Normalize exclude_terms to empty list if None
    exclude_list = exclude_terms or []

    for listing in listings:
        title = listing.get("title", "")
        if not title:
            continue

        # Skip listings that contain exclude terms
        if contains_exclude_term(title, exclude_list):
            continue

        # Check if listing was found by a specific search term
        found_by_term = listing.get("found_by_term")

        for term_data in active_terms:
            term_id = term_data.get("id")
            term_text = term_data.get("term", "")
            match_type = term_data.get("match_type", "exact")

            if not term_id or not term_text:
                continue

            # Match if: 1) title matches term, or 2) listing was found by searching for this term
            title_matches = matches(title, term_text, match_type)
            found_by_matches = (
                found_by_term is not None and
                found_by_term.lower() == term_text.lower()
            )

            if title_matches or found_by_matches:
                results.append(MatchResult(
                    listing=listing,
                    search_term_id=term_id,
                    search_term=term_text,
                    match_type="found_by_search" if found_by_matches and not title_matches else match_type
                ))

    return results
