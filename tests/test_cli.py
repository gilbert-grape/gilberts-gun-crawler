"""
Tests for CLI commands (Story 6.4).

Tests the command-line interface for:
- Running crawls via CLI
"""
from unittest.mock import patch, MagicMock

from backend.cli import main, cmd_crawl
from backend.services.crawler import CrawlResult


class TestCLICrawlCommand:
    """Tests for CLI crawl command."""

    @patch("backend.cli.run_crawl_async")
    @patch("backend.cli.SessionLocal")
    @patch("backend.cli.is_crawl_locked", return_value=False)
    def test_crawl_success(self, mock_locked, mock_session_local, mock_run_crawl, capsys):
        """Test successful crawl via CLI."""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        # Mock async function to return a coroutine
        async def mock_crawl(*args, **kwargs):
            return CrawlResult(
                sources_attempted=3,
                sources_succeeded=3,
                sources_failed=0,
                total_listings=100,
                new_matches=10,
                duplicate_matches=5,
                duration_seconds=15.0,
            )
        mock_run_crawl.side_effect = mock_crawl

        # Simulate command line args
        args = MagicMock()
        result = cmd_crawl(args)

        assert result == 0
        mock_run_crawl.assert_called_once()

        # Check output
        captured = capsys.readouterr()
        assert "CRAWL COMPLETE" in captured.out
        assert "Sources attempted: 3" in captured.out
        assert "successfully" in captured.out.lower()

    @patch("backend.cli.run_crawl_async")
    @patch("backend.cli.SessionLocal")
    @patch("backend.cli.is_crawl_locked", return_value=False)
    def test_crawl_partial_failure(self, mock_locked, mock_session_local, mock_run_crawl, capsys):
        """Test crawl with some failures via CLI."""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        async def mock_crawl(*args, **kwargs):
            return CrawlResult(
                sources_attempted=3,
                sources_succeeded=2,
                sources_failed=1,
                failed_sources=["problematic.ch"],
                total_listings=80,
                new_matches=5,
                duration_seconds=20.0,
            )
        mock_run_crawl.side_effect = mock_crawl

        args = MagicMock()
        result = cmd_crawl(args)

        # Partial success still returns 0
        assert result == 0

        captured = capsys.readouterr()
        assert "problematic.ch" in captured.out

    @patch("backend.cli.run_crawl_async")
    @patch("backend.cli.SessionLocal")
    @patch("backend.cli.is_crawl_locked", return_value=False)
    def test_crawl_complete_failure(self, mock_locked, mock_session_local, mock_run_crawl, capsys):
        """Test crawl with all failures via CLI."""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        async def mock_crawl(*args, **kwargs):
            return CrawlResult(
                sources_attempted=2,
                sources_succeeded=0,
                sources_failed=2,
                failed_sources=["a.ch", "b.ch"],
                total_listings=0,
                new_matches=0,
                duration_seconds=5.0,
            )
        mock_run_crawl.side_effect = mock_crawl

        args = MagicMock()
        result = cmd_crawl(args)

        # Complete failure returns 1
        assert result == 1

        captured = capsys.readouterr()
        assert "failed" in captured.out.lower()

    @patch("backend.cli.run_crawl_async")
    @patch("backend.cli.SessionLocal")
    @patch("backend.cli.is_crawl_locked", return_value=False)
    def test_crawl_exception(self, mock_locked, mock_session_local, mock_run_crawl, capsys):
        """Test crawl handling exception via CLI."""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        async def mock_crawl(*args, **kwargs):
            raise Exception("Database error")
        mock_run_crawl.side_effect = mock_crawl

        args = MagicMock()
        result = cmd_crawl(args)

        # Exception returns 1
        assert result == 1

        captured = capsys.readouterr()
        assert "Database error" in captured.err

    @patch("backend.cli.run_crawl_async")
    @patch("backend.cli.SessionLocal")
    @patch("backend.cli.is_crawl_locked", return_value=False)
    def test_crawl_no_sources(self, mock_locked, mock_session_local, mock_run_crawl, capsys):
        """Test crawl with no sources via CLI."""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        async def mock_crawl(*args, **kwargs):
            return CrawlResult(
                sources_attempted=0,
                sources_succeeded=0,
                sources_failed=0,
            )
        mock_run_crawl.side_effect = mock_crawl

        args = MagicMock()
        result = cmd_crawl(args)

        # No sources returns 0 (not a failure)
        assert result == 0

        captured = capsys.readouterr()
        assert "No sources" in captured.out


class TestCLIMain:
    """Tests for CLI main entry point."""

    @patch("sys.argv", ["yoga-helper"])
    def test_main_no_command_shows_help(self, capsys):
        """Test that main with no command shows help."""
        result = main()
        assert result == 0

    @patch("sys.argv", ["yoga-helper", "crawl"])
    @patch("backend.cli.cmd_crawl")
    def test_main_crawl_command(self, mock_cmd_crawl):
        """Test that main routes to crawl command."""
        mock_cmd_crawl.return_value = 0

        result = main()

        assert result == 0
        mock_cmd_crawl.assert_called_once()
