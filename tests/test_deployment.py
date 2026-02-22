"""
Tests for deployment configuration (Epic 7).

Tests the deployment configuration files:
- 7.1: Systemd service configuration
- 7.2: Cron configuration
- 7.3: Database backup script
- 7.4: Logging configuration
- 7.5: Deployment documentation
"""
from pathlib import Path


# Get project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestSystemdService:
    """Tests for Story 7.1: Systemd Service Configuration."""

    def test_service_file_exists(self):
        """Test that systemd service file exists."""
        service_file = PROJECT_ROOT / "deploy" / "yoga-helper.service"
        assert service_file.exists(), "Systemd service file should exist"

    def test_service_file_has_required_sections(self):
        """Test that service file has required systemd sections."""
        service_file = PROJECT_ROOT / "deploy" / "yoga-helper.service"
        content = service_file.read_text()

        assert "[Unit]" in content, "Should have [Unit] section"
        assert "[Service]" in content, "Should have [Service] section"
        assert "[Install]" in content, "Should have [Install] section"

    def test_service_has_restart_policy(self):
        """Test that service has restart configuration."""
        service_file = PROJECT_ROOT / "deploy" / "yoga-helper.service"
        content = service_file.read_text()

        assert "Restart=" in content, "Should have Restart directive"

    def test_service_has_exec_start(self):
        """Test that service has ExecStart configuration."""
        service_file = PROJECT_ROOT / "deploy" / "yoga-helper.service"
        content = service_file.read_text()

        assert "ExecStart=" in content, "Should have ExecStart directive"
        assert "uvicorn" in content, "Should start uvicorn"

    def test_service_has_journald_env(self):
        """Test that service has USE_JOURNALD environment variable."""
        service_file = PROJECT_ROOT / "deploy" / "yoga-helper.service"
        content = service_file.read_text()

        assert "USE_JOURNALD=true" in content, "Should enable journald logging"


class TestCronConfiguration:
    """Tests for Story 7.2: Cron Configuration."""

    def test_daily_crawl_cron_exists(self):
        """Test that daily crawl cron file exists."""
        cron_file = PROJECT_ROOT / "deploy" / "cron-daily-crawl"
        assert cron_file.exists(), "Daily crawl cron file should exist"

    def test_daily_crawl_has_schedule(self):
        """Test that daily crawl has cron schedule."""
        cron_file = PROJECT_ROOT / "deploy" / "cron-daily-crawl"
        content = cron_file.read_text()

        # Should have 5-field cron schedule starting with time
        assert "0 6 * * *" in content or "* * *" in content, "Should have cron schedule"

    def test_daily_crawl_runs_cli_command(self):
        """Test that daily crawl runs the CLI crawl command."""
        cron_file = PROJECT_ROOT / "deploy" / "cron-daily-crawl"
        content = cron_file.read_text()

        assert "backend.cli" in content or "crawl" in content, "Should run crawl command"


class TestDatabaseBackup:
    """Tests for Story 7.3: Database Backup Configuration."""

    def test_backup_script_exists(self):
        """Test that backup script exists."""
        backup_script = PROJECT_ROOT / "deploy" / "backup-database.sh"
        assert backup_script.exists(), "Backup script should exist"

    def test_backup_script_is_bash(self):
        """Test that backup script has bash shebang."""
        backup_script = PROJECT_ROOT / "deploy" / "backup-database.sh"
        content = backup_script.read_text()

        assert content.startswith("#!/bin/bash"), "Should be bash script"

    def test_backup_script_has_rotation(self):
        """Test that backup script implements rotation."""
        backup_script = PROJECT_ROOT / "deploy" / "backup-database.sh"
        content = backup_script.read_text()

        assert "MAX_BACKUPS" in content, "Should have max backups configuration"

    def test_backup_script_has_timestamp(self):
        """Test that backup script uses timestamp in filename."""
        backup_script = PROJECT_ROOT / "deploy" / "backup-database.sh"
        content = backup_script.read_text()

        assert "TIMESTAMP" in content, "Should use timestamp for backup filename"

    def test_weekly_backup_cron_exists(self):
        """Test that weekly backup cron file exists."""
        cron_file = PROJECT_ROOT / "deploy" / "cron-weekly-backup"
        assert cron_file.exists(), "Weekly backup cron file should exist"


