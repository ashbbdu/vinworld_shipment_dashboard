# SEA Export Milestones — Design

**Date:** 2026-07-06
**Branch:** `sea-export-functionality`
**Author:** Claude Code brainstorming session
**Status:** Awaiting user review

## 1. Problem

CargoWise SEA Export shipments publish a distinct set of Custom Fields that do not match the SEA Import / Foreign-to-Foreign layout. The current `build_milestones_reformed` in `pipeline/milestones.py` uses shared heuristics — an `(A)`/`(M)` suffix parser with a SEA-Export-specific branch at line 1714 — to route fields into `actual_map` / `planned_map`. That branch is entangled with logic used by every other mode, which makes SEA Export brittle: any future change to the shared parser can silently regress SEA Export, and any SEA-Export-specific requirement risks side effects on AIR / SEA Import.

## 2. Goal

Give SEA Export its own dedicated milestone builder that:

- Reads exactly the 13 CargoWise Custom Field keys shown in the reference screenshot (nothing else).
- Produces the fixed 7-event `SEA_EXPORT` sequence already defined in `SEQUENCES`.
- Runs **only** when `transport_mode == "SEA"` and `trade_type == "Export"`.
- Leaves AIR, SEA Import, and SEA Foreign-to-Foreign code paths byte-identical in behavior.

## 3. Non-goals

- No changes to the `SEQUENCES["SEA_EXPORT"]` list — it already matches the target.
- No changes to `build_milestones` (the "raw actuals" builder used elsewhere).
- No refactor of the shared `build_milestones_reformed` beyond adding a one-line dispatch at the top.
- No new tests infrastructure — reuse the existing `tests/` pytest layout.
- No cleanup of the ~900 lines of commented-out history in `milestones.py`.

## 4. Target milestone output

For any SEA Export shipment, the builder emits exactly these 7 milestones, in this order:

| # | `customField` | `eventStatus` | Actual source (Custom Field key) | Planned source (Custom Field key) |
|---|---|---|---|---|
| 1 | `Opened` | Opened | `Opened(A)` (fallback: Excel `Job Opened` date) | — |
| 2 | `Pick up Date` | Picked up | `Pick up Date(M)` | `Est. Pick up Date(M)` |
| 3 | `Gate In Rail` | Loaded on Rail | `Gate In Rail(M)` | `Est. Gate In Rail(M)` |
| 4 | `Gate In Port` | Gate In Port | `Gate In Port(A)` | `Est. Gate In Port(M)` |
| 5 | `ATD Custom` | Sailed | `ATD Custom(A)` | `ETD Custom(A)` |
| 6 | `ATA Custom` | Arrived | `ATA Custom(A)` | `ETA Custom(A)` |
| 7 | `Delivered` | Delivered | `Delivered(A)` | `Est. Delivery(M)` |

Notes:
- **Delay** is computed via `calculate_delay_days(planned, actual)` for **every** row where both `actual` and `planned` are present; otherwise `delay = None`. This matches the current `build_milestones_reformed` behavior — the `calc_delay` bool in the `SEQUENCES` tuple is consulted only by the raw `build_milestones`, not by the reformed builder.
- `status` is `"Completed"` when `actual` is truthy, else `"Pending"`.
- Rows 2 and 3 have `(M)`-suffixed **actuals** — this is intentional and matches the CargoWise convention shown in the screenshot. It is the key reason SEA Export cannot share the generic parser cleanly.
- Row 1 (`Opened`) has no planned source and therefore always has `delay = None`.

## 5. Design

### 5.0 Prerequisites (add if not already present)

The current branch (`sea-export-milestones`) does not have the SEA Export scaffolding that exists on `sea-export-functionality`. This spec therefore introduces all of it fresh, so implementation is self-contained.

Add to `pipeline/milestones.py`:

**A. `SEQUENCES["SEA_EXPORT"]`** — the 7-event sequence:

