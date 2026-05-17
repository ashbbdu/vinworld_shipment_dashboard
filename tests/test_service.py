"""Tests for pipeline.service — health check, recovery, and signal handling."""

import os
import tempfile
from unittest.mock import MagicMock, patch


# ------------------------------------------------------------------ #
# touch_health_check
# ------------------------------------------------------------------ #

def test_touch_health_check():
    from pipeline.service import touch_health_check

    with tempfile.NamedTemporaryFile(delete=False) as f:
        path = f.name
    touch_health_check(path)
    assert os.path.exists(path)
    # Verify it was updated
    mtime = os.path.getmtime(path)
    assert mtime > 0
    os.unlink(path)


def test_touch_health_check_creates_file():
    from pipeline.service import touch_health_check

    path = tempfile.mktemp(suffix="_health")
    try:
        touch_health_check(path)
        assert os.path.exists(path)
        with open(path) as f:
            content = f.read()
        # Should contain a numeric timestamp
        assert float(content) > 0
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ------------------------------------------------------------------ #
# recover_interrupted
# ------------------------------------------------------------------ #

def test_recover_interrupted_with_orphans():
    from pipeline.service import recover_interrupted

    db = MagicMock()
    db.get_interrupted.return_value = [
        {"shipment_id": "S001", "job_run_id": "old-run"},
        {"shipment_id": "S002", "job_run_id": "old-run"},
    ]
    db.create_job_run.return_value = "recovery-run"
    notifier = MagicMock()
    settings = MagicMock()
    settings.MAX_PARALLEL_REQUESTS = 1
    settings.SHIPMENT_RETRY_MAX = 0
    settings.SHIPMENT_RETRY_DELAY = 0
    settings.CW_CIRCUIT_BREAKER_THRESHOLD = 100

    with patch("pipeline.service.run_job") as mock_run:
        recover_interrupted(db, MagicMock(), notifier, settings)
        notifier.send_recovery_notice.assert_called_with(2)
        mock_run.assert_called_once()


def test_recover_interrupted_no_orphans():
    from pipeline.service import recover_interrupted

    db = MagicMock()
    db.get_interrupted.return_value = []
    notifier = MagicMock()
    recover_interrupted(db, MagicMock(), notifier, MagicMock())
    notifier.send_recovery_notice.assert_not_called()


def test_recover_interrupted_marks_old_runs_failed():
    from pipeline.service import recover_interrupted

    db = MagicMock()
    db.get_interrupted.return_value = [
        {"shipment_id": "S001", "job_run_id": "run-A"},
        {"shipment_id": "S002", "job_run_id": "run-A"},
        {"shipment_id": "S003", "job_run_id": "run-B"},
    ]
    db.create_job_run.return_value = "recovery-run"
    notifier = MagicMock()

    with patch("pipeline.service.run_job"):
        recover_interrupted(db, MagicMock(), notifier, MagicMock())

    # Should mark both old runs as failed (deduplicated)
    complete_calls = db.complete_job_run.call_args_list
    assert len(complete_calls) == 2
    run_ids_marked = {c[0][0] for c in complete_calls}
    assert run_ids_marked == {"run-A", "run-B"}
