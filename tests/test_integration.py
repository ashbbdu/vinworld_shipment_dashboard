"""End-to-end smoke test using mocked external services."""
import json
from unittest.mock import MagicMock, patch

SAMPLE_CW_RESPONSE = {
    "TransportMode": {"Code": "SEA"},
    "WayBillNumber": "HBL999",
    "WayBillType": {"Code": "HWB", "Description": "House Waybill"},
    "BookingConfirmationReference": "BK-001",
    "PortOfOrigin": {"Name": "Dubai", "Code": "AEDXB"},
    "PortOfDestination": {"Name": "Houston", "Code": "USHOU"},
    "SubShipmentCollection": {"SubShipment": {
        "ServiceLevel": {"Code": "DTD"},
        "TransportMode": {"Code": "SEA"},
        "CustomizedFieldCollection": {"CustomizedField": [
            {"Key": "Opened(A)", "Value": "2024-01-01T00:00:00Z"},
            {"Key": "Carrier Booking(A)", "Value": "2024-01-15T00:00:00Z"},
            {"Key": "ATD Custom(A)", "Value": "2024-03-03T00:00:00Z"},
            {"Key": "ETD Custom(A)", "Value": "2024-03-01T00:00:00Z"},
            {"Key": "ETA Custom(A)", "Value": "2024-03-20T00:00:00Z"},
        ]},
    }},
    "OrganizationAddressCollection": {"OrganizationAddress": [
        {"AddressType": "ConsigneeDocumentaryAddress", "CompanyName": "Test Corp", "OrganizationCode": "TC01"},
    ]},
}

def _make_db():
    db = MagicMock()
    db.fetch_eta_etd.return_value = None
    db.fetch_actuals.return_value = None
    db.was_processed_in_cycle.return_value = False
    db.create_job_run.return_value = "test-run-id"
    db.get_existing_shipment_ids.return_value = set()
    return db

def _make_cw():
    cw = MagicMock()
    cw.fetch_shipment.return_value = SAMPLE_CW_RESPONSE
    cw.fetch_documents.return_value = [{"FileName": "invoice.pdf", "DocumentID": "DOC1"}]
    return cw

def test_full_shipment_processing():
    """Verify complete pipeline: CW fetch -> parse -> milestones -> upsert."""
    from pipeline.jobs.processing import process_shipment
    db = _make_db()
    cw = _make_cw()
    settings = MagicMock()
    settings.SHIPMENT_RETRY_MAX = 3
    settings.SHIPMENT_MAX_LIFETIME_RETRIES = 10
    result = process_shipment("S999", "run-1", db, cw, settings)
    assert result["status"] == "completed"
    record = db.upsert_shipment.call_args[0][0]
    # Core fields
    assert record["JS_UniqueConsignRef"] == "S999"
    assert record["JS_TransportMode"] == "SEA"
    assert record["tradeType"] == "Import"
    assert record["consignee"] == "Test Corp"
    assert record["JS_BookingReference"] == "BK-001"
    # ETA/ETD snapshots (first insert)
    assert record["currentETA"] == "2024-03-20T00:00:00Z"
    assert record["updatedETA"] == "2024-03-20T00:00:00Z"
    assert record["currentETD"] == "2024-03-01T00:00:00Z"
    # Milestones
    milestones_new = json.loads(record["milestones_new"])
    assert len(milestones_new) == 9  # SEA DTD
    sailed = next(m for m in milestones_new if m["eventStatus"] == "Sailed")
    assert sailed["status"] == "Completed"
    assert sailed["delay"] == 2
    # Status
    assert record["primary_status"] == "Active"  # Not all milestones completed
    # Documents
    docs = json.loads(record["documents"])
    assert len(docs) == 1
    assert docs[0]["FileName"] == "invoice.pdf"

def test_eta_snapshot_update_on_second_sync():
    """Verify ETA snapshot logic: updated stays frozen on value change."""
    from pipeline.jobs.processing import process_shipment
    db = _make_db()
    db.fetch_eta_etd.return_value = {
        "currentETA": "2024-03-20T00:00:00Z",
        "updatedETA": "2024-03-20T00:00:00Z",
        "currentETD": "2024-03-01T00:00:00Z",
        "updatedETD": "2024-03-01T00:00:00Z",
    }
    # CW returns different ETA
    response = dict(SAMPLE_CW_RESPONSE)
    response["SubShipmentCollection"] = {"SubShipment": {
        "ServiceLevel": {"Code": "DTD"},
        "TransportMode": {"Code": "SEA"},
        "CustomizedFieldCollection": {"CustomizedField": [
            {"Key": "ETA Custom(A)", "Value": "2024-03-25T00:00:00Z"},
            {"Key": "ETD Custom(A)", "Value": "2024-03-01T00:00:00Z"},
        ]},
    }}
    cw = MagicMock()
    cw.fetch_shipment.return_value = response
    cw.fetch_documents.return_value = []
    settings = MagicMock()
    settings.SHIPMENT_RETRY_MAX = 3
    settings.SHIPMENT_MAX_LIFETIME_RETRIES = 10
    result = process_shipment("S999", "run-2", db, cw, settings)
    assert result["status"] == "completed"
    record = db.upsert_shipment.call_args[0][0]
    assert record["currentETA"] == "2024-03-25T00:00:00Z"  # updated
    assert record["updatedETA"] == "2024-03-20T00:00:00Z"  # frozen

def test_run_job_end_to_end():
    """Verify run_job processes multiple shipments and reports."""
    from pipeline.jobs.processing import run_job
    db = _make_db()
    cw = _make_cw()
    notifier = MagicMock()
    settings = MagicMock()
    settings.MAX_PARALLEL_REQUESTS = 2
    settings.SHIPMENT_RETRY_MAX = 0
    settings.SHIPMENT_RETRY_DELAY = 0
    settings.CW_CIRCUIT_BREAKER_THRESHOLD = 100
    settings.SHIPMENT_MAX_LIFETIME_RETRIES = 10
    run_job("test", ["S001", "S002", "S003"], db, cw, notifier, settings)
    assert db.upsert_shipment.call_count == 3
    db.complete_job_run.assert_called_once()

def test_scheduler_registers_jobs():
    """Verify scheduler registers expected jobs."""
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
    # No shutdown needed — scheduler was never started
