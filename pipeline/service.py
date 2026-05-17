"""
Service entry point — starts the pipeline as a long-running process.

Responsibilities:
  1. Load settings, set up logging, initialise components
  2. Recover interrupted shipments from a prior crash
  3. Start APScheduler with all configured jobs
  4. Run a health-check loop until SIGTERM/SIGINT
  5. Graceful shutdown
"""

import os
import sys
import signal
import logging
import threading
import time

from pipeline.config import Settings
from pipeline.log_setup import setup_logging
from pipeline.db import Database
from pipeline.cargowise import CargoWiseClient
from pipeline.notifications import EmailNotifier
from pipeline.scheduler import setup_scheduler
from pipeline.jobs.processing import run_job

logger = logging.getLogger("pipeline.service")

_shutdown_event = threading.Event()


def touch_health_check(path):
    """Write timestamp to health check file."""
    try:
        with open(path, "w") as f:
            f.write(str(time.time()))
    except Exception as e:
        logger.error(f"Health check write failed: {e}")


def recover_interrupted(db, cw_client, notifier, settings):
    """Find and re-process interrupted shipments from a prior crash."""
    orphans = db.get_interrupted()
    if not orphans:
        logger.info("No interrupted shipments to recover")
        return

    count = len(orphans)
    logger.info(f"Recovering {count} interrupted shipments")

    recovery_run_id = db.create_job_run("recovery")
    shipment_ids = [o["shipment_id"] for o in orphans]

    # Mark old running jobs as failed
    seen_runs = set()
    for o in orphans:
        old_run = o.get("job_run_id")
        if old_run and old_run not in seen_runs:
            try:
                db.complete_job_run(old_run, 0, 0, error_summary="Interrupted by service restart")
            except Exception:
                pass
            seen_runs.add(old_run)

    # Re-process
    run_job("recovery", shipment_ids, db, cw_client, notifier, settings)
    notifier.send_recovery_notice(count)


def _signal_handler(signum, frame):
    logger.info(f"Received signal {signum}, initiating graceful shutdown")
    _shutdown_event.set()


def main():
    # 1. Load settings
    try:
        settings = Settings()
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. Setup logging
    setup_logging(settings)
    # logger.info("Pipeline service starting")
    logger.info(f"Pipeline service starting [ENV={settings.ENV}, DB={settings.DB_NAME}]")

    # 3. Initialize components
    db = Database(settings)
    cw_client = CargoWiseClient(settings)
    notifier = EmailNotifier(settings)

    # 4. Test SMTP (non-fatal)
    try:
        import smtplib

        with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT, timeout=10) as s:
            s.starttls()
            s.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        logger.info("SMTP connection verified")
    except Exception as e:
        logger.warning(f"SMTP test failed (non-fatal): {e}")

    # 5. Recover interrupted work
    recover_interrupted(db, cw_client, notifier, settings)

    # 6. Signal handlers
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # 7. Start scheduler
    scheduler = setup_scheduler(settings, db, cw_client, notifier)
    scheduler.start()
    logger.info("Scheduler started")

    # 8. Health check loop
    logger.info("Pipeline service running")
    while not _shutdown_event.is_set():
        touch_health_check(settings.HEALTH_CHECK_FILE)
        _shutdown_event.wait(timeout=60)

    # 9. Graceful shutdown
    logger.info("Shutting down scheduler")
    scheduler.shutdown(wait=True)
    logger.info("Pipeline service stopped")


if __name__ == "__main__":
    main()
