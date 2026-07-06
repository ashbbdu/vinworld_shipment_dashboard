"""Tests for SEA Export milestone builder — isolated from other transport modes."""

import pytest

from pipeline.milestones import (
    build_sea_export_milestones_reformed,
    build_milestones_reformed,
    SEQUENCES,
)


def _fields(pairs):
    """Turn a list of (key, value) tuples into CargoWise CustomizedField dicts."""
    return [{"Key": k, "Value": v} for k, v in pairs]


SEA_EXPORT_FULL_FIELDS = [
    ("ETD Custom(A)",        "2026-06-01T00:00:00Z"),
    ("ETA Custom(A)",        "2026-06-20T00:00:00Z"),
    ("Est. Pick up Date(M)", "2026-05-20T00:00:00Z"),
    ("Est. Gate In Rail(M)", "2026-05-22T00:00:00Z"),
    ("Est. Gate In Port(M)", "2026-05-28T00:00:00Z"),
    ("Est. Delivery(M)",     "2026-06-24T00:00:00Z"),
    ("Opened(A)",            "2026-05-15T00:00:00Z"),
    ("Pick up Date(M)",      "2026-05-21T00:00:00Z"),
    ("Gate In Rail(M)",      "2026-05-23T00:00:00Z"),
    ("Gate In Port(A)",      "2026-05-29T00:00:00Z"),
    ("ATD Custom(A)",        "2026-06-04T00:00:00Z"),
    ("ATA Custom(A)",        "2026-06-22T00:00:00Z"),
    ("Delivered(A)",         "2026-06-26T00:00:00Z"),
]


def test_happy_path_all_13_fields():
    result = build_sea_export_milestones_reformed(_fields(SEA_EXPORT_FULL_FIELDS))

    assert len(result) == 7
    assert [m["customField"] for m in result] == [
        "Opened", "Pick up Date", "Gate In Rail", "Gate In Port",
        "ATD Custom", "ATA Custom", "Delivered",
    ]
    assert [m["eventStatus"] for m in result] == [
        "Opened", "Picked up", "Loaded on Rail", "Gate In Port",
        "Sailed", "Arrived", "Delivered",
    ]
    assert all(m["status"] == "Completed" for m in result)

    by_cf = {m["customField"]: m for m in result}
    assert by_cf["Opened"]["actualDate"] == "2026-05-15T00:00:00Z"
    assert by_cf["Pick up Date"]["actualDate"] == "2026-05-21T00:00:00Z"
    assert by_cf["Pick up Date"]["plannedDate"] == "2026-05-20T00:00:00Z"
    assert by_cf["Gate In Rail"]["actualDate"] == "2026-05-23T00:00:00Z"
    assert by_cf["Gate In Rail"]["plannedDate"] == "2026-05-22T00:00:00Z"
    assert by_cf["Gate In Port"]["actualDate"] == "2026-05-29T00:00:00Z"
    assert by_cf["Gate In Port"]["plannedDate"] == "2026-05-28T00:00:00Z"
    assert by_cf["ATD Custom"]["actualDate"] == "2026-06-04T00:00:00Z"
    assert by_cf["ATD Custom"]["plannedDate"] == "2026-06-01T00:00:00Z"
    assert by_cf["ATA Custom"]["actualDate"] == "2026-06-22T00:00:00Z"
    assert by_cf["ATA Custom"]["plannedDate"] == "2026-06-20T00:00:00Z"
    assert by_cf["Delivered"]["actualDate"] == "2026-06-26T00:00:00Z"
    assert by_cf["Delivered"]["plannedDate"] == "2026-06-24T00:00:00Z"


def test_missing_actuals_all_pending():
    fields = _fields([
        ("ETD Custom(A)",        "2026-06-01T00:00:00Z"),
        ("ETA Custom(A)",        "2026-06-20T00:00:00Z"),
        ("Est. Pick up Date(M)", "2026-05-20T00:00:00Z"),
        ("Est. Gate In Rail(M)", "2026-05-22T00:00:00Z"),
        ("Est. Gate In Port(M)", "2026-05-28T00:00:00Z"),
        ("Est. Delivery(M)",     "2026-06-24T00:00:00Z"),
    ])
    result = build_sea_export_milestones_reformed(fields)

    assert len(result) == 7
    assert all(m["status"] == "Pending" for m in result)
    assert all(m["actualDate"] is None for m in result)
    assert all(m["delay"] is None for m in result)

    by_cf = {m["customField"]: m for m in result}
    assert by_cf["ATD Custom"]["plannedDate"] == "2026-06-01T00:00:00Z"
    assert by_cf["Delivered"]["plannedDate"] == "2026-06-24T00:00:00Z"
    assert by_cf["Opened"]["plannedDate"] is None


def test_excel_fallback_for_opened():
    fields = _fields([("Delivered(A)", "2026-06-26T00:00:00Z")])
    result = build_sea_export_milestones_reformed(
        fields, job_opened_date="2026-07-01T00:00:00Z"
    )
    by_cf = {m["customField"]: m for m in result}
    assert by_cf["Opened"]["actualDate"] == "2026-07-01T00:00:00Z"
    assert by_cf["Opened"]["status"] == "Completed"


