"""
Pure helper / utility functions extracted from new_milestones5.py.

These have zero side-effects and no dependency on config or DB.
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional


# ---------------------------
# Safe helpers (lines 68-141)
# ---------------------------
def safe_dict(obj: Any) -> Dict:
    return obj if isinstance(obj, dict) else {}


def safe_list(obj: Any) -> List:
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    return [obj]


def safe_text(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return None
    if isinstance(obj, list):
        try:
            return ",".join(str(x) for x in obj if x is not None)
        except Exception:
            return None
    s = str(obj).strip()
    return s if s != "" else None


def dump_json(obj: Any) -> Optional[str]:
    try:
        return json.dumps(obj, default=str) if obj is not None else None
    except Exception:
        try:
            return json.dumps(safe_dict(obj))
        except Exception:
            return None


def get_value(d: Dict, path: List[str]) -> Optional[str]:
    """Get nested value from dict `d` following path list, return safe_text or None."""
    try:
        for key in path:
            if isinstance(d, dict):
                d = d.get(key)
            else:
                return None
        return safe_text(d)
    except Exception:
        return None


def first_non_null(*args):
    for a in args:
        if a not in (None, "", []):
            return a
    return None


def format_port(port_obj: Any) -> Optional[str]:
    port = safe_dict(port_obj)
    name = safe_text(port.get("Name")) or safe_text(port.get("PortName"))
    code = safe_text(port.get("Code")) or safe_text(port.get("UNLocode"))
    if name and code:
        return f"{name}({code})"
    elif name:
        return name
    elif code:
        return f"({code})"
    return None


def format_address(addr_obj: Any) -> Optional[str]:
    addr = safe_dict(addr_obj)
    parts = [
        safe_text(addr.get("CompanyName")),
        safe_text(addr.get("Address1")),
        safe_text(addr.get("Address2")),
        safe_text(addr.get("City")),
        safe_text(addr.get("State")),
        safe_text(addr.get("Country")),
    ]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else None


# ---------------------------
# Date helpers (lines 267-345)
# ---------------------------
def parse_iso_dt(dt_str: Optional[str]) -> Optional[datetime]:
    """
    Robust ISO datetime parser.
    Fixes:
    - Handles timezone-less strings by assuming UTC (+00:00)
    - Handles strings with milliseconds or without
    - Never returns None due to simple formatting issues
    """
    if not dt_str:
        return None

    dt_str = str(dt_str).strip()

    # If no timezone exists, assume UTC
    if "Z" not in dt_str and "+" not in dt_str and "-" not in dt_str[10:]:
        dt_str = dt_str + "+00:00"

    # Convert trailing Z to +00:00
    if dt_str.endswith("Z"):
        dt_str = dt_str.replace("Z", "+00:00")

    # Try normal ISO format directly
    try:
        return datetime.fromisoformat(dt_str)
    except Exception:
        pass

    # Fallback formats
    fmts = [
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in fmts:
        try:
            dt = datetime.strptime(dt_str, fmt)

            # If tzinfo missing, attach UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            return dt
        except Exception:
            continue

    return None


def iso_str(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return None


def calculate_delay_days(planned: Optional[str], actual: Optional[str]) -> Optional[int]:
    """
    Safe delay calculation.
    Always uses parsed normalized dates.
    Returns delay in full days (rounded).
    """
    if not planned or not actual:
        return None

    planned_dt = parse_iso_dt(planned)
    actual_dt = parse_iso_dt(actual)

    if not planned_dt or not actual_dt:
        return None

    delta = actual_dt - planned_dt
    return delta.days


# ---------------------------
# Small helpers (lines 550-567)
# ---------------------------
def _planned_from_eta(currentETA: Optional[str], buffer_days: int) -> Optional[str]:
    """Return ISO planned datetime string from ETA + buffer or None."""
    if not currentETA:
        return None
    dt = parse_iso_dt(currentETA)
    if not dt:
        return None
    try:
        return iso_str(dt + timedelta(days=buffer_days))
    except Exception:
        return None


def _get_cf_date(milestones_list: List[Dict], cf_name: str) -> Optional[str]:
    """Helper: get actualDate by customField name (case-insensitive)."""
    for m in safe_list(milestones_list):
        if (m.get("customField") or "").strip().lower() == cf_name.strip().lower():
            return m.get("actualDate")
    return None
