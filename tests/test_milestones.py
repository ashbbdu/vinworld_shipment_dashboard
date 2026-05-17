"""Tests for pipeline.milestones — data-driven milestone builder."""

from pipeline.milestones import (
    build_milestones, build_milestones_reformed, derive_status,
    extract_milestones_from_customized_fields, get_last_completed_event,
    SEQUENCES, extract_milestones_for_mode
)

# --- Sequence definition tests ---

def test_all_sequences_defined():
    expected = [("SEA","DTD"),("SEA","DTP"),("SEA","PTD"),("SEA","PTP"),
                ("AIR","DTD"),("AIR","DTP"),("AIR","PTD"),("AIR","PTP")]
    for key in expected:
        assert key in SEQUENCES, f"Missing sequence: {key}"

def test_sea_dtd_has_9_milestones():
    assert len(SEQUENCES[("SEA", "DTD")]) == 9

def test_sea_dtp_has_8_milestones():
    assert len(SEQUENCES[("SEA", "DTP")]) == 8

def test_air_dtd_has_9_milestones():
    assert len(SEQUENCES[("AIR", "DTD")]) == 9

def test_air_ptp_has_7_milestones():
    assert len(SEQUENCES[("AIR", "PTP")]) == 7

def test_air_ptd_has_8_milestones():
    assert len(SEQUENCES[("AIR", "PTD")]) == 8

def test_air_dtp_has_8_milestones():
    assert len(SEQUENCES[("AIR", "DTP")]) == 8

# --- build_milestones tests ---

def test_build_milestones_sea_dtd():
    actuals = {"Opened": "2024-01-01T00:00:00Z", "ATD Custom": "2024-03-03T00:00:00Z"}
    dates = {"currentETA": "2024-03-20T00:00:00Z", "currentETD": "2024-03-01T00:00:00Z"}
    result = build_milestones("SEA", "DTD", actuals, dates)
    assert len(result) == 9
    assert result[0]["eventStatus"] == "Opened"
    assert result[0]["status"] == "Completed"
    assert result[0]["actualDate"] == "2024-01-01T00:00:00Z"
    assert result[-1]["eventStatus"] == "Delivered"
    assert result[-1]["status"] == "Pending"

def test_build_milestones_sailed_delay():
    actuals = {"ATD Custom": "2024-03-03T00:00:00Z"}
    dates = {"currentETD": "2024-03-01T00:00:00Z"}
    result = build_milestones("SEA", "DTD", actuals, dates)
    sailed = next(m for m in result if m["eventStatus"] == "Sailed")
    assert sailed["delay"] == 2
    assert sailed["plannedDate"] == "2024-03-01T00:00:00Z"

def test_build_milestones_arrived_delay():
    actuals = {"ATA Custom": "2024-03-22T00:00:00Z"}
    dates = {"currentETA": "2024-03-20T00:00:00Z"}
    result = build_milestones("SEA", "DTD", actuals, dates)
    arrived = next(m for m in result if m["eventStatus"] == "Arrived")
    assert arrived["delay"] == 2

def test_build_milestones_discharged_planned_from_arrived():
    actuals = {"ATA Custom": "2024-03-20T00:00:00Z", "Gate Out": "2024-03-21T00:00:00Z"}
    dates = {}
    result = build_milestones("SEA", "DTD", actuals, dates)
    discharged = next(m for m in result if m["eventStatus"] == "Discharged")
    assert discharged["plannedDate"] == "2024-03-20T00:00:00Z"
    assert discharged["delay"] == 1

def test_build_milestones_delivered_planned_eta_plus_buffer():
    actuals = {}
    dates = {"currentETA": "2024-03-20T00:00:00Z"}
    result = build_milestones("SEA", "DTD", actuals, dates, buffer_days=4)
    delivered = next(m for m in result if m["eventStatus"] == "Delivered")
    assert delivered["plannedDate"] is not None
    assert "2024-03-24" in delivered["plannedDate"]

def test_build_milestones_no_delay_without_both_dates():
    actuals = {"ATD Custom": "2024-03-03T00:00:00Z"}
    dates = {}  # no currentETD
    result = build_milestones("SEA", "DTD", actuals, dates)
    sailed = next(m for m in result if m["eventStatus"] == "Sailed")
    assert sailed["delay"] is None  # no planned, so no delay