def test_excel_fallback_does_not_override_actual_opened():
    fields = _fields([("Opened(A)", "2026-05-15T00:00:00Z")])
    result = build_sea_export_milestones_reformed(
        fields, job_opened_date="2026-07-01T00:00:00Z"
    )
    by_cf = {m["customField"]: m for m in result}
    assert by_cf["Opened"]["actualDate"] == "2026-05-15T00:00:00Z"


def test_whitespace_tolerance_in_field_keys():
    fields = _fields([
        ("ETD Custom( A )", "2026-06-01T00:00:00Z"),
        ("ATD Custom( A )", "2026-06-04T00:00:00Z"),
    ])
    result = build_sea_export_milestones_reformed(fields)
    by_cf = {m["customField"]: m for m in result}
    assert by_cf["ATD Custom"]["actualDate"] == "2026-06-04T00:00:00Z"
    assert by_cf["ATD Custom"]["plannedDate"] == "2026-06-01T00:00:00Z"


def test_unknown_keys_silently_ignored():
    fields = _fields([
        ("Opened(A)",              "2026-05-15T00:00:00Z"),
        ("Some Other Field(A)",    "2026-05-16T00:00:00Z"),
        ("Discharged(A)",          "2026-06-25T00:00:00Z"),
    ])
    result = build_sea_export_milestones_reformed(fields)
    assert len(result) == 7
    assert all(m["customField"] != "Some Other Field" for m in result)
    assert all(m["customField"] != "Discharged" for m in result)


def test_delay_on_atd_row():
    fields = _fields([
        ("ETD Custom(A)", "2026-06-01T00:00:00Z"),
        ("ATD Custom(A)", "2026-06-04T00:00:00Z"),
    ])
    result = build_sea_export_milestones_reformed(fields)
    by_cf = {m["customField"]: m for m in result}
    assert by_cf["ATD Custom"]["delay"] == 3


def test_delay_on_intermediate_gate_in_rail_row():
    fields = _fields([
        ("Est. Gate In Rail(M)", "2026-06-01T00:00:00Z"),
        ("Gate In Rail(M)",      "2026-06-03T00:00:00Z"),
    ])
    result = build_sea_export_milestones_reformed(fields)
    by_cf = {m["customField"]: m for m in result}
    assert by_cf["Gate In Rail"]["delay"] == 2


def test_empty_value_fields_are_skipped():
    fields = _fields([
        ("Opened(A)", ""),
        ("ATD Custom(A)", "2026-06-04T00:00:00Z"),
    ])
    result = build_sea_export_milestones_reformed(fields)
    by_cf = {m["customField"]: m for m in result}
    assert by_cf["Opened"]["actualDate"] is None
    assert by_cf["ATD Custom"]["actualDate"] == "2026-06-04T00:00:00Z"


# ---------------------------------------------------------------------------
# DISPATCH GUARD: only SEA + Export reaches the dedicated builder.
# ---------------------------------------------------------------------------

def test_dispatch_routes_sea_export_to_dedicated_builder():
    """SEA + Export -> 7 milestones from SEQUENCES['SEA_EXPORT']."""
    result = build_milestones_reformed(
        transport_mode="SEA",
        service_level=None,
        customized_fields=_fields(SEA_EXPORT_FULL_FIELDS),
        job_opened_date=None,
        trade_type="Export",
    )
    assert len(result) == 7
    assert [m["customField"] for m in result] == [cf for cf, *_ in SEQUENCES["SEA_EXPORT"]]
    # Sanity: the SEA_EXPORT sequence uses "Pick up Date", the SEA sequence does not.
    assert any(m["customField"] == "Pick up Date" for m in result)
    assert not any(m["customField"] == "Loaded" for m in result)


def test_dispatch_sea_import_uses_shared_sea_sequence():
    """SEA + Import must NOT reach the SEA Export builder."""
    result = build_milestones_reformed(
        transport_mode="SEA",
        service_level=None,
        customized_fields=_fields(SEA_EXPORT_FULL_FIELDS),
        job_opened_date=None,
        trade_type="Import",
    )
    assert len(result) == len(SEQUENCES["SEA"])
    cf_keys = [m["customField"] for m in result]
    assert "Loaded" in cf_keys
    assert "Discharged" in cf_keys
    assert "Pick up Date" not in cf_keys


def test_dispatch_air_export_uses_air_sequence():
    """AIR + Export must NOT reach the SEA Export builder."""
    result = build_milestones_reformed(
        transport_mode="AIR",
        service_level=None,
        customized_fields=_fields(SEA_EXPORT_FULL_FIELDS),
        job_opened_date=None,
        trade_type="Export",
    )
    assert len(result) == len(SEQUENCES["AIR"])
    cf_keys = [m["customField"] for m in result]
    assert "ATA Transit" in cf_keys
    assert "Pick up Date" not in cf_keys


def test_dispatch_sea_foreign_to_foreign_uses_shared_sea_sequence():
    """SEA + Foreign To Foreign must NOT reach the SEA Export builder."""
    result = build_milestones_reformed(
        transport_mode="SEA",
        service_level=None,
        customized_fields=_fields(SEA_EXPORT_FULL_FIELDS),
        job_opened_date=None,
        trade_type="Foreign To Foreign",
    )
    assert len(result) == len(SEQUENCES["SEA"])
    cf_keys = [m["customField"] for m in result]
    assert "Loaded" in cf_keys
