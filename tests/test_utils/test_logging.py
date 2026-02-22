"""
Tests for logging configuration with rotation.

Tests verify:
- Log file is created in logs/ directory
- Log format matches specification: {timestamp} - {level} - {source} - {message}
- Log rotation occurs at configured size
- Oldest backup is deleted when max reached
- Different log levels work correctly
"""
import logging
import re
from unittest.mock import patch, MagicMock

import pytest


class TestLoggingSetup:
    """Tests for setup_logging() function."""

    @pytest.fixture
    def temp_log_dir(self, tmp_path):
        """Create a temporary log directory."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        return log_dir

    @pytest.fixture
    def mock_settings(self, temp_log_dir):
        """Create mock settings for testing."""
        mock = MagicMock()
        mock.LOG_LEVEL = "DEBUG"
        mock.LOG_FILE = str(temp_log_dir / "test.log")
        mock.LOG_MAX_SIZE = 1024  # 1KB for easy rotation testing
        mock.LOG_BACKUP_COUNT = 3
        mock.DEBUG = False
        return mock

    def test_creates_log_file(self, mock_settings, temp_log_dir):
        """setup_logging should create log file in configured directory."""
        from backend.utils import logging as log_module

        with patch.object(log_module, "settings", mock_settings):
            # Clear any existing handlers
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            # Log something to ensure file is created
            logger = logging.getLogger("test")
            logger.info("Test message")

            log_file = temp_log_dir / "test.log"
            assert log_file.exists(), f"Log file should exist at {log_file}"

    def test_log_format_matches_specification(self, mock_settings, temp_log_dir):
        """Log format should be: {timestamp} - {level} - {source} - {message}."""
        from backend.utils import logging as log_module

        with patch.object(log_module, "settings", mock_settings):
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            logger = logging.getLogger("test.module")
            logger.info("Test message content")

            log_file = temp_log_dir / "test.log"
            content = log_file.read_text()

            # Format: 2026-01-22 08:00:01 - INFO - test.module - Test message content
            pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} - \w+ - [\w.]+ - .+"
            assert re.search(pattern, content), f"Log format doesn't match. Got: {content}"

    def test_log_format_timestamp_format(self, mock_settings, temp_log_dir):
        """Timestamp should be in YYYY-MM-DD HH:MM:SS format."""
        from backend.utils import logging as log_module

        with patch.object(log_module, "settings", mock_settings):
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            logger = logging.getLogger("test")
            logger.info("Test")

            log_file = temp_log_dir / "test.log"
            content = log_file.read_text()

            # Check timestamp format
            pattern = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
            for line in content.splitlines():
                if line.strip():
                    assert re.match(pattern, line), f"Invalid timestamp format in: {line}"

    def test_log_rotation_occurs_at_max_size(self, mock_settings, temp_log_dir):
        """Log should rotate when file exceeds maxBytes."""
        from backend.utils import logging as log_module

        # Use small max size for quick rotation
        mock_settings.LOG_MAX_SIZE = 500  # 500 bytes

        with patch.object(log_module, "settings", mock_settings):
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            logger = logging.getLogger("test")

            # Write enough to trigger rotation (more than 500 bytes)
            for i in range(50):
                logger.info(f"This is a test message number {i} with some padding to fill up the log file quickly")

            log_file = temp_log_dir / "test.log"
            backup_file = temp_log_dir / "test.log.1"

            assert log_file.exists(), "Main log file should exist"
            assert backup_file.exists(), "Backup log file should exist after rotation"

    def test_oldest_backup_deleted_when_max_reached(self, mock_settings, temp_log_dir):
        """Oldest backup should be deleted when backupCount is exceeded."""
        from backend.utils import logging as log_module

        # Use small max size and 2 backups for quick testing
        mock_settings.LOG_MAX_SIZE = 300  # 300 bytes
        mock_settings.LOG_BACKUP_COUNT = 2

        with patch.object(log_module, "settings", mock_settings):
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            logger = logging.getLogger("test")

            # Write enough to trigger multiple rotations
            for i in range(100):
                logger.info(f"Test message {i} with padding to fill the log file and trigger rotations quickly")

            log_file = temp_log_dir / "test.log"
            backup_1 = temp_log_dir / "test.log.1"
            backup_2 = temp_log_dir / "test.log.2"
            backup_3 = temp_log_dir / "test.log.3"

            assert log_file.exists(), "Main log file should exist"
            assert backup_1.exists(), "Backup 1 should exist"
            assert backup_2.exists(), "Backup 2 should exist"
            assert not backup_3.exists(), "Backup 3 should NOT exist (max 2 backups)"


class TestLogLevels:
    """Tests for different log levels."""

    @pytest.fixture
    def temp_log_dir(self, tmp_path):
        """Create a temporary log directory."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        return log_dir

    @pytest.fixture
    def mock_settings(self, temp_log_dir):
        """Create mock settings for testing."""
        mock = MagicMock()
        mock.LOG_FILE = str(temp_log_dir / "test.log")
        mock.LOG_MAX_SIZE = 5 * 1024 * 1024
        mock.LOG_BACKUP_COUNT = 3
        mock.DEBUG = False
        return mock

    def test_debug_level_logs_all(self, mock_settings, temp_log_dir):
        """DEBUG level should log all messages."""
        from backend.utils import logging as log_module

        mock_settings.LOG_LEVEL = "DEBUG"

        with patch.object(log_module, "settings", mock_settings):
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            logger = logging.getLogger("test")
            logger.debug("Debug message")
            logger.info("Info message")
            logger.warning("Warning message")
            logger.error("Error message")

            log_file = temp_log_dir / "test.log"
            content = log_file.read_text()

            assert "Debug message" in content
            assert "Info message" in content
            assert "Warning message" in content
            assert "Error message" in content

    def test_info_level_excludes_debug(self, mock_settings, temp_log_dir):
        """INFO level should exclude DEBUG messages."""
        from backend.utils import logging as log_module

        mock_settings.LOG_LEVEL = "INFO"

        with patch.object(log_module, "settings", mock_settings):
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            logger = logging.getLogger("test")
            logger.debug("Debug message")
            logger.info("Info message")
            logger.warning("Warning message")
            logger.error("Error message")

            log_file = temp_log_dir / "test.log"
            content = log_file.read_text()

            assert "Debug message" not in content
            assert "Info message" in content
            assert "Warning message" in content
            assert "Error message" in content

    def test_warning_level_excludes_info_and_debug(self, mock_settings, temp_log_dir):
        """WARNING level should exclude INFO and DEBUG messages."""
        from backend.utils import logging as log_module

        mock_settings.LOG_LEVEL = "WARNING"

        with patch.object(log_module, "settings", mock_settings):
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            logger = logging.getLogger("test")
            logger.debug("Debug message")
            logger.info("Info message")
            logger.warning("Warning message")
            logger.error("Error message")

            log_file = temp_log_dir / "test.log"
            content = log_file.read_text()

            assert "Debug message" not in content
            assert "Info message" not in content
            assert "Warning message" in content
            assert "Error message" in content

    def test_error_level_only_logs_errors(self, mock_settings, temp_log_dir):
        """ERROR level should only log ERROR messages."""
        from backend.utils import logging as log_module

        mock_settings.LOG_LEVEL = "ERROR"

        with patch.object(log_module, "settings", mock_settings):
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            logger = logging.getLogger("test")
            logger.debug("Debug message")
            logger.info("Info message")
            logger.warning("Warning message")
            logger.error("Error message")

            log_file = temp_log_dir / "test.log"
            content = log_file.read_text()

            assert "Debug message" not in content
            assert "Info message" not in content
            assert "Warning message" not in content
            assert "Error message" in content

    def test_invalid_log_level_falls_back_to_info(self, mock_settings, temp_log_dir, capsys):
        """Invalid LOG_LEVEL should fall back to INFO and print warning."""
        from backend.utils import logging as log_module

        mock_settings.LOG_LEVEL = "INVALID_LEVEL"

        with patch.object(log_module, "settings", mock_settings):
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            # Check warning was printed
            captured = capsys.readouterr()
            assert "Invalid LOG_LEVEL" in captured.out
            assert "INVALID_LEVEL" in captured.out
            assert "Falling back to INFO" in captured.out

            # Verify INFO level is used (DEBUG excluded, INFO included)
            logger = logging.getLogger("test")
            logger.debug("Debug message")
            logger.info("Info message")

            log_file = temp_log_dir / "test.log"
            content = log_file.read_text()

            assert "Debug message" not in content
            assert "Info message" in content


