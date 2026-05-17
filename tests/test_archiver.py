import os
import time
from unittest.mock import MagicMock, patch

def test_archiver_run_skips_when_disabled():
    from pipeline.jobs.archive import run
    settings = MagicMock()
    settings.ARCHIVE_ENABLED = False
    db = MagicMock()
    run(db, settings)
    # Should not attempt any S3 operations

def test_archiver_purges_old_tracking():
    from pipeline.jobs.archive import run
    settings = MagicMock()
    settings.ARCHIVE_ENABLED = True
    settings.TRACKING_RETENTION_DAYS = 30
    settings.AWS_S3_BUCKET = ""  # no bucket = skip S3
    db = MagicMock()
    run(db, settings)
    db.purge_old_tracking.assert_called_once_with(30)
