"""
Tests for Alembic database migrations.

Tests verify:
- Configuration files exist and are valid
- Migrations folder structure is correct
- Upgrade creates all expected tables
- Downgrade removes tables
- Schema matches SQLAlchemy model definitions
"""
import os
import tempfile

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from alembic import command
from alembic.config import Config

# Import connection module but NOT models to avoid metadata conflicts during migration tests
from backend.database.connection import PROJECT_ROOT


# Project paths
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"
VERSIONS_DIR = MIGRATIONS_DIR / "versions"


class TestAlembicConfiguration:
    """Tests for Alembic configuration files."""

    def test_alembic_ini_exists(self):
        """alembic.ini should exist at project root."""
        assert ALEMBIC_INI.exists(), f"alembic.ini not found at {ALEMBIC_INI}"

    def test_alembic_ini_has_script_location(self):
        """alembic.ini should have correct script_location."""
        content = ALEMBIC_INI.read_text()
        assert "script_location = migrations" in content

    def test_alembic_ini_has_sqlalchemy_url(self):
        """alembic.ini should have sqlalchemy.url configured."""
        content = ALEMBIC_INI.read_text()
        assert "sqlalchemy.url" in content

    def test_alembic_ini_has_path_separator(self):
        """alembic.ini should have path_separator configured to avoid deprecation warning."""
        content = ALEMBIC_INI.read_text()
        assert "path_separator = os" in content

    def test_migrations_folder_exists(self):
        """migrations folder should exist."""
        assert MIGRATIONS_DIR.exists(), f"migrations folder not found at {MIGRATIONS_DIR}"

    def test_migrations_env_py_exists(self):
        """migrations/env.py should exist."""
        env_py = MIGRATIONS_DIR / "env.py"
        assert env_py.exists(), f"env.py not found at {env_py}"

    def test_migrations_script_mako_exists(self):
        """migrations/script.py.mako should exist."""
        script_mako = MIGRATIONS_DIR / "script.py.mako"
        assert script_mako.exists(), f"script.py.mako not found at {script_mako}"

    def test_versions_folder_exists(self):
        """migrations/versions folder should exist."""
        assert VERSIONS_DIR.exists(), f"versions folder not found at {VERSIONS_DIR}"

    def test_initial_migration_exists(self):
        """Initial migration file should exist in versions folder."""
        migration_files = list(VERSIONS_DIR.glob("*.py"))
        assert len(migration_files) > 0, "No migration files found in versions folder"


class TestEnvPyConfiguration:
    """Tests for migrations/env.py configuration."""

    def test_env_py_imports_base(self):
        """env.py should import Base from connection."""
        env_py = MIGRATIONS_DIR / "env.py"
        content = env_py.read_text()
        assert "from backend.database.connection import Base" in content

    def test_env_py_imports_models(self):
        """env.py should import models to register with metadata."""
        env_py = MIGRATIONS_DIR / "env.py"
        content = env_py.read_text()
        assert "from backend.database import models" in content

    def test_env_py_has_render_as_batch(self):
        """env.py should use render_as_batch=True for SQLite."""
        env_py = MIGRATIONS_DIR / "env.py"
        content = env_py.read_text()
        assert "render_as_batch=True" in content


@pytest.fixture
def temp_db():
    """Create a temporary database for testing migrations."""
    # Create a temporary file for the test database
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # Create engine for the temporary database
    test_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False}
    )

    yield db_path, test_engine

    # Cleanup
    test_engine.dispose()
    if os.path.exists(db_path):
        os.unlink(db_path)
    # Clean up WAL files if they exist
    for suffix in ["-shm", "-wal"]:
        wal_path = db_path + suffix
        if os.path.exists(wal_path):
            os.unlink(wal_path)


class TestMigrationExecution:
    """Tests for migration upgrade and downgrade functionality."""

    def test_upgrade_creates_alembic_version_table(self, temp_db):
        """Running upgrade should create alembic_version table."""
        db_path, test_engine = temp_db

        # Create Alembic config for the test database
        alembic_cfg = Config(str(ALEMBIC_INI))
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

        # Run upgrade
        command.upgrade(alembic_cfg, "head")

        # Verify alembic_version table exists
        inspector = inspect(test_engine)
        tables = inspector.get_table_names()
        assert "alembic_version" in tables

    def test_upgrade_creates_search_terms_table(self, temp_db):
        """Running upgrade should create search_terms table."""
        db_path, test_engine = temp_db

        alembic_cfg = Config(str(ALEMBIC_INI))
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

        command.upgrade(alembic_cfg, "head")

        inspector = inspect(test_engine)
        tables = inspector.get_table_names()
        assert "search_terms" in tables

    def test_upgrade_creates_sources_table(self, temp_db):
        """Running upgrade should create sources table."""
        db_path, test_engine = temp_db

        alembic_cfg = Config(str(ALEMBIC_INI))
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

        command.upgrade(alembic_cfg, "head")

        inspector = inspect(test_engine)
        tables = inspector.get_table_names()
        assert "sources" in tables

    def test_upgrade_creates_matches_table(self, temp_db):
        """Running upgrade should create matches table."""
        db_path, test_engine = temp_db

        alembic_cfg = Config(str(ALEMBIC_INI))
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

        command.upgrade(alembic_cfg, "head")

        inspector = inspect(test_engine)
        tables = inspector.get_table_names()
        assert "matches" in tables

    def test_downgrade_removes_tables(self, temp_db):
        """Running downgrade should remove application tables."""
        db_path, test_engine = temp_db

        alembic_cfg = Config(str(ALEMBIC_INI))
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

        # First upgrade
        command.upgrade(alembic_cfg, "head")

        # Then downgrade
        command.downgrade(alembic_cfg, "base")

        # Verify application tables are removed
        inspector = inspect(test_engine)
        tables = inspector.get_table_names()
        assert "search_terms" not in tables
        assert "sources" not in tables
        assert "matches" not in tables
        # alembic_version should still exist
        assert "alembic_version" in tables