```python
"SEA_EXPORT": [
    ("Opened",       "Opened",         None,         False),
    ("Pick up Date", "Picked up",      None,         False),
    ("Gate In Rail", "Loaded on Rail", None,         False),
    ("Gate In Port", "Gate In Port",   None,         False),
    ("ATD Custom",   "Sailed",         "etd",        True),
    ("ATA Custom",   "Arrived",        "eta",        True),
    ("Delivered",    "Delivered",      "eta_buffer", True),
],
```

**B. `_is_sea_export` helper:**

```python
def _is_sea_export(transport_mode, trade_type):
    return (transport_mode or "").upper() == "SEA" and \
        (trade_type or "").strip().lower() == "export"
```

**C. `_resolve_sequence` helper** used by `build_milestones`, `derive_status`, `get_last_completed_event`:

```python
def _resolve_sequence(transport_mode, trade_type):
    mode = (transport_mode or "").upper()
    if _is_sea_export(mode, trade_type):
        return SEQUENCES.get("SEA_EXPORT", [])
    return SEQUENCES.get(mode, [])
```

**D. Add `trade_type=None` kwarg** to `build_milestones`, `derive_status`, `get_last_completed_event`, `build_milestones_reformed`, and `extract_milestones_from_customized_fields`. Each uses `_resolve_sequence(mode, trade_type)` in place of `SEQUENCES.get(mode)`.

**E. Thread `trade_type` through `pipeline/jobs/processing.py`** — read `record.get("tradeType")` and pass to each milestone call. `parser.py` already sets `tradeType` at line 255.

### 5.1 New public function

Add `build_sea_export_milestones_reformed` to `pipeline/milestones.py`, placed immediately above the existing `build_milestones_reformed` definition.

```python
def build_sea_export_milestones_reformed(customized_fields, job_opened_date=None):
    """
    Build SEA Export milestones from CargoWise Custom Fields.

    Uses an exact-match lookup on the 13 known SEA Export Custom Field keys;
    ignores every other key. Emits the 7-event SEQUENCES["SEA_EXPORT"] sequence
    with status, planned/actual dates, and delay filled in.

    Called only when transport_mode == "SEA" and trade_type == "Export"
    (see build_milestones_reformed dispatch).
    """
```

### 5.2 Field lookup table

A single dict, defined inside the function, mapping each expected Custom Field label to `(target_map, canonical_customField_key)`:

```python
SEA_EXPORT_FIELD_MAP = {
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
```

Any incoming Custom Field key not present in this table is ignored. This is intentional — SEA Export shipments should not be affected by future new field types added by CargoWise for other modes.

### 5.3 Parsing rules

- Normalize each incoming key with `.replace("( A )", "(A)").replace("( M )", "(M)").strip()` — matching the whitespace tolerance of the existing generic parser.
- Skip a field if either `Key` or `Value` is empty.
- On exact match: write `value` into either `actual_map` or `planned_map` under the canonical key. Last-writer-wins if the same field appears twice (matches current behavior).

### 5.4 Excel fallback for `Opened`

Preserved from current behavior:

```python
if not actual_map.get("Opened") and job_opened_date:
    actual_map["Opened"] = job_opened_date
```

### 5.5 Milestone assembly

Iterate `SEQUENCES["SEA_EXPORT"]` in order. For each `(cf_key, label, _, _)`:

- `actual  = actual_map.get(cf_key)`
- `planned = planned_map.get(cf_key)`
- `delay   = calculate_delay_days(planned, actual) if actual and planned else None`
- Append the milestone dict with the same shape as `build_milestones_reformed`.

`PLANNED_FIELD_MAP` is **not** consulted by this function — the field-lookup table already resolves the planned key to the correct canonical name.

### 5.6 Dispatch

Modify `build_milestones_reformed` at `pipeline/milestones.py:1617` with a single guard at the very top of the function, after the empty-mode check:

```python
def build_milestones_reformed(transport_mode, service_level, customized_fields,
                              job_opened_date=None, trade_type=None):
    transport_mode = (transport_mode or "").upper()
    if not transport_mode:
        return []

    if _is_sea_export(transport_mode, trade_type):
        return build_sea_export_milestones_reformed(customized_fields, job_opened_date)

    # ... existing body unchanged ...
```

