"""
Tests for SQLAlchemy ORM models.

Tests verify:
- All models can be instantiated
- Table names are plural snake_case
- All models have id, created_at, updated_at columns
- Foreign key columns follow <singular>_id pattern
- Relationships work correctly
"""
import time

import pytest
from sqlalchemy import inspect

from backend.database.models import SearchTerm, Source, Match, TimestampMixin


class TestTableNames:
    """Tests for table naming conventions (plural snake_case)."""

    def test_search_term_table_name(self):
        """SearchTerm table should be 'search_terms' (plural snake_case)."""
        assert SearchTerm.__tablename__ == "search_terms"

    def test_source_table_name(self):
        """Source table should be 'sources' (plural snake_case)."""
        assert Source.__tablename__ == "sources"

    def test_match_table_name(self):
        """Match table should be 'matches' (plural snake_case)."""
        assert Match.__tablename__ == "matches"


class TestTimestampMixin:
    """Tests for TimestampMixin common columns."""

    def test_mixin_has_id_column(self):
        """TimestampMixin should define id column."""
        assert hasattr(TimestampMixin, "id")

    def test_mixin_has_created_at_column(self):
        """TimestampMixin should define created_at column."""
        assert hasattr(TimestampMixin, "created_at")

    def test_mixin_has_updated_at_column(self):
        """TimestampMixin should define updated_at column."""
        assert hasattr(TimestampMixin, "updated_at")


class TestSearchTermModel:
    """Tests for SearchTerm model."""

    def test_model_has_required_columns(self):
        """SearchTerm should have all required columns."""
        mapper = inspect(SearchTerm)
        column_names = [c.key for c in mapper.columns]

        assert "id" in column_names
        assert "created_at" in column_names
        assert "updated_at" in column_names
        assert "term" in column_names
        assert "match_type" in column_names
        assert "is_active" in column_names

    def test_model_can_be_instantiated(self, test_session):
        """SearchTerm should be instantiable with required fields."""
        search_term = SearchTerm(term="Glock 17")
        test_session.add(search_term)
        test_session.commit()

        assert search_term.id is not None
        assert search_term.term == "Glock 17"
        assert search_term.match_type == "exact"  # default
        assert search_term.is_active is True  # default
        assert search_term.created_at is not None
        assert search_term.updated_at is not None

    def test_term_is_unique(self, test_session):
        """SearchTerm.term should be unique."""
        term1 = SearchTerm(term="SIG 550")
        term2 = SearchTerm(term="SIG 550")
        test_session.add(term1)
        test_session.commit()

        test_session.add(term2)
        with pytest.raises(Exception):  # IntegrityError
            test_session.commit()

    def test_updated_at_changes_on_modification(self, test_session):
        """updated_at should change when record is modified."""
        search_term = SearchTerm(term="Update Test")
        test_session.add(search_term)
        test_session.commit()

        original_updated_at = search_term.updated_at

        # Wait a tiny bit to ensure timestamp difference
        time.sleep(0.01)

        # Modify the record
        search_term.match_type = "similar"
        test_session.commit()

        # Refresh to get the updated value from DB
        test_session.refresh(search_term)

        assert search_term.updated_at > original_updated_at

    def test_match_type_constraint(self, test_session):
        """match_type should only allow 'exact' or 'similar'."""
        # Valid values should work
        term_exact = SearchTerm(term="Valid Exact", match_type="exact")
        term_similar = SearchTerm(term="Valid Similar", match_type="similar")
        test_session.add(term_exact)
        test_session.add(term_similar)
        test_session.commit()

        assert term_exact.match_type == "exact"
        assert term_similar.match_type == "similar"

        # Invalid value should fail
        term_invalid = SearchTerm(term="Invalid Type", match_type="invalid")
        test_session.add(term_invalid)
        with pytest.raises(Exception):  # IntegrityError from CheckConstraint
            test_session.commit()


