# SEA Export Milestones Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give SEA Export shipments a dedicated milestone builder driven by an exact-match Custom Field lookup, isolated from AIR / SEA Import / SEA Foreign-to-Foreign behavior.

**Architecture:** Add a new `build_sea_export_milestones_reformed(customized_fields, job_opened_date)` function to `pipeline/milestones.py` that reads exactly the 13 CargoWise Custom Field keys for SEA Export and emits the 7-event `SEQUENCES["SEA_EXPORT"]` sequence. Add a one-line dispatch guard at the top of the existing `build_milestones_reformed` that routes SEA + Export calls to the new function. All prerequisites (sequence, `_is_sea_export`, `_resolve_sequence`, `trade_type` kwargs, `processing.py` wiring) already exist on `sea-export-functionality`.

**Tech Stack:** Python 3, pytest.

## Global Constraints

- **Branch:** `sea-export-functionality` (already checked out).
- **Isolation:** AIR, SEA Import, and SEA Foreign-to-Foreign call paths must remain byte-identical in behavior. Any test change that alters non-SEA-Export output means a bug has been introduced.
- **No refactor of shared parser body.** The existing SEA-Export branch at `pipeline/milestones.py:1714` (`elif is_export and not clean.startswith("Est"):`) stays in place — it becomes dead code but removing it is out of scope.
- **No cleanup of commented-out history.** ~900 lines of legacy commented blocks in `milestones.py` stay as-is.
- **Reference:** `docs/superpowers/specs/2026-07-06-sea-export-milestones-design.md` is the source of truth for the 7-milestone target and 13-field lookup.
- **No changes to** `SEQUENCES["SEA_EXPORT"]`, `PLANNED_FIELD_MAP`, `_is_sea_export`, `_resolve_sequence`, `build_milestones`, `derive_status`, `get_last_completed_event`, `parser.py`, or `processing.py`.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `pipeline/milestones.py` | Modify | Add `build_sea_export_milestones_reformed`; add dispatch guard in `build_milestones_reformed`. |
| `tests/test_milestones_sea_export.py` | Create | Nine unit tests covering happy path, missing actuals, Excel fallback, whitespace tolerance, unknown-key isolation, SEA Import dispatch, AIR dispatch, ATD delay math, intermediate-row delay math. |

---

### Task 1: Add `build_sea_export_milestones_reformed` (TDD)

**Files:**
- Create: `tests/test_milestones_sea_export.py`
- Modify: `pipeline/milestones.py` (insert new function immediately above `build_milestones_reformed` at line 1617)

**Interfaces:**
- Consumes (existing): `SEQUENCES["SEA_EXPORT"]`, `safe_list`, `safe_text` (from `pipeline.helpers`), `calculate_delay_days` (from `pipeline.helpers`).
- Produces: `build_sea_export_milestones_reformed(customized_fields: list, job_opened_date: str | None = None) -> list[dict]`. Each dict has keys `eventStatus`, `customField`, `plannedDate`, `actualDate`, `status`, `delay`.

- [ ] **Step 1: Create the test file with the happy-path test**

Create `tests/test_milestones_sea_export.py` with this initial content:

```python
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
```

- [ ] **Step 2: Run test to verify it fails (function does not exist yet)**

Run: `python -m pytest tests/test_milestones_sea_export.py::test_happy_path_all_13_fields -v`
Expected: FAIL with `ImportError: cannot import name 'build_sea_export_milestones_reformed'`.

- [ ] **Step 3: Add the new function to `pipeline/milestones.py`**

Insert this function into `pipeline/milestones.py` immediately BEFORE the line `def build_milestones_reformed(transport_mode, service_level, customized_fields , job_opened_date=None, trade_type=None):` (currently at line 1617):