The pre-existing SEA-Export branch inside the shared body (`milestones.py:1714`, the `elif is_export and not clean.startswith("Est"):` block) becomes dead code but stays in place — removing it is out of scope for this change to minimize diff.

## 6. Wiring

On `sea-export-functionality`, `processing.py` already reads `trade_type` and passes it through. On `sea-export-milestones` (current branch) that wiring does not exist yet and is part of prerequisite (E) above. Once added:

```python
trade_type = record.get("tradeType")  # already set by parser.py:255
...
milestones_reformed = build_milestones_reformed(
    transport_mode, service_level, customized_fields, job_opened_date,
    trade_type=trade_type,
)
```

Same `trade_type` kwarg is passed to `build_milestones`, `derive_status`, and `get_last_completed_event`.

## 7. Testing

Add `tests/test_milestones_sea_export.py` with these cases:

1. **Happy path — all 13 fields present.** Construct a `customized_fields` list matching the screenshot exactly. Assert the returned list has 7 milestones in the expected order, with correct `customField`, `eventStatus`, `plannedDate`, `actualDate`, `status`, and `delay` values.
2. **Missing actuals.** Include only Estimated Milestone fields. Assert every milestone has `status == "Pending"` and `actualDate is None`, planned dates populated, `delay is None`.
3. **Excel fallback.** Omit `Opened(A)`, pass `job_opened_date="2026-07-01"`. Assert `Opened` milestone has that actual and `status == "Completed"`.
4. **Whitespace tolerance.** Send `"ETD Custom( A )"` — assert it still routes as `ETD Custom(A)`.
5. **Unknown key isolation.** Include an unrelated field `"Some Other Field(A)"`. Assert it is silently ignored.
6. **Dispatch — SEA Import unaffected.** Call `build_milestones_reformed("SEA", None, fields, trade_type="Import")` with the same 13 fields. Assert the output uses `SEQUENCES["SEA"]` (9 events), NOT `SEA_EXPORT` — proves isolation.
7. **Dispatch — AIR unaffected.** Same fields, `transport_mode="AIR"`. Assert `SEQUENCES["AIR"]` sequence returned.
8. **Delay math on ATD.** Set `ETD Custom(A)="2026-06-01"`, `ATD Custom(A)="2026-06-04"`. Assert row 5 `delay == 3`.
9. **Delay math on intermediate row.** Set `Est. Gate In Rail(M)="2026-06-01"`, `Gate In Rail(M)="2026-06-03"`. Assert row 3 `delay == 2` (proves reformed-builder delay is per-row-both-present, not gated by `calc_delay`).

## 8. Risks

- **Duplicate field-key emission by CargoWise.** If a shipment publishes the same key twice, last-writer-wins. This matches current behavior; not a regression.
- **New CargoWise field types.** Ignored silently. If a new mandatory field is added for SEA Export later, this function will need an entry — captured by test #1 failing on missing data.
- **Dispatch order.** The new guard runs *before* any existing SEA-Export handling. If for any reason `_is_sea_export` returns `True` incorrectly, SEA Import would be misrouted. Mitigated by test #6.

## 9. Rollback

The change is additive plus a one-line dispatch. Revert by:
1. Removing the dispatch guard in `build_milestones_reformed`.
2. Deleting `build_sea_export_milestones_reformed`.

The existing SEA-Export branch inside the shared parser (`milestones.py:1714`) remains untouched, so behavior falls back to the pre-change state exactly.

## 10. Out of scope (deferred)

- Cleaning up the ~900 lines of commented-out historical blocks in `milestones.py`.
- Removing the now-dead SEA-Export branch inside the shared parser body.
- Introducing `(mode, trade_type)` tuple keys in `SEQUENCES` for AIR Export / SEA Import as first-class variants.
- Rewriting `build_milestones` (the raw-actuals variant) to be direction-aware.