class TestLoggingConfiguration:
    """Tests for Story 7.4: Production Logging Configuration."""

    def test_logging_module_exists(self):
        """Test that logging module exists."""
        logging_module = PROJECT_ROOT / "backend" / "utils" / "logging.py"
        assert logging_module.exists(), "Logging module should exist"

    def test_logging_has_rotation(self):
        """Test that logging supports rotation."""
        logging_module = PROJECT_ROOT / "backend" / "utils" / "logging.py"
        content = logging_module.read_text()

        assert "RotatingFileHandler" in content, "Should use rotating file handler"

    def test_logging_has_journald_support(self):
        """Test that logging supports journald integration."""
        logging_module = PROJECT_ROOT / "backend" / "utils" / "logging.py"
        content = logging_module.read_text()

        assert "USE_JOURNALD" in content, "Should support journald env var"
        assert "JOURNALD_FORMAT" in content, "Should have journald format"

    def test_logging_get_logger_function(self):
        """Test that get_logger function works."""
        from backend.utils.logging import get_logger

        logger = get_logger("test_module")
        assert logger is not None
        assert logger.name == "test_module"


class TestDeploymentDocumentation:
    """Tests for Story 7.5: Deployment Documentation."""

    def test_deployment_doc_exists(self):
        """Test that deployment documentation exists."""
        deployment_doc = PROJECT_ROOT / "DEPLOYMENT.md"
        assert deployment_doc.exists(), "DEPLOYMENT.md should exist"

    def test_deployment_doc_has_prerequisites(self):
        """Test that documentation has prerequisites section."""
        deployment_doc = PROJECT_ROOT / "DEPLOYMENT.md"
        content = deployment_doc.read_text()

        assert "Prerequisites" in content or "prerequisite" in content.lower(), \
            "Should have prerequisites section"

    def test_deployment_doc_has_installation(self):
        """Test that documentation has installation instructions."""
        deployment_doc = PROJECT_ROOT / "DEPLOYMENT.md"
        content = deployment_doc.read_text()

        assert "Installation" in content or "install" in content.lower(), \
            "Should have installation section"

    def test_deployment_doc_has_systemd_instructions(self):
        """Test that documentation has systemd setup instructions."""
        deployment_doc = PROJECT_ROOT / "DEPLOYMENT.md"
        content = deployment_doc.read_text()

        assert "systemctl" in content, "Should have systemctl commands"
        assert "systemd" in content.lower(), "Should mention systemd"

    def test_deployment_doc_has_troubleshooting(self):
        """Test that documentation has troubleshooting section."""
        deployment_doc = PROJECT_ROOT / "DEPLOYMENT.md"
        content = deployment_doc.read_text()

        assert "Troubleshooting" in content or "troubleshoot" in content.lower(), \
            "Should have troubleshooting section"

    def test_deployment_doc_has_python_version(self):
        """Test that documentation specifies Python version."""
        deployment_doc = PROJECT_ROOT / "DEPLOYMENT.md"
        content = deployment_doc.read_text()

        assert "Python 3.11" in content or "Python 3.12" in content, \
            "Should specify Python version"


class TestDeployDirectory:
    """Tests for deploy directory structure."""

    def test_deploy_directory_exists(self):
        """Test that deploy directory exists."""
        deploy_dir = PROJECT_ROOT / "deploy"
        assert deploy_dir.exists(), "Deploy directory should exist"
        assert deploy_dir.is_dir(), "Deploy should be a directory"

    def test_all_deploy_files_present(self):
        """Test that all deployment files are present."""
        deploy_dir = PROJECT_ROOT / "deploy"

        expected_files = [
            "yoga-helper.service",
            "cron-daily-crawl",
            "cron-weekly-backup",
            "backup-database.sh",
        ]

        for filename in expected_files:
            file_path = deploy_dir / filename
            assert file_path.exists(), f"Deploy file should exist: {filename}"
