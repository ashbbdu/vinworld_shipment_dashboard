"""Tests for pipeline.scheduler — cron parsing and scheduler setup."""

import pytest
from unittest.mock import MagicMock, patch


# ------------------------------------------------------------------ #
# parse_cron_schedule
# ------------------------------------------------------------------ #

def test_parse_cron_schedule_standard():
    from pipeline.scheduler import parse_cron_schedule

    result = parse_cron_schedule("0 10 */3 * *")
    assert result["minute"] == "0"
    assert result["hour"] == "10"
    assert result["day"] == "*/3"
    assert result["month"] == "*"
    assert result["day_of_week"] == "*"


def test_parse_cron_schedule_midnight():
    from pipeline.scheduler import parse_cron_schedule

    result = parse_cron_schedule("0 0 * * *")
    assert result["hour"] == "0"
    assert result["minute"] == "0"


def test_parse_cron_schedule_complex():
    from pipeline.scheduler import parse_cron_schedule

    result = parse_cron_schedule("30 2 1,15 * 1-5")
    assert result["minute"] == "30"
    assert result["hour"] == "2"
    assert result["day"] == "1,15"
    assert result["day_of_week"] == "1-5"


def test_parse_cron_schedule_invalid_too_few_parts():
    from pipeline.scheduler import parse_cron_schedule

    with pytest.raises(ValueError, match="Invalid cron schedule"):
        parse_cron_schedule("0 10 *")


def test_parse_cron_schedule_invalid_too_many_parts():
    from pipeline.scheduler import parse_cron_schedule

    with pytest.raises(ValueError, match="Invalid cron schedule"):
        parse_cron_schedule("0 10 * * * *")


def test_parse_cron_schedule_strips_whitespace():
    from pipeline.scheduler import parse_cron_schedule

    result = parse_cron_schedule("  5  12  *  *  0  ")
    assert result["minute"] == "5"
    assert result["hour"] == "12"
    assert result["day_of_week"] == "0"


# ------------------------------------------------------------------ #
# setup_scheduler
# ------------------------------------------------------------------ #

def test_setup_scheduler_registers_core_jobs():
    """Scheduler must register excel_ingest and sea_reverse at minimum."""
    from pipeline.scheduler import setup_scheduler

    settings = MagicMock()
    settings.EXCEL_INGEST_SCHEDULE = "0 10 */3 * *"
    settings.SEA_REVERSE_SCHEDULE = "0 0 * * *"
    settings.NIGHTLY_RETRY_ENABLED = False
    settings.ARCHIVE_ENABLED = False
    settings.JOB_MAX_INSTANCES = 1

    scheduler = setup_scheduler(settings, MagicMock(), MagicMock(), MagicMock())

    job_ids = {j.id for j in scheduler.get_jobs()}
    assert "excel_ingest" in job_ids
    assert "sea_reverse" in job_ids
    assert "nightly_retry" not in job_ids
    assert "archive" not in job_ids


def test_setup_scheduler_registers_optional_jobs():
    """When enabled, nightly_retry and archive jobs are registered."""
    from pipeline.scheduler import setup_scheduler

    settings = MagicMock()
    settings.EXCEL_INGEST_SCHEDULE = "0 10 */3 * *"
    settings.SEA_REVERSE_SCHEDULE = "0 0 * * *"
    settings.NIGHTLY_RETRY_ENABLED = True
    settings.NIGHTLY_RETRY_SCHEDULE = "30 0 * * *"
    settings.ARCHIVE_ENABLED = True
    settings.ARCHIVE_SCHEDULE = "0 2 * * *"
    settings.JOB_MAX_INSTANCES = 1

    scheduler = setup_scheduler(settings, MagicMock(), MagicMock(), MagicMock())

    job_ids = {j.id for j in scheduler.get_jobs()}
    assert "excel_ingest" in job_ids
    assert "sea_reverse" in job_ids
    assert "nightly_retry" in job_ids
    assert "archive" in job_ids
