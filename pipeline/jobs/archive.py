import logging
from pipeline.archiver import Archiver

logger = logging.getLogger("pipeline.jobs.archive")

def run(db, settings):
    """Archive old files to S3 and purge old tracking records."""
    if not settings.ARCHIVE_ENABLED:
        logger.info("Archival disabled (ARCHIVE_ENABLED=False)")
        return

    try:
        archiver = Archiver(settings)
        archiver.archive_excel_files(db)
        archiver.archive_logs()
        archiver.cleanup_local()
    except Exception as e:
        logger.error(f"Archival error: {e}")

    # Always purge old tracking records (even if S3 archival fails)
    try:
        db.purge_old_tracking(settings.TRACKING_RETENTION_DAYS)
        logger.info(f"Purged tracking records older than {settings.TRACKING_RETENTION_DAYS} days")
    except Exception as e:
        logger.error(f"Tracking purge error: {e}")
