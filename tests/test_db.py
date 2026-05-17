"""
Tests for pipeline.db — Database layer.

Uses mocks throughout; no real DB connection required.
"""

import pytest
from unittest.mock import MagicMock, patch, call
from pipeline.db import Database, apply_eta_snapshot, apply_actual_snapshot


# ------------------------------------------------------------------ #
# ETA snapshot — pure function tests
# ------------------------------------------------------------------ #

class TestApplyEtaSnapshot:
    def test_first_insert_sets_both(self):
        existing = {"currentETA": None, "updatedETA": None}
        result = apply_eta_snapshot(existing, "2024-03-20T00:00:00Z")
        assert result["currentETA"] == "2024-03-20T00:00:00Z"
        assert result["updatedETA"] == "2024-03-20T00:00:00Z"

    def test_update_changes_current_preserves_updated(self):
        existing = {
            "currentETA": "2024-03-20T00:00:00Z",
            "updatedETA": "2024-03-20T00:00:00Z",
        }
        result = apply_eta_snapshot(existing, "2024-03-22T00:00:00Z")
        assert result["currentETA"] == "2024-03-22T00:00:00Z"
        assert result["updatedETA"] == "2024-03-20T00:00:00Z"

    def test_no_change_keeps_both(self):
        existing = {
            "currentETA": "2024-03-20T00:00:00Z",
            "updatedETA": "2024-03-20T00:00:00Z",
        }
        result = apply_eta_snapshot(existing, "2024-03-20T00:00:00Z")
        assert result["currentETA"] == "2024-03-20T00:00:00Z"
        assert result["updatedETA"] == "2024-03-20T00:00:00Z"

    def test_none_new_value_leaves_unchanged(self):
        existing = {
            "currentETA": "2024-03-20T00:00:00Z",
            "updatedETA": "2024-03-20T00:00:00Z",
        }
        result = apply_eta_snapshot(existing, None)
        assert result["currentETA"] == "2024-03-20T00:00:00Z"
        assert result["updatedETA"] == "2024-03-20T00:00:00Z"

    def test_empty_string_new_value_leaves_unchanged(self):
        existing = {
            "currentETA": "2024-03-20T00:00:00Z",
            "updatedETA": "2024-03-20T00:00:00Z",
        }
        result = apply_eta_snapshot(existing, "")
        assert result["currentETA"] == "2024-03-20T00:00:00Z"
        assert result["updatedETA"] == "2024-03-20T00:00:00Z"

    def test_updated_none_gets_frozen_on_change(self):
        """When updatedETA is None and current changes, freeze updatedETA."""
        existing = {"currentETA": "2024-03-20T00:00:00Z", "updatedETA": None}
        result = apply_eta_snapshot(existing, "2024-03-25T00:00:00Z")
        assert result["currentETA"] == "2024-03-25T00:00:00Z"
        assert result["updatedETA"] == "2024-03-20T00:00:00Z"

    def test_both_none_with_none_input(self):
        existing = {"currentETA": None, "updatedETA": None}
        result = apply_eta_snapshot(existing, None)
        assert result["currentETA"] is None
        assert result["updatedETA"] is None


# ------------------------------------------------------------------ #
# Actual snapshot — pure function tests
# ------------------------------------------------------------------ #

class TestApplyActualSnapshot:
    def test_first_insert_arrival(self):
        existing = {"currentActualArrival": None, "updatedActualArrival": None}
        result = apply_actual_snapshot(existing, "2024-03-20T00:00:00Z", "Arrival")
        assert result["currentActualArrival"] == "2024-03-20T00:00:00Z"
        assert result["updatedActualArrival"] == "2024-03-20T00:00:00Z"

    def test_first_insert_departure(self):
        existing = {"currentActualDeparture": None, "updatedActualDeparture": None}
        result = apply_actual_snapshot(existing, "2024-03-20T00:00:00Z", "Departure")
        assert result["currentActualDeparture"] == "2024-03-20T00:00:00Z"
        assert result["updatedActualDeparture"] == "2024-03-20T00:00:00Z"

    def test_subsequent_update_changes_current_only(self):
        existing = {
            "currentActualArrival": "2024-03-20T00:00:00Z",
            "updatedActualArrival": "2024-03-20T00:00:00Z",
        }
        result = apply_actual_snapshot(existing, "2024-03-22T00:00:00Z", "Arrival")
        assert result["currentActualArrival"] == "2024-03-22T00:00:00Z"
        assert result["updatedActualArrival"] == "2024-03-20T00:00:00Z"

    def test_none_new_value_leaves_unchanged(self):
        existing = {
            "currentActualDeparture": "2024-03-20T00:00:00Z",
            "updatedActualDeparture": "2024-03-20T00:00:00Z",
        }
        result = apply_actual_snapshot(existing, None, "Departure")
        assert result["currentActualDeparture"] == "2024-03-20T00:00:00Z"
        assert result["updatedActualDeparture"] == "2024-03-20T00:00:00Z"

    def test_snapshot_frozen_on_first_change(self):
        """updated is None, current exists -> freeze updated to current before change."""
        existing = {
            "currentActualArrival": "2024-03-18T00:00:00Z",
            "updatedActualArrival": None,
        }
        result = apply_actual_snapshot(existing, "2024-03-22T00:00:00Z", "Arrival")
        assert result["currentActualArrival"] == "2024-03-22T00:00:00Z"
        assert result["updatedActualArrival"] == "2024-03-18T00:00:00Z"

    def test_same_value_no_change(self):
        existing = {
            "currentActualDeparture": "2024-03-20T00:00:00Z",
            "updatedActualDeparture": "2024-03-20T00:00:00Z",
        }
        result = apply_actual_snapshot(existing, "2024-03-20T00:00:00Z", "Departure")
        assert result["currentActualDeparture"] == "2024-03-20T00:00:00Z"
        assert result["updatedActualDeparture"] == "2024-03-20T00:00:00Z"