class TestSourceModel:
    """Tests for Source model."""

    def test_model_has_required_columns(self):
        """Source should have all required columns."""
        mapper = inspect(Source)
        column_names = [c.key for c in mapper.columns]

        assert "id" in column_names
        assert "created_at" in column_names
        assert "updated_at" in column_names
        assert "name" in column_names
        assert "base_url" in column_names
        assert "is_active" in column_names
        assert "last_crawl_at" in column_names
        assert "last_error" in column_names

    def test_model_can_be_instantiated(self, test_session):
        """Source should be instantiable with required fields."""
        source = Source(name="waffenboerse.ch", base_url="https://www.waffenboerse.ch")
        test_session.add(source)
        test_session.commit()

        assert source.id is not None
        assert source.name == "waffenboerse.ch"
        assert source.base_url == "https://www.waffenboerse.ch"
        assert source.is_active is True  # default
        assert source.last_crawl_at is None  # nullable
        assert source.last_error is None  # nullable

    def test_name_is_unique(self, test_session):
        """Source.name should be unique."""
        source1 = Source(name="test-source", base_url="https://example.com")
        source2 = Source(name="test-source", base_url="https://example2.com")
        test_session.add(source1)
        test_session.commit()

        test_session.add(source2)
        with pytest.raises(Exception):  # IntegrityError
            test_session.commit()


class TestMatchModel:
    """Tests for Match model."""

    def test_model_has_required_columns(self):
        """Match should have all required columns."""
        mapper = inspect(Match)
        column_names = [c.key for c in mapper.columns]

        assert "id" in column_names
        assert "created_at" in column_names
        assert "updated_at" in column_names
        assert "source_id" in column_names
        assert "search_term_id" in column_names
        assert "title" in column_names
        assert "price" in column_names
        assert "url" in column_names
        assert "image_url" in column_names
        assert "is_new" in column_names
        assert "external_id" in column_names

    def test_foreign_key_naming_pattern(self):
        """Foreign keys should follow <singular>_id pattern."""
        mapper = inspect(Match)
        column_names = [c.key for c in mapper.columns]

        # Should be source_id not sources_id
        assert "source_id" in column_names
        # Should be search_term_id not search_terms_id
        assert "search_term_id" in column_names

    def test_model_can_be_instantiated_with_relationships(self, test_session):
        """Match should be instantiable with foreign key relationships."""
        # Create required related objects
        source = Source(name="test-source-match", base_url="https://example.com")
        search_term = SearchTerm(term="Test Term")
        test_session.add(source)
        test_session.add(search_term)
        test_session.commit()

        # Create match
        match = Match(
            source_id=source.id,
            search_term_id=search_term.id,
            title="Test Listing",
            url="https://example.com/listing/1",
        )
        test_session.add(match)
        test_session.commit()

        assert match.id is not None
        assert match.source_id == source.id
        assert match.search_term_id == search_term.id
        assert match.is_new is True  # default

    def test_relationships_work(self, test_session):
        """Match relationships should allow navigation to Source and SearchTerm."""
        source = Source(name="test-source-rel", base_url="https://example.com")
        search_term = SearchTerm(term="Relationship Test")
        test_session.add(source)
        test_session.add(search_term)
        test_session.commit()

        match = Match(
            source_id=source.id,
            search_term_id=search_term.id,
            title="Relationship Test Listing",
            url="https://example.com/listing/2",
        )
        test_session.add(match)
        test_session.commit()

        # Test relationship navigation
        assert match.source.name == "test-source-rel"
        assert match.search_term.term == "Relationship Test"

        # Test reverse relationship
        assert len(source.matches) == 1
        assert len(search_term.matches) == 1


class TestAllModelsHaveCommonColumns:
    """Verify all models have id, created_at, updated_at."""

    @pytest.mark.parametrize("model_class", [SearchTerm, Source, Match])
    def test_model_has_id_column(self, model_class):
        """All models should have id column."""
        mapper = inspect(model_class)
        column_names = [c.key for c in mapper.columns]
        assert "id" in column_names

    @pytest.mark.parametrize("model_class", [SearchTerm, Source, Match])
    def test_model_has_created_at_column(self, model_class):
        """All models should have created_at column."""
        mapper = inspect(model_class)
        column_names = [c.key for c in mapper.columns]
        assert "created_at" in column_names

    @pytest.mark.parametrize("model_class", [SearchTerm, Source, Match])
    def test_model_has_updated_at_column(self, model_class):
        """All models should have updated_at column."""
        mapper = inspect(model_class)
        column_names = [c.key for c in mapper.columns]
        assert "updated_at" in column_names
