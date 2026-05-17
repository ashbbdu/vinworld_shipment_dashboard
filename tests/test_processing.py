from unittest.mock import MagicMock, patch
from requests.exceptions import Timeout, ConnectionError as ReqConnectionError
import json


def _make_settings():
    s = MagicMock()
    s.SHIPMENT_RETRY_MAX = 3
    s.SHIPMENT_RETRY_DELAY = 0  # no delay in tests
    s.SHIPMENT_MAX_LIFETIME_RETRIES = 10
    s.MAX_PARALLEL_REQUESTS = 2
    s.CW_CIRCUIT_BREAKER_THRESHOLD = 3
    return s


def _make_db():
    db = MagicMock()
    db.fetch_eta_etd.return_value = None  # no existing record
    db.fetch_actuals.return_value = None
    db.was_processed_in_cycle.return_value = False
    return db


def _make_cw():
    cw = MagicMock()
    cw.fetch_shipment.return_value = {
        "TransportMode": {"Code": "AIR"},
        "SubShipmentCollection": {"SubShipment": {"ServiceLevel": {"Code": "DTD"}}},
        "WayBillNumber": "AWB123",
        "WayBillType": {"Code": "HWB"},
        "PortOfOrigin": {"Name": "Dubai", "Code": "AEDXB"},
        "PortOfDestination": {"Name": "Houston", "Code": "USHOU"},
    }
    cw.fetch_documents.return_value = []
    return cw


def test_process_shipment_success():
    from pipeline.jobs.processing import process_shipment
    db = _make_db()
    cw = _make_cw()
    result = process_shipment("S001", "run-1", db, cw, _make_settings())
    assert result["status"] == "completed"
    db.update_tracking.assert_called()
    db.upsert_shipment.assert_called_once()


def test_process_shipment_retry_on_timeout():
    from pipeline.jobs.processing import process_shipment
    db = _make_db()
    cw = MagicMock()
    cw.fetch_shipment.side_effect = Timeout("timed out")
    result = process_shipment("S001", "run-1", db, cw, _make_settings(), retry_count=0)
    assert result["status"] == "retry"
    assert result["retry_count"] == 1


def test_process_shipment_fails_after_max_retries():
    from pipeline.jobs.processing import process_shipment
    db = _make_db()
    cw = MagicMock()
    cw.fetch_shipment.side_effect = Timeout("timed out")
    result = process_shipment("S001", "run-1", db, cw, _make_settings(), retry_count=3)
    assert result["status"] == "failed"


def test_process_shipment_fails_on_unexpected_error():
    from pipeline.jobs.processing import process_shipment
    db = _make_db()
    cw = MagicMock()
    cw.fetch_shipment.side_effect = ValueError("unexpected")
    result = process_shipment("S001", "run-1", db, cw, _make_settings())
    assert result["status"] == "failed"
    assert "unexpected" in result["error"]


def test_process_shipment_applies_eta_snapshot():
    from pipeline.jobs.processing import process_shipment
    db = _make_db()
    db.fetch_eta_etd.return_value = {"currentETA": "2024-03-20", "updatedETA": "2024-03-20", "currentETD": None, "updatedETD": None}
    cw = _make_cw()
    # Add ETA custom field to response
    cw.fetch_shipment.return_value["SubShipmentCollection"]["SubShipment"]["CustomizedFieldCollection"] = {
        "CustomizedField": [{"Key": "ETA Custom(A)", "Value": "2024-03-22T00:00:00Z"}]
    }
    result = process_shipment("S001", "run-1", db, cw, _make_settings())
    assert result["status"] == "completed"
    # Verify upsert was called with updated ETA
    record = db.upsert_shipment.call_args[0][0]
    assert record["currentETA"] == "2024-03-22T00:00:00Z"
    assert record["updatedETA"] == "2024-03-20"  # original snapshot preserved


def test_run_job_processes_all_shipments():
    from pipeline.jobs.processing import run_job
    db = _make_db()
    db.create_job_run.return_value = "run-123"
    cw = _make_cw()
    notifier = MagicMock()
    settings = _make_settings()
    run_job("air_sync", ["S001", "S002"], db, cw, notifier, settings)
    assert db.upsert_shipment.call_count == 2
    db.complete_job_run.assert_called_once()


def test_run_job_circuit_breaker():
    from pipeline.jobs.processing import run_job
    db = _make_db()
    db.create_job_run.return_value = "run-123"
    cw = MagicMock()
    cw.fetch_shipment.side_effect = ReqConnectionError("down")
    notifier = MagicMock()
    settings = _make_settings()
    settings.MAX_PARALLEL_REQUESTS = 1  # sequential for predictable behavior
    settings.CW_CIRCUIT_BREAKER_THRESHOLD = 3
    settings.SHIPMENT_RETRY_MAX = 0  # no retries
    run_job("test", [f"S{i:03d}" for i in range(10)], db, cw, notifier, settings)
    notifier.send_circuit_breaker_alert.assert_called_once()
    # Should have stopped early, not all 10 processed
    assert cw.fetch_shipment.call_count < 10


def test_run_job_sends_failure_email():
    from pipeline.jobs.processing import run_job
    db = _make_db()
    db.create_job_run.return_value = "run-123"
    cw = MagicMock()
    cw.fetch_shipment.side_effect = ValueError("bad")
    notifier = MagicMock()
    settings = _make_settings()
    settings.MAX_PARALLEL_REQUESTS = 1
    run_job("test", ["S001"], db, cw, notifier, settings)
    notifier.send_job_failure.assert_called_once()


def test_run_job_skips_duplicates():
    from pipeline.jobs.processing import run_job
    db = _make_db()
    db.create_job_run.return_value = "run-123"
    db.was_processed_in_cycle.side_effect = lambda sid, rid: sid == "S001"
    cw = _make_cw()
    notifier = MagicMock()
    settings = _make_settings()
    run_job("air_sync", ["S001", "S002"], db, cw, notifier, settings, parent_job_run_id="parent-1")
    # S001 should be skipped
    assert db.upsert_shipment.call_count == 1
