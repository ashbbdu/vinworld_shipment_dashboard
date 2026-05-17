"""Tests for pipeline.helpers — pure functions with no side-effects."""

import pytest
from datetime import datetime, timezone, timedelta

from pipeline.helpers import (
    safe_dict,
    safe_list,
    safe_text,
    dump_json,
    get_value,
    first_non_null,
    format_port,
    format_address,
    parse_iso_dt,
    iso_str,
    calculate_delay_days,
    _planned_from_eta,
    _get_cf_date,
)


# ------------------------------------------------------------------ #
# safe_dict
# ------------------------------------------------------------------ #
class TestSafeDict:
    def test_dict_passthrough(self):
        d = {"a": 1}
        assert safe_dict(d) is d

    def test_non_dict_returns_empty(self):
        assert safe_dict(None) == {}
        assert safe_dict("hello") == {}
        assert safe_dict([1, 2]) == {}
        assert safe_dict(42) == {}


# ------------------------------------------------------------------ #
# safe_list
# ------------------------------------------------------------------ #
class TestSafeList:
    def test_none_returns_empty(self):
        assert safe_list(None) == []

    def test_list_passthrough(self):
        lst = [1, 2]
        assert safe_list(lst) is lst

    def test_scalar_wrapped(self):
        assert safe_list("abc") == ["abc"]
        assert safe_list(42) == [42]
        assert safe_list({"k": "v"}) == [{"k": "v"}]


# ------------------------------------------------------------------ #
# safe_text
# ------------------------------------------------------------------ #
class TestSafeText:
    def test_none(self):
        assert safe_text(None) is None

    def test_dict_returns_none(self):
        assert safe_text({"a": 1}) is None

    def test_list_joins(self):
        assert safe_text(["a", "b"]) == "a,b"

    def test_list_skips_none(self):
        assert safe_text(["a", None, "b"]) == "a,b"

    def test_string_stripped(self):
        assert safe_text("  hello  ") == "hello"

    def test_empty_string(self):
        assert safe_text("") is None
        assert safe_text("   ") is None

    def test_number(self):
        assert safe_text(42) == "42"


# ------------------------------------------------------------------ #
# get_value
# ------------------------------------------------------------------ #
class TestGetValue:
    def test_nested_path(self):
        d = {"a": {"b": {"c": "deep"}}}
        assert get_value(d, ["a", "b", "c"]) == "deep"

    def test_missing_key(self):
        assert get_value({"a": 1}, ["b"]) is None

    def test_non_dict_in_path(self):
        assert get_value({"a": "string"}, ["a", "b"]) is None

    def test_empty_path(self):
        assert get_value({"a": 1}, []) is None  # safe_text on dict returns None


# ------------------------------------------------------------------ #
# first_non_null
# ------------------------------------------------------------------ #
class TestFirstNonNull:
    def test_returns_first_truthy(self):
        assert first_non_null(None, "", "ok", "later") == "ok"

    def test_all_null(self):
        assert first_non_null(None, "", []) is None

    def test_zero_is_returned(self):
        assert first_non_null(None, 0) == 0

    def test_empty_list_skipped(self):
        assert first_non_null([], [1]) == [1]


# ------------------------------------------------------------------ #
# format_port
# ------------------------------------------------------------------ #
class TestFormatPort:
    def test_name_and_code(self):
        assert format_port({"Name": "Shanghai", "Code": "CNSHA"}) == "Shanghai(CNSHA)"

    def test_portname_and_unlocode(self):
        assert format_port({"PortName": "LA", "UNLocode": "USLAX"}) == "LA(USLAX)"

    def test_name_only(self):
        assert format_port({"Name": "Shanghai"}) == "Shanghai"

    def test_code_only(self):
        assert format_port({"Code": "CNSHA"}) == "(CNSHA)"

    def test_empty(self):
        assert format_port({}) is None
        assert format_port(None) is None


# ------------------------------------------------------------------ #
# parse_iso_dt
# ------------------------------------------------------------------ #
class TestParseIsoDt:
    def test_none_empty(self):
        assert parse_iso_dt(None) is None
        assert parse_iso_dt("") is None

    def test_iso_with_z(self):
        result = parse_iso_dt("2024-01-15T10:30:00Z")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.tzinfo is not None

    def test_iso_with_offset(self):
        result = parse_iso_dt("2024-06-01T12:00:00+05:30")
        assert result is not None
        assert result.hour == 12

    def test_iso_no_tz_gets_utc(self):
        result = parse_iso_dt("2024-01-15T10:30:00")
        assert result is not None
        assert result.tzinfo is not None  # UTC attached

    def test_space_separated(self):
        result = parse_iso_dt("2024-01-15 10:30:00")
        assert result is not None

    def test_garbage_returns_none(self):
        assert parse_iso_dt("not-a-date") is None


# ------------------------------------------------------------------ #
# calculate_delay_days
# ------------------------------------------------------------------ #
class TestCalculateDelayDays:
    def test_positive_delay(self):
        assert calculate_delay_days("2024-01-01T00:00:00Z", "2024-01-04T00:00:00Z") == 3

    def test_negative_delay(self):
        assert calculate_delay_days("2024-01-04T00:00:00Z", "2024-01-01T00:00:00Z") == -3

    def test_zero_delay(self):
        assert calculate_delay_days("2024-01-01T12:00:00Z", "2024-01-01T12:00:00Z") == 0

    def test_none_inputs(self):
        assert calculate_delay_days(None, "2024-01-01T00:00:00Z") is None
        assert calculate_delay_days("2024-01-01T00:00:00Z", None) is None
        assert calculate_delay_days(None, None) is None

    def test_garbage_input(self):
        assert calculate_delay_days("bad", "2024-01-01T00:00:00Z") is None


# ------------------------------------------------------------------ #
# _planned_from_eta
# ------------------------------------------------------------------ #
class TestPlannedFromEta:
    def test_adds_buffer(self):
        result = _planned_from_eta("2024-01-10T00:00:00Z", 4)
        dt = parse_iso_dt(result)
        assert dt.day == 14

    def test_none_eta(self):
        assert _planned_from_eta(None, 4) is None

    def test_bad_eta(self):
        assert _planned_from_eta("not-a-date", 4) is None


# ------------------------------------------------------------------ #
# _get_cf_date
# ------------------------------------------------------------------ #
class TestGetCfDate:
    def test_finds_match(self):
        milestones = [
            {"customField": "Pickup", "actualDate": "2024-01-01"},
            {"customField": "Delivery", "actualDate": "2024-01-05"},
        ]
        assert _get_cf_date(milestones, "delivery") == "2024-01-05"

    def test_case_insensitive(self):
        milestones = [{"customField": "PICKUP", "actualDate": "2024-01-01"}]
        assert _get_cf_date(milestones, "pickup") == "2024-01-01"

    def test_no_match(self):
        assert _get_cf_date([{"customField": "X"}], "Y") is None

    def test_empty_list(self):
        assert _get_cf_date([], "anything") is None

    def test_none_input(self):
        assert _get_cf_date(None, "anything") is None