```python
# ---------------------------------------------------------------------------
# SEA EXPORT — DEDICATED BUILDER
# ---------------------------------------------------------------------------

_SEA_EXPORT_FIELD_MAP = {
    # Estimated Milestones -> planned_map
    "ETD Custom(A)":        ("planned", "ATD Custom"),
    "ETA Custom(A)":        ("planned", "ATA Custom"),
    "Est. Pick up Date(M)": ("planned", "Pick up Date"),
    "Est. Gate In Rail(M)": ("planned", "Gate In Rail"),
    "Est. Gate In Port(M)": ("planned", "Gate In Port"),
    "Est. Delivery(M)":     ("planned", "Delivered"),
    # Actual Milestones -> actual_map
    "Opened(A)":       ("actual", "Opened"),
    "Pick up Date(M)": ("actual", "Pick up Date"),
    "Gate In Rail(M)": ("actual", "Gate In Rail"),
    "Gate In Port(A)": ("actual", "Gate In Port"),
    "ATD Custom(A)":   ("actual", "ATD Custom"),
    "ATA Custom(A)":   ("actual", "ATA Custom"),
    "Delivered(A)":    ("actual", "Delivered"),
}


def build_sea_export_milestones_reformed(customized_fields, job_opened_date=None):
    """Build SEA Export milestones from CargoWise Custom Fields.

    Uses an exact-match lookup on the 13 known SEA Export Custom Field keys;
    ignores every other key. Emits the 7-event SEQUENCES["SEA_EXPORT"] sequence
    with status, planned/actual dates, and per-row delay.
    """
    actual_map = {}
    planned_map = {}

    for field in safe_list(customized_fields):
        key = safe_text(field.get("Key"))
        value = safe_text(field.get("Value"))
        if not key or not value:
            continue
        key = key.replace("( A )", "(A)").replace("( M )", "(M)").strip()
        mapping = _SEA_EXPORT_FIELD_MAP.get(key)
        if not mapping:
            continue
        target, canonical = mapping
        if target == "actual":
            actual_map[canonical] = value
        else:
            planned_map[canonical] = value

    if not actual_map.get("Opened") and job_opened_date:
        actual_map["Opened"] = job_opened_date

    milestones = []
    for cf_key, label, _, _ in SEQUENCES["SEA_EXPORT"]:
        actual = actual_map.get(cf_key)
        planned = planned_map.get(cf_key)
        delay = calculate_delay_days(planned, actual) if actual and planned else None
        milestones.append({
            "eventStatus": label,
            "customField": cf_key,
            "plannedDate": planned,
            "actualDate": actual,
            "status": "Completed" if actual else "Pending",
            "delay": delay,
        })
    return milestones
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_milestones_sea_export.py::test_happy_path_all_13_fields -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/milestones.py tests/test_milestones_sea_export.py
git commit -m "$(cat <<'EOF'
feat: dedicated SEA Export milestone builder

Add build_sea_export_milestones_reformed which uses an exact-match
lookup on the 13 CargoWise Custom Field keys for SEA Export and emits
the 7-event SEQUENCES["SEA_EXPORT"] sequence. Not yet dispatched from
build_milestones_reformed — dispatch guard is a follow-up task.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Add remaining unit tests (edge cases)

**Files:**
- Modify: `tests/test_milestones_sea_export.py`

**Interfaces:**
- Consumes: `build_sea_export_milestones_reformed` (from Task 1).

- [ ] **Step 1: Add the eight remaining test cases**

Append these tests to `tests/test_milestones_sea_export.py`:

```python
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
```

- [ ] **Step 2: Run all SEA Export tests**

Run: `python -m pytest tests/test_milestones_sea_export.py -v`
Expected: 9 tests pass (including happy path from Task 1 and 8 new).

- [ ] **Step 3: Commit**

```bash
git add tests/test_milestones_sea_export.py
git commit -m "$(cat <<'EOF'
test: edge cases for SEA Export milestone builder

Cover missing actuals, Excel fallback (present and does-not-override),
whitespace tolerance, unknown-key isolation, delay math on ATD and
intermediate rows, empty-value skip.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Add dispatch guard + isolation tests (TDD)

**Files:**
- Modify: `pipeline/milestones.py` (insert three lines into `build_milestones_reformed` at line 1622)
- Modify: `tests/test_milestones_sea_export.py`

**Interfaces:**
- Consumes: `build_milestones_reformed`, `build_sea_export_milestones_reformed`, `SEQUENCES` (existing).

- [ ] **Step 1: Write the dispatch-isolation tests first**

Append to `tests/test_milestones_sea_export.py`:

```python
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
    # SEA (Import) sequence has 9 events including "Loaded" and "Discharged" —
    # SEA_EXPORT sequence has neither.
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
```

- [ ] **Step 2: Run dispatch tests to see them fail**

Run: `python -m pytest tests/test_milestones_sea_export.py::test_dispatch_routes_sea_export_to_dedicated_builder -v`
Expected: FAIL. Reason: `build_milestones_reformed` currently uses the shared parser body for SEA + Export too. Depending on the current SEA Export branch's parser output, the test might pass by coincidence, but the sequence length assertion still validates behavior. Note the actual failure mode; if it PASSES, that just means the shared parser is already producing the same 7 milestones — proceed to Step 3 anyway to lock in the dedicated dispatch.

- [ ] **Step 3: Add the dispatch guard to `build_milestones_reformed`**

In `pipeline/milestones.py`, edit `build_milestones_reformed`. Currently line 1621-1624 reads:

```python
    if not transport_mode:
        return []

    is_export = _is_sea_export(transport_mode, trade_type)
```

Change it to:

```python
    if not transport_mode:
        return []

    if _is_sea_export(transport_mode, trade_type):
        return build_sea_export_milestones_reformed(customized_fields, job_opened_date)

    is_export = _is_sea_export(transport_mode, trade_type)
```

The pre-existing `is_export = ...` line stays untouched — the branch inside the shared body becomes unreachable for SEA Export shipments but is left in place per the Global Constraints.

- [ ] **Step 4: Run all SEA Export tests to confirm dispatch works**

Run: `python -m pytest tests/test_milestones_sea_export.py -v`
Expected: All 13 tests pass (9 builder tests + 4 dispatch tests).

- [ ] **Step 5: Run the full pipeline test suite to prove no regressions**

Run: `python -m pytest tests/ -v --ignore=tests/test_integration.py`
Expected: No new failures introduced by this branch (pre-existing failures in `test_milestones.py` from the older `(mode, service_level)`-tuple tests may still fail — that is out of scope and pre-existing). Compare against `git stash && python -m pytest tests/ ... && git stash pop` if you want to be sure the failure delta is zero.

- [ ] **Step 6: Commit**

```bash
git add pipeline/milestones.py tests/test_milestones_sea_export.py
git commit -m "$(cat <<'EOF'
feat: dispatch SEA Export shipments to dedicated builder

build_milestones_reformed now returns
build_sea_export_milestones_reformed(...) when the shipment is SEA +
Export. AIR, SEA Import, and SEA Foreign-to-Foreign paths keep using
the shared parser body and are unchanged. Regression-tested with four
dispatch-isolation tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- Spec section 4 (7-milestone target) → Task 1 Step 1 test `test_happy_path_all_13_fields` asserts every row.
- Spec section 5.1 (new function) → Task 1 Step 3 adds it.
- Spec section 5.2 (field lookup table) → Task 1 Step 3, `_SEA_EXPORT_FIELD_MAP`.
- Spec section 5.3 (parsing rules) → Task 1 Step 3 (whitespace normalization + empty skip) + Task 2 tests (`test_whitespace_tolerance_in_field_keys`, `test_empty_value_fields_are_skipped`).
- Spec section 5.4 (Excel fallback) → Task 1 Step 3 code + Task 2 tests (`test_excel_fallback_for_opened`, `test_excel_fallback_does_not_override_actual_opened`).
- Spec section 5.5 (assembly) → Task 1 Step 3 code + Task 2 delay tests.
- Spec section 5.6 (dispatch) → Task 3 Step 3.
- Spec section 6 (wiring) → No task needed; already live.
- Spec section 7 tests 1-9 → Covered by Tasks 1 & 2 (9 tests) plus Task 3's four dispatch-isolation tests (which cover spec tests 6, 7 more thoroughly).
- Spec section 8 (risks) → Task 3 Step 5 full-suite regression check mitigates dispatch-order risk.

**Placeholder scan:** No TBDs, TODOs, or "add appropriate X" phrases. Every code block is complete.

**Type consistency:** `build_sea_export_milestones_reformed` has the same `(customized_fields, job_opened_date)` signature everywhere it appears (definition Task 1, call site Task 3). All field-map values are `(target: str, canonical: str)` tuples throughout.