class TestConsoleHandler:
    """Tests for console handler in DEBUG mode."""

    @pytest.fixture
    def temp_log_dir(self, tmp_path):
        """Create a temporary log directory."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        return log_dir

    @pytest.fixture
    def mock_settings(self, temp_log_dir):
        """Create mock settings for testing."""
        mock = MagicMock()
        mock.LOG_LEVEL = "DEBUG"
        mock.LOG_FILE = str(temp_log_dir / "test.log")
        mock.LOG_MAX_SIZE = 5 * 1024 * 1024
        mock.LOG_BACKUP_COUNT = 3
        return mock

    def test_console_handler_added_in_debug_mode(self, mock_settings):
        """Console handler should be added when DEBUG=True."""
        from backend.utils import logging as log_module
        import sys

        mock_settings.DEBUG = True

        with patch.object(log_module, "settings", mock_settings):
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            # Check for StreamHandler to stdout
            stream_handlers = [
                h for h in root_logger.handlers
                if isinstance(h, logging.StreamHandler) and h.stream == sys.stdout
            ]
            assert len(stream_handlers) == 1, "Should have one console handler in DEBUG mode"

    def test_no_console_handler_in_production(self, mock_settings):
        """Console handler should NOT be added when DEBUG=False."""
        from backend.utils import logging as log_module
        import sys

        mock_settings.DEBUG = False

        with patch.object(log_module, "settings", mock_settings):
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            # Check for StreamHandler to stdout
            stream_handlers = [
                h for h in root_logger.handlers
                if isinstance(h, logging.StreamHandler) and h.stream == sys.stdout
            ]
            assert len(stream_handlers) == 0, "Should have no console handler when not in DEBUG mode"


class TestGetLogger:
    """Tests for get_logger() function."""

    def test_returns_logger_with_given_name(self):
        """get_logger should return a logger with the specified name."""
        from backend.utils.logging import get_logger

        logger = get_logger("my.test.module")
        assert logger.name == "my.test.module"

    def test_returns_same_logger_for_same_name(self):
        """get_logger should return the same logger instance for the same name."""
        from backend.utils.logging import get_logger

        logger1 = get_logger("same.name")
        logger2 = get_logger("same.name")
        assert logger1 is logger2


class TestJournaldIntegration:
    """Tests for journald/systemd integration."""

    @pytest.fixture
    def temp_log_dir(self, tmp_path):
        """Create a temporary log directory."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        return log_dir

    @pytest.fixture
    def mock_settings(self, temp_log_dir):
        """Create mock settings for testing."""
        mock = MagicMock()
        mock.LOG_LEVEL = "INFO"
        mock.LOG_FILE = str(temp_log_dir / "test.log")
        mock.LOG_MAX_SIZE = 5 * 1024 * 1024
        mock.LOG_BACKUP_COUNT = 3
        mock.DEBUG = False
        return mock

    def test_console_handler_added_when_use_journald_true(self, mock_settings):
        """Console handler should be added when USE_JOURNALD=true."""
        from backend.utils import logging as log_module
        import sys
        import os

        with patch.object(log_module, "settings", mock_settings), \
             patch.dict(os.environ, {"USE_JOURNALD": "true"}):
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            # Check for StreamHandler to stdout
            stream_handlers = [
                h for h in root_logger.handlers
                if isinstance(h, logging.StreamHandler) and h.stream == sys.stdout
            ]
            assert len(stream_handlers) == 1, "Should have console handler when USE_JOURNALD=true"

    def test_journald_format_used_when_enabled(self, mock_settings):
        """Simplified format without timestamp should be used for journald."""
        from backend.utils import logging as log_module
        import sys
        import os

        with patch.object(log_module, "settings", mock_settings), \
             patch.dict(os.environ, {"USE_JOURNALD": "1"}):
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            # Find the console handler and check its formatter
            stream_handlers = [
                h for h in root_logger.handlers
                if isinstance(h, logging.StreamHandler) and h.stream == sys.stdout
            ]
            assert len(stream_handlers) == 1

            handler = stream_handlers[0]
            # Journald format doesn't include timestamp (asctime)
            format_str = handler.formatter._fmt
            assert "%(asctime)s" not in format_str, "Journald format should not include timestamp"
            assert "%(levelname)s" in format_str, "Journald format should include level"

    def test_no_journald_when_env_false(self, mock_settings):
        """Console handler should NOT be added when USE_JOURNALD is not set."""
        from backend.utils import logging as log_module
        import sys
        import os

        # Ensure USE_JOURNALD is not set
        env = {k: v for k, v in os.environ.items() if k != "USE_JOURNALD"}

        with patch.object(log_module, "settings", mock_settings), \
             patch.dict(os.environ, env, clear=True):
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            # Check for StreamHandler to stdout
            stream_handlers = [
                h for h in root_logger.handlers
                if isinstance(h, logging.StreamHandler) and h.stream == sys.stdout
            ]
            assert len(stream_handlers) == 0, "Should have no console handler when USE_JOURNALD not set"