# ------------------------------------------------------------------ #
# Database class — mocked tests
# ------------------------------------------------------------------ #

def _make_db():
    """Create a Database instance without calling __init__ (no real pool)."""
    db = Database.__new__(Database)
    db._pool = MagicMock()
    db._settings = MagicMock()
    db._settings.SHIPMENT_MAX_LIFETIME_RETRIES = 10
    db._settings.TRACKING_RETENTION_DAYS = 30
    return db


def _mock_conn_cursor():
    """Return (mock_conn, mock_cursor) wired for context-manager use."""
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


class TestGetExistingShipmentIds:
    def test_returns_set_of_ids(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        mock_cursor.fetchall.return_value = [
            {"JS_UniqueConsignRef": "S001"},
            {"JS_UniqueConsignRef": "S002"},
        ]
        db._pool.connection.return_value = mock_conn
        result = db.get_existing_shipment_ids()
        assert result == {"S001", "S002"}

    def test_returns_empty_set_on_no_rows(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        mock_cursor.fetchall.return_value = []
        db._pool.connection.return_value = mock_conn
        result = db.get_existing_shipment_ids()
        assert result == set()

    def test_skips_none_values(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        mock_cursor.fetchall.return_value = [
            {"JS_UniqueConsignRef": "S001"},
            {"JS_UniqueConsignRef": None},
        ]
        db._pool.connection.return_value = mock_conn
        result = db.get_existing_shipment_ids()
        assert result == {"S001"}


class TestCreateJobRun:
    def test_returns_uuid_string(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        db._pool.connection.return_value = mock_conn
        job_id = db.create_job_run("excel_ingest")
        assert len(job_id) == 36  # UUID format
        assert job_id.count("-") == 4

    def test_executes_insert(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        db._pool.connection.return_value = mock_conn
        db.create_job_run("air_sync")
        mock_cursor.execute.assert_called_once()
        sql_arg = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO job_runs" in sql_arg


class TestCompleteJobRun:
    def test_sets_completed_status(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        db._pool.connection.return_value = mock_conn
        db.complete_job_run("abc-123", 10, 2, error_summary="2 failed")
        mock_cursor.execute.assert_called_once()
        sql_arg = mock_cursor.execute.call_args[0][0]
        assert "UPDATE job_runs" in sql_arg
        assert "completed" in sql_arg or "status" in sql_arg


class TestFetchEtaEtd:
    def test_returns_dict_when_found(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        mock_cursor.fetchone.return_value = {
            "currentETA": "2024-03-20",
            "updatedETA": "2024-03-20",
            "currentETD": "2024-03-15",
            "updatedETD": "2024-03-15",
        }
        db._pool.connection.return_value = mock_conn
        result = db.fetch_eta_etd("SHIP001")
        assert result is not None
        assert result["currentETA"] == "2024-03-20"

    def test_returns_none_when_not_found(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        mock_cursor.fetchone.return_value = None
        db._pool.connection.return_value = mock_conn
        result = db.fetch_eta_etd("NONEXISTENT")
        assert result is None


class TestFetchActuals:
    def test_returns_dict_when_found(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        mock_cursor.fetchone.return_value = {
            "currentActualArrival": "2024-03-22",
            "updatedActualArrival": "2024-03-22",
            "currentActualDeparture": "2024-03-15",
            "updatedActualDeparture": "2024-03-15",
        }
        db._pool.connection.return_value = mock_conn
        result = db.fetch_actuals("SHIP001")
        assert result is not None
        assert result["currentActualArrival"] == "2024-03-22"

    def test_returns_none_when_not_found(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        mock_cursor.fetchone.return_value = None
        db._pool.connection.return_value = mock_conn
        result = db.fetch_actuals("NONEXISTENT")
        assert result is None


class TestUpsertShipment:
    def test_insert_when_not_exists(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        mock_cursor.fetchone.return_value = {"cnt": 0}
        db._pool.connection.return_value = mock_conn
        record = {"JS_UniqueConsignRef": "S001", "JS_TransportMode": "SEA"}
        db.upsert_shipment(record)
        calls = mock_cursor.execute.call_args_list
        # First call = SELECT COUNT, second = INSERT
        assert len(calls) == 2
        assert "INSERT" in calls[1][0][0]

    def test_update_when_exists(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        mock_cursor.fetchone.return_value = {"cnt": 1}
        db._pool.connection.return_value = mock_conn
        record = {"JS_UniqueConsignRef": "S001", "JS_TransportMode": "SEA"}
        db.upsert_shipment(record)
        calls = mock_cursor.execute.call_args_list
        assert len(calls) == 2
        assert "UPDATE" in calls[1][0][0]


class TestGetActiveShipments:
    def test_returns_list_of_ids(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        mock_cursor.fetchall.return_value = [
            {"JS_UniqueConsignRef": "S001"},
            {"JS_UniqueConsignRef": "S002"},
        ]
        db._pool.connection.return_value = mock_conn
        result = db.get_active_shipments("AIR", "Active")
        assert result == ["S001", "S002"]


class TestMarkDoNotQuery:
    def test_executes_update(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        db._pool.connection.return_value = mock_conn
        db.mark_do_not_query("SHIP001")
        mock_cursor.execute.assert_called_once()
        sql_arg = mock_cursor.execute.call_args[0][0]
        assert "do_not_query" in sql_arg


class TestTrackShipment:
    def test_inserts_tracking_row(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        db._pool.connection.return_value = mock_conn
        db.track_shipment("S001", "run-uuid", "excel_ingest", status="pending")
        mock_cursor.execute.assert_called_once()
        sql_arg = mock_cursor.execute.call_args[0][0]
        assert "shipment_tracking" in sql_arg


class TestBulkTrackShipments:
    def test_bulk_insert(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        db._pool.connection.return_value = mock_conn
        db.bulk_track_shipments(["S001", "S002", "S003"], "run-uuid", "air_sync")
        mock_cursor.executemany.assert_called_once()


class TestUpdateTracking:
    def test_updates_status(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        db._pool.connection.return_value = mock_conn
        db.update_tracking("S001", "run-uuid", "completed")
        mock_cursor.execute.assert_called_once()
        sql_arg = mock_cursor.execute.call_args[0][0]
        assert "UPDATE shipment_tracking" in sql_arg


class TestGetInterrupted:
    def test_returns_list_of_dicts(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        mock_cursor.fetchall.return_value = [
            {"shipment_id": "S001", "job_run_id": "r1", "job_type": "air_sync"},
        ]
        db._pool.connection.return_value = mock_conn
        result = db.get_interrupted()
        assert len(result) == 1
        assert result[0]["shipment_id"] == "S001"


class TestGetFailedShipments:
    def test_returns_list(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        mock_cursor.fetchall.return_value = [
            {"shipment_id": "S001", "lifetime_retry_count": 2},
        ]
        db._pool.connection.return_value = mock_conn
        result = db.get_failed_shipments()
        assert len(result) == 1


class TestGetDeadLetterShipments:
    def test_returns_list(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        mock_cursor.fetchall.return_value = [
            {"shipment_id": "S001", "lifetime_retry_count": 10},
        ]
        db._pool.connection.return_value = mock_conn
        result = db.get_dead_letter_shipments()
        assert len(result) == 1


class TestWasProcessedInCycle:
    def test_true_when_found(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        mock_cursor.fetchone.return_value = {"cnt": 1}
        db._pool.connection.return_value = mock_conn
        assert db.was_processed_in_cycle("S001", "run-uuid") is True

    def test_false_when_not_found(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        mock_cursor.fetchone.return_value = {"cnt": 0}
        db._pool.connection.return_value = mock_conn
        assert db.was_processed_in_cycle("S001", "run-uuid") is False


class TestSaveExcelMetadata:
    def test_returns_insert_id(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        mock_cursor.lastrowid = 42
        db._pool.connection.return_value = mock_conn
        metadata = {
            "filename": "report.xlsx",
            "job_run_id": "run-uuid",
            "row_count": 100,
        }
        result = db.save_excel_metadata(metadata)
        assert result == 42


class TestSaveExcelRows:
    def test_bulk_insert(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        db._pool.connection.return_value = mock_conn
        rows = [
            {"shipment_id": "S001", "raw_row_data": "{}", "is_new": True},
            {"shipment_id": "S002", "raw_row_data": "{}", "is_new": False},
        ]
        db.save_excel_rows(1, rows)
        mock_cursor.executemany.assert_called_once()


class TestPurgeOldTracking:
    def test_executes_delete(self):
        db = _make_db()
        mock_conn, mock_cursor = _mock_conn_cursor()
        db._pool.connection.return_value = mock_conn
        db.purge_old_tracking(30)
        mock_cursor.execute.assert_called_once()
        sql_arg = mock_cursor.execute.call_args[0][0]
        assert "DELETE" in sql_arg
        assert "job_runs" in sql_arg