def test_build_milestones_air_dtd():
    actuals = {"Opened": "2024-01-01T00:00:00Z", "Picked": "2024-01-05T00:00:00Z"}
    dates = {}
    result = build_milestones("AIR", "DTD", actuals, dates)
    assert len(result) == 9
    assert result[2]["eventStatus"] == "Picked up"
    assert result[2]["status"] == "Completed"

def test_build_milestones_air_ptd_no_picked():
    result = build_milestones("AIR", "PTD", {}, {})
    labels = [m["eventStatus"] for m in result]
    assert "Picked up" not in labels
    assert "Delivered" in labels

def test_build_milestones_air_ptp_no_picked_no_delivered():
    result = build_milestones("AIR", "PTP", {}, {})
    labels = [m["eventStatus"] for m in result]
    assert "Picked up" not in labels
    assert "Delivered" not in labels

def test_build_milestones_unknown_returns_empty():
    assert build_milestones("RAIL", "DTD", {}, {}) == []
    assert build_milestones("SEA", "UNKNOWN", {}, {}) == []

def test_all_milestones_have_required_keys():
    result = build_milestones("SEA", "DTD", {}, {})
    for m in result:
        assert "eventStatus" in m
        assert "customField" in m
        assert "actualDate" in m
        assert "plannedDate" in m
        assert "status" in m
        assert "delay" in m

# --- extract_milestones_from_customized_fields tests ---

def test_extract_milestones_sea():
    fields = [
        {"Key": "Opened(A)", "Value": "2024-01-01"},
        {"Key": "ATD Custom(A)", "Value": "2024-03-01"},
        {"Key": "ATA Custom(M)", "Value": "2024-03-20"},  # lower priority than (A)
    ]
    result = extract_milestones_from_customized_fields(fields, "SEA")
    opened = next(m for m in result if m["customField"] == "Opened")
    assert opened["status"] == "Completed"
    assert opened["actualDate"] == "2024-01-01"

def test_extract_milestones_priority_a_over_m():
    fields = [
        {"Key": "Opened(M)", "Value": "plan-date"},
        {"Key": "Opened(A)", "Value": "actual-date"},
    ]
    result = extract_milestones_from_customized_fields(fields, "SEA")
    opened = next(m for m in result if m["customField"] == "Opened")
    assert opened["actualDate"] == "actual-date"

# --- derive_status tests ---

def test_derive_status_active():
    milestones = build_milestones("SEA", "DTD", {}, {})
    status, statuses = derive_status(milestones, "SEA", "DTD")
    assert status == "Active"

def test_derive_status_delivered():
    actuals = {"Delivered": "2024-04-01T00:00:00Z"}
    milestones = build_milestones("SEA", "DTD", actuals, {})
    status, statuses = derive_status(milestones, "SEA", "DTD")
    assert status == "Delivered"

def test_derive_status_unknown_mode():
    status, statuses = derive_status([], "UNKNOWN", "DTD")
    assert status == "Active"

# --- get_last_completed_event tests ---

def test_get_last_completed_event():
    actuals = {"Opened": "2024-01-01T00:00:00Z", "ATD Custom": "2024-03-03T00:00:00Z"}
    dates = {"currentETD": "2024-03-01T00:00:00Z"}
    milestones = build_milestones("SEA", "DTD", actuals, dates)
    delay, actual_date, event = get_last_completed_event(milestones, "SEA", "DTD")
    assert event == "Sailed"
    assert delay == 2

def test_get_last_completed_event_none():
    milestones = build_milestones("SEA", "DTD", {}, {})
    delay, actual_date, event = get_last_completed_event(milestones, "SEA", "DTD")
    assert event is None

# --- extract_milestones_for_mode tests ---

def test_extract_milestones_for_mode_sea():
    mapping = extract_milestones_for_mode("SEA")
    assert "Opened" in mapping
    assert "ATD Custom" in mapping
    assert mapping["ATD Custom"] == "Sailed"

def test_extract_milestones_for_mode_air():
    mapping = extract_milestones_for_mode("AIR")
    assert "Picked" in mapping
    assert mapping["Picked"] == "Picked up"

def test_extract_milestones_for_mode_unknown():
    assert extract_milestones_for_mode("RAIL") == {}
