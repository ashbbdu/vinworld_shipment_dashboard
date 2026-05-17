"""
Scheduler — configures APScheduler with all pipeline jobs.

parse_cron_schedule() converts a standard 5-field cron string into
APScheduler CronTrigger kwargs.  setup_scheduler() wires up all jobs
(excel ingest with chained AIR/SEA sync, SEA reverse, nightly retry,
and archive) on their configured schedules.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("pipeline.scheduler")


def parse_cron_schedule(cron_str):
    """Parse '0 10 */3 * *' into APScheduler CronTrigger kwargs."""
    parts = cron_str.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron schedule: {cron_str}")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def setup_scheduler(settings, db, cw_client, notifier):
    """Create and configure APScheduler with all jobs."""
    from pipeline.jobs import excel_ingest, sync_air, sync_sea, nightly_retry, archive

    scheduler = BackgroundScheduler()
    max_inst = settings.JOB_MAX_INSTANCES

    # Excel Ingest (time-triggered, chains to AIR + SEA on completion)
    def excel_ingest_with_chain():
        try:
            job_run_id = excel_ingest.run(db, cw_client, notifier, settings)
            # Event-driven chain: trigger AIR and SEA sync after Excel completes
            logger.info("Excel ingest complete, triggering AIR and SEA sync")
            sync_air.run(db, cw_client, notifier, settings, parent_job_run_id=job_run_id)
            sync_sea.run_sync(db, cw_client, notifier, settings, parent_job_run_id=job_run_id)
        except Exception as e:
            logger.error(f"Excel ingest chain failed: {e}")

    cron = parse_cron_schedule(settings.EXCEL_INGEST_SCHEDULE)
    scheduler.add_job(
        excel_ingest_with_chain,
        CronTrigger(**cron),
        id="excel_ingest",
        max_instances=max_inst,
    )

    # SEA Reverse (midnight, independent)
    cron = parse_cron_schedule(settings.SEA_REVERSE_SCHEDULE)
    scheduler.add_job(
        lambda: sync_sea.run_reverse(db, cw_client, notifier, settings),
        CronTrigger(**cron),
        id="sea_reverse",
        max_instances=max_inst,
    )

    # Nightly Retry (optional)
    if settings.NIGHTLY_RETRY_ENABLED:
        cron = parse_cron_schedule(settings.NIGHTLY_RETRY_SCHEDULE)
        scheduler.add_job(
            lambda: nightly_retry.run(db, cw_client, notifier, settings),
            CronTrigger(**cron),
            id="nightly_retry",
            max_instances=max_inst,
        )

    # Archive (optional)
    if settings.ARCHIVE_ENABLED:
        cron = parse_cron_schedule(settings.ARCHIVE_SCHEDULE)
        scheduler.add_job(
            lambda: archive.run(db, settings),
            CronTrigger(**cron),
            id="archive",
            max_instances=max_inst,
        )

    return scheduler
