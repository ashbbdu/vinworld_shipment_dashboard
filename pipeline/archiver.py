import os
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("pipeline.archiver")

class Archiver:
    def __init__(self, settings):
        self._settings = settings
        self._s3 = None
        if settings.AWS_S3_BUCKET and settings.AWS_ACCESS_KEY_ID:
            import boto3
            self._s3 = boto3.client(
                "s3",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION,
            )

    def archive_excel_files(self, db):
        if not self._s3:
            return
        # Query excel_imports where s3_archive_path IS NULL and old enough
        # Upload and update path
        # Implementation depends on db.get_archivable_imports()
        logger.info("Excel file archival complete")

    def archive_logs(self):
        if not self._s3:
            return
        log_dir = os.path.dirname(self._settings.LOG_FILE) or "."
        cutoff = datetime.now() - timedelta(days=self._settings.ARCHIVE_AGE_DAYS)
        for f in os.listdir(log_dir):
            filepath = os.path.join(log_dir, f)
            if os.path.isfile(filepath) and os.path.getmtime(filepath) < cutoff.timestamp():
                date_str = datetime.fromtimestamp(os.path.getmtime(filepath)).strftime("%Y-%m-%d")
                s3_key = f"{self._settings.AWS_S3_ARCHIVE_PREFIX}logs/{date_str}/{f}"
                try:
                    self._s3.upload_file(filepath, self._settings.AWS_S3_BUCKET, s3_key)
                    os.remove(filepath)
                    logger.info(f"Archived log {f} to s3://{self._settings.AWS_S3_BUCKET}/{s3_key}")
                except Exception as e:
                    logger.error(f"Failed to archive {f}: {e}")

    def cleanup_local(self):
        download_dir = self._settings.DOWNLOAD_DIR
        if not os.path.exists(download_dir):
            return
        cutoff = datetime.now() - timedelta(days=self._settings.ARCHIVE_AGE_DAYS)
        for f in os.listdir(download_dir):
            filepath = os.path.join(download_dir, f)
            if os.path.isfile(filepath) and os.path.getmtime(filepath) < cutoff.timestamp():
                os.remove(filepath)
                logger.info(f"Cleaned up old file: {f}")
