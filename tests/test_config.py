"""Tests for pipeline.config.Settings."""

import os
import pytest


# All required env vars with dummy values for testing
REQUIRED_VARS = {
    "DB_HOST": "localhost",
    "DB_USER": "testuser",
    "DB_PASSWORD": "testpass",
    "DB_NAME": "testdb",
    "CW_API_URL": "https://api.example.com",
    "CW_CLIENT_ID": "client-id",
    "CW_CLIENT_SECRET": "client-secret",
    "CW_USERNAME": "cw-user",
    "CW_PASSWORD": "cw-pass",
    "CW_ORIGIN": "origin",
    "SFTP_HOST": "sftp.example.com",
    "SFTP_USERNAME": "sftp-user",
    "SFTP_PASSWORD": "sftp-pass",
    "SMTP_SERVER": "smtp.example.com",
    "SMTP_USERNAME": "smtp-user",
    "SMTP_PASSWORD": "smtp-pass",
    "SMTP_FROM": "noreply@example.com",
    "ERROR_EMAIL_RECIPIENTS": "admin@example.com",
    "AWS_S3_BUCKET": "my-bucket",
    "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE",
    "AWS_SECRET_ACCESS_KEY": "secret-key",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure a clean environment for every test — remove all known vars first."""
    all_keys = list(REQUIRED_VARS.keys()) + [
        "DB_POOL_SIZE", "CW_TIMEOUT", "CW_RATE_LIMIT",
        "CW_CIRCUIT_BREAKER_THRESHOLD", "CW_VERIFY_SSL",
        "SFTP_PORT", "SFTP_FILE_PATTERN", "SFTP_SAFE_AGE_SECONDS",
        "SFTP_DELETE_AFTER_INGEST", "EXCEL_INGEST_SCHEDULE",
        "SEA_REVERSE_SCHEDULE", "NIGHTLY_RETRY_ENABLED",
        "NIGHTLY_RETRY_SCHEDULE", "ARCHIVE_ENABLED", "ARCHIVE_SCHEDULE",
        "JOB_MAX_INSTANCES", "SEA_ETA_WINDOW_DAYS",
        "AIR_SYNC_TRANSPORT_MODE", "AIR_SYNC_STATUS",
        "SEA_SYNC_TRANSPORT_MODE", "SEA_SYNC_STATUS",
        "MAX_PARALLEL_REQUESTS", "SHIPMENT_RETRY_MAX",
        "SHIPMENT_RETRY_DELAY", "SHIPMENT_MAX_LIFETIME_RETRIES",
        "SMTP_PORT", "SMTP_FROM_NAME", "JOB_REPORT_RECIPIENTS",
        "AWS_S3_ARCHIVE_PREFIX", "AWS_REGION", "ARCHIVE_AGE_DAYS",
        "DEBUG", "LOG_FILE", "LOG_LEVEL", "LOG_ROTATION",
        "DOWNLOAD_DIR", "HEALTH_CHECK_FILE", "TRACKING_RETENTION_DAYS",
    ]
    for key in all_keys:
        monkeypatch.delenv(key, raising=False)


def _set_all_required(monkeypatch):
    for key, val in REQUIRED_VARS.items():
        monkeypatch.setenv(key, val)


class TestSettingsLoadsDefaults:
    """Settings should load all required vars and apply correct defaults."""

    def test_loads_all_required_vars(self, monkeypatch):
        _set_all_required(monkeypatch)
        from pipeline.config import Settings

        s = Settings()
        assert s.DB_HOST == "localhost"
        assert s.DB_USER == "testuser"
        assert s.CW_API_URL == "https://api.example.com"
        assert s.SFTP_HOST == "sftp.example.com"
        assert s.SMTP_SERVER == "smtp.example.com"
        assert s.AWS_S3_BUCKET == "my-bucket"

    def test_applies_int_defaults(self, monkeypatch):
        _set_all_required(monkeypatch)
        from pipeline.config import Settings

        s = Settings()
        assert s.DB_POOL_SIZE == 5
        assert s.CW_TIMEOUT == 60
        assert s.CW_RATE_LIMIT == 10
        assert s.SFTP_PORT == 22
        assert s.SMTP_PORT == 587
        assert s.ARCHIVE_AGE_DAYS == 7
        assert s.TRACKING_RETENTION_DAYS == 30
        assert s.MAX_PARALLEL_REQUESTS == 5
        assert s.SHIPMENT_RETRY_MAX == 3
        assert s.SHIPMENT_RETRY_DELAY == 30
        assert s.JOB_MAX_INSTANCES == 1
        assert s.SEA_ETA_WINDOW_DAYS == 3

    def test_applies_bool_defaults(self, monkeypatch):
        _set_all_required(monkeypatch)
        from pipeline.config import Settings

        s = Settings()
        assert s.CW_VERIFY_SSL is False
        assert s.DEBUG is False
        assert s.SFTP_DELETE_AFTER_INGEST is True
        assert s.NIGHTLY_RETRY_ENABLED is True
        assert s.ARCHIVE_ENABLED is True

    def test_applies_string_defaults(self, monkeypatch):
        _set_all_required(monkeypatch)
        from pipeline.config import Settings

        s = Settings()
        assert s.LOG_FILE == "pipeline.log"
        assert s.LOG_LEVEL == "INFO"
        assert s.LOG_ROTATION == "daily"
        assert s.DOWNLOAD_DIR == "/tmp/pipeline_downloads"
        assert s.AWS_REGION == "us-east-1"
        assert s.AIR_SYNC_TRANSPORT_MODE == "AIR"
        assert s.SEA_SYNC_TRANSPORT_MODE == "SEA"
        assert s.SMTP_FROM_NAME == "VIN World Pipeline"

    def test_overrides_defaults(self, monkeypatch):
        _set_all_required(monkeypatch)
        monkeypatch.setenv("DB_POOL_SIZE", "20")
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        from pipeline.config import Settings

        s = Settings()
        assert s.DB_POOL_SIZE == 20
        assert s.DEBUG is True
        assert s.LOG_LEVEL == "DEBUG"


class TestSettingsRaisesOnMissing:
    """Settings must raise ValueError when a required var is absent."""

    @pytest.mark.parametrize("missing_key", list(REQUIRED_VARS.keys()))
    def test_missing_required_var_raises(self, monkeypatch, missing_key):
        _set_all_required(monkeypatch)
        monkeypatch.delenv(missing_key)
        from pipeline.config import Settings

        with pytest.raises(ValueError, match=f"Missing required environment variable: {missing_key}"):
            Settings()

    def test_empty_required_var_raises(self, monkeypatch):
        _set_all_required(monkeypatch)
        monkeypatch.setenv("DB_HOST", "   ")
        from pipeline.config import Settings

        with pytest.raises(ValueError, match="Missing required environment variable: DB_HOST"):
            Settings()