class TestLogDirectory:
    """Tests for log directory creation."""

    def test_creates_logs_directory_if_not_exists(self, tmp_path):
        """setup_logging should create logs directory if it doesn't exist."""
        from backend.utils import logging as log_module

        log_dir = tmp_path / "nonexistent_logs"
        log_file = log_dir / "app.log"

        mock_settings = MagicMock()
        mock_settings.LOG_LEVEL = "INFO"
        mock_settings.LOG_FILE = str(log_file)
        mock_settings.LOG_MAX_SIZE = 5 * 1024 * 1024
        mock_settings.LOG_BACKUP_COUNT = 3
        mock_settings.DEBUG = False

        with patch.object(log_module, "settings", mock_settings):
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            assert log_dir.exists(), "Log directory should be created"
            logger = logging.getLogger("test")
            logger.info("Test")
            assert log_file.exists(), "Log file should be created"

    def test_handles_absolute_log_path(self, tmp_path):
        """setup_logging should handle absolute log file paths."""
        from backend.utils import logging as log_module

        log_file = tmp_path / "absolute_logs" / "app.log"

        mock_settings = MagicMock()
        mock_settings.LOG_LEVEL = "INFO"
        mock_settings.LOG_FILE = str(log_file)
        mock_settings.LOG_MAX_SIZE = 5 * 1024 * 1024
        mock_settings.LOG_BACKUP_COUNT = 3
        mock_settings.DEBUG = False

        with patch.object(log_module, "settings", mock_settings):
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            log_module.setup_logging()

            logger = logging.getLogger("test")
            logger.info("Test with absolute path")

            assert log_file.exists(), "Log file should be created at absolute path"