class TestSchemaMatchesModels:
    """Tests that migrated schema matches SQLAlchemy model definitions."""

    @pytest.fixture
    def migrated_db(self):
        """Create and migrate a temporary database."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        test_engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False}
        )

        # Run migrations
        alembic_cfg = Config(str(ALEMBIC_INI))
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
        command.upgrade(alembic_cfg, "head")

        yield test_engine

        # Cleanup
        test_engine.dispose()
        if os.path.exists(db_path):
            os.unlink(db_path)
        for suffix in ["-shm", "-wal"]:
            wal_path = db_path + suffix
            if os.path.exists(wal_path):
                os.unlink(wal_path)

    def test_search_terms_columns_match_model(self, migrated_db):
        """search_terms table columns should match SearchTerm model."""
        inspector = inspect(migrated_db)
        columns = {col['name'] for col in inspector.get_columns('search_terms')}

        expected_columns = {'id', 'created_at', 'updated_at', 'term', 'match_type', 'is_active', 'sort_order', 'hide_seen_matches'}
        assert columns == expected_columns

    def test_sources_columns_match_model(self, migrated_db):
        """sources table columns should match Source model."""
        inspector = inspect(migrated_db)
        columns = {col['name'] for col in inspector.get_columns('sources')}

        expected_columns = {
            'id', 'created_at', 'updated_at', 'name', 'base_url',
            'is_active', 'last_crawl_at', 'last_error', 'sort_order'
        }
        assert columns == expected_columns

    def test_matches_columns_match_model(self, migrated_db):
        """matches table columns should match Match model."""
        inspector = inspect(migrated_db)
        columns = {col['name'] for col in inspector.get_columns('matches')}

        expected_columns = {
            'id', 'created_at', 'updated_at', 'source_id', 'search_term_id',
            'title', 'price', 'url', 'image_url', 'is_new', 'external_id'
        }
        assert columns == expected_columns

    def test_matches_foreign_keys_exist(self, migrated_db):
        """matches table should have foreign keys to sources and search_terms."""
        inspector = inspect(migrated_db)
        fks = inspector.get_foreign_keys('matches')

        # Extract referred tables
        referred_tables = {fk['referred_table'] for fk in fks}
        assert 'sources' in referred_tables
        assert 'search_terms' in referred_tables

    def test_search_terms_has_term_index(self, migrated_db):
        """search_terms should have an index on term column."""
        inspector = inspect(migrated_db)
        indexes = inspector.get_indexes('search_terms')

        # Find index on term column
        term_indexes = [idx for idx in indexes if 'term' in idx['column_names']]
        assert len(term_indexes) > 0, "No index found on term column"

    def test_sources_has_name_index(self, migrated_db):
        """sources should have an index on name column."""
        inspector = inspect(migrated_db)
        indexes = inspector.get_indexes('sources')

        # Find index on name column
        name_indexes = [idx for idx in indexes if 'name' in idx['column_names']]
        assert len(name_indexes) > 0, "No index found on name column"


class TestModelsCrudAfterMigration:
    """Tests that models work correctly with migrated database."""

    @pytest.fixture
    def migrated_session(self):
        """Create a migrated database and return a session."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        test_engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False}
        )

        # Run migrations
        alembic_cfg = Config(str(ALEMBIC_INI))
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
        command.upgrade(alembic_cfg, "head")

        # Create session
        TestSession = sessionmaker(bind=test_engine)
        session = TestSession()

        yield session

        # Cleanup
        session.close()
        test_engine.dispose()
        if os.path.exists(db_path):
            os.unlink(db_path)
        for suffix in ["-shm", "-wal"]:
            wal_path = db_path + suffix
            if os.path.exists(wal_path):
                os.unlink(wal_path)

    def test_can_create_search_term(self, migrated_session):
        """Should be able to create SearchTerm after migration."""
        # Import inside test to avoid metadata conflicts with migration
        from backend.database.models import SearchTerm

        term = SearchTerm(term="Glock 17")
        migrated_session.add(term)
        migrated_session.commit()

        assert term.id is not None
        assert term.term == "Glock 17"

    def test_can_create_source(self, migrated_session):
        """Should be able to create Source after migration."""
        from backend.database.models import Source

        source = Source(name="test-source", base_url="https://example.com")
        migrated_session.add(source)
        migrated_session.commit()

        assert source.id is not None
        assert source.name == "test-source"

    def test_can_create_match_with_relationships(self, migrated_session):
        """Should be able to create Match with relationships after migration."""
        from backend.database.models import SearchTerm, Source, Match

        # Create related objects
        source = Source(name="test-source-match", base_url="https://example.com")
        term = SearchTerm(term="Test Term")
        migrated_session.add(source)
        migrated_session.add(term)
        migrated_session.commit()

        # Create match
        match = Match(
            source_id=source.id,
            search_term_id=term.id,
            title="Test Listing",
            url="https://example.com/listing/1",
        )
        migrated_session.add(match)
        migrated_session.commit()

        assert match.id is not None
        assert match.source_id == source.id
        assert match.search_term_id == term.id
