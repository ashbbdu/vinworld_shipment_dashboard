# VIN World Shipment Dashboard Pipeline — System Design Spec

> As-is documentation of the existing system. Authored 2026-03-25.

---

## 1. System Overview & Purpose

VIN World Shipment Dashboard Pipeline is a Python-based data pipeline that:

1. Ingests shipment IDs from an Excel file fetched via SFTP (Couchdrop)
2. Queries the CargoWise eAdaptor XML API for full shipment details
3. Parses XML responses into structured records (~118 fields per shipment)
4. Calculates milestone sequences and delay metrics per transport mode/service level
5. Stores everything in a MySQL database on AWS RDS
6. Runs on a cron schedule from an Ubuntu server at `/home/ubuntu/python_scripts/`

**Tech Stack**: Python 3, pymysql, mysql-connector-python, pandas, requests, xmltodict, paramiko, python-dotenv. Dependencies listed in `requirements.txt`. No framework, no tests, no CI/CD.

**Target databases**: Configured via `DB_NAME` env var. Historical targets include `lvs_prod_db` (production) and `lvs_uat_db` (UAT) on the same AWS RDS instance.

---

## 2. Architecture & Data Flow

### High-level pipeline

```
Couchdrop SFTP ──→ Excel file ──→ excel_ingest.py
                                       │
                                       ▼
                              CargoWise eAdaptor API
                                       │
                                       ▼
                              new_milestones5.py
                            (parse, milestones, delays)
                                       │
                                       ▼
                                 MySQL (AWS RDS)
                                       │
                    ┌──────────────────┼──────────────────┐
                    ▼                  ▼                  ▼
              sync_air.py    sea_atd_done_eta    sea_etd_no_atd_eta
              (AIR refresh)  (SEA critical)      (SEA remainder)
                    │                  │                  │
                    └──────────────────┼──────────────────┘
                                       ▼
                              CargoWise API → new_milestones5.py → MySQL
```

### Module responsibilities

| Module | Role | Lines |
|--------|------|-------|
| `new_milestones5.py` | Monolithic core: API calls, XML parsing, milestone building, delay calculation, DB writes | ~4,000 |
| `cron_jobs/excel_ingest.py` | SFTP download, Excel reading, new shipment detection, triggers `update_shipment()` | ~200 |
| `cron_jobs/sync_air.py` | Re-syncs active AIR shipments (conditional on Excel timing) | ~60 |
| `cron_jobs/sea_atd_done_eta_3days.py` | Re-syncs SEA shipments near departure/arrival | ~70 |
| `cron_jobs/sea_etd_no_atd_eta_3days.py` | Midnight reverse sync for remaining SEA shipments | ~85 |
| `core/db.py` | MySQL connection factory via pymysql | ~15 |
| `core/utils.py` | Lockfile mechanism + `excel_ran_recently()` check (includes commented-out legacy versions) | ~220 |
| `core/logger.py` | Timestamped file logger → `cron_jobs/cron.log` | ~15 |
| `core/__init__.py` | Legacy/unused copy of older Excel ingest logic | ~85 |
| `sql/tables.sql` | Schema for `cargowise_containers_new` (~118 cols) + `system_flags` | ~140 |

### Key design decisions

- All business logic concentrated in one file (`new_milestones5.py`)
- Shipment-level records despite table name `cargowise_containers_new` (`JC_ContainerNum` always NULL)
- Dual MySQL drivers: `pymysql` (cron jobs via `core/db.py`) and `mysql-connector-python` (`new_milestones5.py` directly)
- No retry logic on API failures — waits for next cron cycle

---

## 3. Job Scheduling & Coordination

### Cron schedule (Ubuntu server)

| Job | Schedule | Excel Gate? | Target |
|-----|----------|-------------|--------|
| `excel_ingest.py` | Every 3 hours @ minute 10 | No (is the gate) | New shipments from Excel |
| `sync_air.py` | After Excel window | Yes (10–210 min) | Active AIR shipments |
| `sea_atd_done_eta_3days.py` | After Excel window | Yes (10–210 min) | SEA with ETD set but no ATD, or ETA exactly 3 days out |
| `sea_etd_no_atd_eta_3days.py` | Midnight | No | SEA remainder (inverse of above) |

### Coordination mechanisms

**Lockfiles** (`core/utils.py`):
- Path: `/tmp/{job_name}.lock`
- Prevents concurrent execution of the same job
- Stale timeout: 6 hours — if lock older than 6h, it is overwritten
- Removed on job completion (crash leaves stale lock for timeout to handle)

**System flags** (MySQL table `system_flags`):
- Single row: `key_name='excel_sync_last_run'`, `key_value=<timestamp>`
- Updated after each successful Excel ingest
- AIR/SEA conditional jobs call `excel_ran_recently()` which checks:
  - Must be >= 10 minutes ago (allow Excel job to finish)
  - Must be <= 210 minutes ago (3.5 hours — data still fresh)
  - If outside this window, job exits without processing

**Implicit ordering**: Excel runs first (provides new shipment IDs), then AIR/SEA sync jobs refresh existing active shipments with latest API data.

---

## 4. CargoWise API Integration

**Endpoint:** Configured via `CW_API_URL` environment variable.

**Authentication:**
- HTTP Basic Auth (`CW_USERNAME` / `CW_PASSWORD`)
- Custom headers: `clientId`, `clientSecret`, `Origin`
- Content-Type: `application/xml`

### Two API calls per shipment

**1. Shipment Request** (`build_shipment_xml`):
- POST with `UniversalShipmentRequest` XML
- Targets `ForwardingShipment` by shipment ID
- Company: `INJ`, Enterprise: `GWS`, Server: `TR2`
- Returns full shipment object with nested collections:
  - `SubShipmentCollection` → transport legs, containers
  - `MilestoneCollection` → system milestones
  - `CustomizedFieldCollection` → customer-defined milestone dates (primary source)
  - `ContainerCollection` → container details
  - `TransportLegCollection` → vessel/flight info
  - `OrganizationAddressCollection` → parties (shipper, consignee, etc.)

**2. Documents Request** (`build_documents_xml`):
- Separate call to fetch `AttachedDocumentCollection`
- Uses a different Company Code (`VWT`) and includes `DataProvider: GWSTRVWR`
- Returns file metadata: FileName, Type, DocumentID, FileSizeInBytes, SaveDateUTC
- Stored as JSON in the `documents` column

### Response parsing
- XML → `xmltodict.parse()` → Python dict
- Navigated via helper functions (`safe_dict()`, `safe_list()`, `safe_text()`, `get_value()`)
- All parsing defensive — any missing field returns `None` rather than crashing

### Error handling
- API failures logged to `cron.log` and stored in `cargowise_error` column
- `do_not_query` flag can be set to skip problematic shipments
- No retry mechanism — next cron cycle retries automatically

---

## 5. Milestone System

### Data source

`CustomizedFieldCollection` from the CargoWise API response. Each field has a `(A)` suffix (Actual — event happened) or `(M)` suffix (Milestone — planned/estimated date).

### Transport mode x Service level matrix (8 combinations)

| Transport | Service Level | Milestones | Sequence |
|-----------|---------------|------------|----------|
| SEA DTD | Door-to-Door | 9 | Opened → Booked → Loaded → Sailed → Arrived → Discharged → Loaded on Rail → Arrived at Rail → Delivered |
| SEA DTP | Door-to-Port | 8 | Opened → Booked → Loaded → Sailed → Arrived → Discharged → Loaded on Rail → Arrived at Rail |
| SEA PTD | Port-to-Door | 9 | Opened → Booked → Loaded → Sailed → Arrived → Discharged → Loaded on Rail → Arrived at Rail → Delivered |
| SEA PTP | Port-to-Port | 9 | Opened → Booked → Loaded → Sailed → Arrived → Discharged → Loaded on Rail → Arrived at Rail → Delivered |
| AIR DTD | Door-to-Door | 9 | Opened → Booked → Picked up → Delivered to airline → Departed → Arrival at transit point → Departure from transit point → Arrival at final destination → Delivered |
| AIR DTP | Door-to-Port | 8 | Opened → Booked → Picked up → Delivered to airline → Departed → Arrival at transit point → Departure from transit point → Arrival at final destination |
| AIR PTD | Port-to-Door | 8 | Opened → Booked → Delivered to airline → Departed → Arrival at transit point → Departure from transit point → Arrival at final destination → Delivered |
| AIR PTP | Port-to-Port | 7 | Opened → Booked → Delivered to airline → Departed → Arrival at transit point → Departure from transit point → Arrival at final destination |

### Per-milestone record structure

```json
{
  "eventStatus": "Sailed",
  "customField": "ATD Custom",
  "actualDate": "2024-03-15T10:30Z",
  "plannedDate": "2024-03-15T08:00Z",
  "status": "Completed",
  "delay": 2
}
```

### Three milestone JSON columns in DB

- `milestones` — raw extraction from CustomizedFields
- `milestones_new` — fully built with planned/actual/delay per event
- `milestones_reformed` — strict ordered sequences per transport/service level

### Delay calculation (`calculate_delay_days`)

- `delay = ceil((actual_datetime - planned_datetime) / 1 day)`
- Positive = late, negative = early, zero = on time
- Only computed when both dates exist

### ETA/ETD history tracking (dual-column pattern)

- `currentETA` / `updatedETA` — current value vs. original snapshot
- `currentETD` / `updatedETD` — same pattern
- `currentActualArrival` / `updatedActualArrival`
- `currentActualDeparture` / `updatedActualDeparture`
- On first sync: both columns get the same value
- On subsequent syncs: `current*` updates, `updated*` stays frozen
- Delay between snapshots shows schedule drift over time

### Status derivation

- `derive_statuses_from_milestones()` → `derived_statuses` (JSON, all applicable)
- `primary_status` → "Active" or "Delivered"
- `latest_completed_event` → name of most recent completed milestone in sequence

---

## 6. Database Schema

### `cargowise_containers_new` (~118 columns, unique on `JS_UniqueConsignRef`)

| Category | Count | Examples |
|----------|-------|---------|
| **Identity** | 6 | `id`, `JS_UniqueConsignRef`, `JS_HouseBill`, `JS_BookingReference`, `JS_PK`, `console` |
| **Dates - Estimated** | 4 | `currentETA`, `updatedETA`, `currentETD`, `updatedETD` |
| **Dates - Actual** | 4 | `currentActualArrival`, `updatedActualArrival`, `currentActualDeparture`, `updatedActualDeparture` |
| **Dates - Events** | 6 | `arrival_date`, `dep_date`, `confirmedOnBoardDate`, `vesselArrivedDate`, `dischargedDate`, `emptyReturnedDate` |
| **Delays** | 9 | `delay_arrival`, `delay_departure`, `delay_actual_arrival`, `delay_actual_departure`, `delay_in_arrival`, `delay_in_departure`, `delay_status`, `latest_completed_delay`, `latest_completed_actualDate` |
| **Transport** | 8 | `JS_TransportMode`, `JS_PackingMode`, `tradeType`, `steamshipLine`, `carrier`, `scac_code`, `voyageNumber`, `vessel` |
| **Ports & Routes** | 8 | `JS_RL_NKOrigin`, `JS_RL_NKDestination`, `portOfLoading`, `portOfDischarge`, `originPort`, `destinationPort`, `terminalAtPortOfDischarge`, `terminalAtDestinationPort` |
| **Parties** | 6 | `consignee`, `consignee_id`, `deliver_to`, `shipper`, `shipper_id`, `pickup_from` |
| **Goods & Packaging** | 14 | `JS_GoodsDescription`, `JL_PackageCount`, `JL_ActualWeight`, `JL_ActualVolume`, `JL_Length/Width/Height`, `unit_*`, `quantity`, `weight`, `size` |
| **Containers** | 6 | `JC_ContainerNum`, `container_count`, `container_numbers`, `container_weight`, `RC_Code`, `JC_SealNum` |
| **Milestones & Status** | 8 | `milestones`, `milestones_new`, `milestones_reformed`, `derived_statuses`, `primary_status`, `latestStatus`, `status`, `latest_completed_event` |
| **JSON Blobs** | 10 | `documents`, `containerDetails`, `container_records`, `package_records`, `console_shipment`, `currentLocation`, `lastKnownPosition`, `holds`, `history`, `open_track` |
| **Control** | 3 | `do_not_query`, `cargowise_error`, `isRailMove` |
| **Relationships** | 4 | `SM_PK`, `SM_DB`, `SM_ParentFK`, `JT_OrderReference` |
| **Metadata** | 3 | `created_at`, `updated_at`, `JS_SystemLastEditTimeUtc` |
| **Other** | 20 | `JS_ScreeningStatus`, `JS_INCO`, `JS_F3_NKPackType`, `JL_F3_NKPackType`, `JL_PK`, `JL_UnitOfDimension`, `JL_ActualWeightUQ`, `JL_Description`, `JL_MarksAndNumbers`, `company_code`, `rail_addon`, `order_ref`, `flight_vessel`, `masterBillNumber`, `etaAtTerminal`, `etaAtDestination`, `equipmentType`, `location`, `actual_volume`, `timestamp` |

Dimension units: FT for SEA FCL, CM for LCL.

### `system_flags` (job coordination)

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INT, PK | Auto-increment |
| `key_name` | VARCHAR | Flag identifier (e.g., `excel_sync_last_run`) |
| `key_value` | VARCHAR | Timestamp or value |
| `updated_at` | TIMESTAMP | Auto-updated |

Currently holds a single row tracking the last Excel ingest completion time.

---

## 7. Configuration & Deployment

### Environment variables (`.env`)

| Variable | Purpose |
|----------|---------|
| `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | MySQL connection |
| `CW_API_URL` | CargoWise eAdaptor endpoint |
| `CW_CLIENT_ID`, `CW_CLIENT_SECRET` | API client credentials |
| `CW_USERNAME`, `CW_PASSWORD` | API basic auth |
| `CW_ORIGIN` | API origin header |
| `SFTP_HOST`, `SFTP_PORT`, `SFTP_USERNAME`, `SFTP_PASSWORD` | Couchdrop SFTP for Excel download |
| `EXCEL_FILE` | Path to shipment spreadsheet |
| `DEBUG` | Debug mode flag |

### Deployment

- Runs on an Ubuntu server at `/home/ubuntu/python_scripts/`
- Cron jobs scheduled via system crontab
- No process supervisor (systemd, supervisord, etc.)
- No CI/CD pipeline — manual deployment
- Logs append to `cron_jobs/cron.log` (no rotation configured)

### Known limitations

- No automated tests
- No linter or code formatting config
- Dual MySQL drivers (`pymysql` in cron jobs, `mysql-connector-python` in core)
- No retry/backoff on API failures
- No alerting or monitoring — silent failures until next cron run
- 4,000-line monolith makes changes risky without test coverage
- Log file grows unbounded (no rotation)
- Lockfile cleanup depends on graceful exit — crashes leave stale locks (6h timeout as safety net)

---

## Appendix A: Function-Level Reference (`new_milestones5.py`)

### A.1 Helper Functions (Lines 68–141)

**`safe_dict(obj)`** — Returns `obj` if it's a dict, else empty dict `{}`.

**`safe_list(obj)`** — Returns `obj` if list; wraps single items in a list; returns `[]` for None.

**`safe_text(obj)`** — Extracts text from any value:
- `None` → `None`
- `dict` → `None` (prevents accidentally stringifying a nested object)
- `list` → comma-joined string of non-None items
- Other → `str(obj).strip()`, returns `None` if empty string

**`dump_json(obj)`** — Safe JSON serializer with `default=str` fallback. Double-try: first with `default=str`, then with `safe_dict()`.

**`get_value(d, path)`** — Traverses nested dict by list of keys (e.g., `["TransportMode", "Code"]`). Returns `safe_text()` result or `None` at any failure.

**`first_non_null(*args)`** — Returns first argument that is not `None`, empty string, or empty list.

**`format_port(port_obj)`** — Formats port as `"Name(Code)"`. Falls back to `Name` or `(Code)` alone.

**`format_address(addr_obj)`** — Joins CompanyName, Address1, Address2, City, State, Country with commas, skipping `None` parts.

### A.2 Date Helpers (Lines 267–345)

**`parse_iso_dt(dt_str)`** — Robust ISO datetime parser:
1. Strips whitespace
2. Appends `+00:00` if no timezone info present
3. Replaces trailing `Z` with `+00:00`
4. Tries `datetime.fromisoformat()` first
5. Falls back through 6 format patterns (`%Y-%m-%dT%H:%M:%S.%f%z`, etc.)
6. Attaches UTC if tzinfo still missing after parse
7. Returns `None` if all formats fail

**`iso_str(dt)`** — Converts datetime to ISO string, attaching UTC if tzinfo missing.

**`calculate_delay_days(planned, actual)`** — Returns `delta.days` (integer, can be negative). Only computes if both inputs parse successfully. Uses `parse_iso_dt()` on both inputs.

### A.3 Service Level & Mode Helpers (Lines 352–457)

**`get_last_completed_event_in_sequence(milestones, transport_mode, service_level, sequence_map)`**:
1. Looks up `(transport_mode, service_level)` in sequence_map
2. Builds milestone lookup by `customField`
3. Walks sequence in order, tracking the last milestone with `status == "Completed"`
4. Returns `(delay, actualDate, eventStatus)` of the last completed, or `(None, None, None)`

**`extract_service_level_code(shipment, subshipment)`**:
1. Reads `SubShipmentCollection → SubShipment` (takes first if list)
2. Extracts `ServiceLevel → Code`
3. Returns uppercased code (DTD/DTP/PTD/PTP) or `None`

**`extract_milestones_for_mode(transport_mode)`** — Returns dict mapping CustomizedField key → user-facing eventStatus:
- **SEA**: Opened, Carrier Booking, ETD Custom, ETA Custom, Loaded, ATD Custom, ATA Custom, Gate Out, Gate In Rail, ATA Rail, Delivered
- **AIR**: Opened, Carrier Booking, ETD Custom, ETA Custom, Picked, Gate In, ATD Custom, ATA Transit, ATD Transit, ATA Custom, Delivered

### A.4 Milestone Extraction (Lines 462–567)

**`extract_milestones_from_customized_fields(customized_fields, transport_mode)`**:
1. Gets allowed field names from `extract_milestones_for_mode()` + adds `"Discharged"` as extra
2. Iterates all CustomizedField entries
3. Strips `(A)`/`(M)` suffix from key to get clean field name
4. **Priority system**: `(A)` suffix = priority 2, `(M)` = priority 1, no suffix = 0. Higher priority overwrites lower.
5. For each matching field, creates milestone dict: `{eventStatus, customField, actualDate, plannedDate: None, status, delay: None}`
6. Status is `"Completed"` if value exists, else `"Pending"`
7. Removes internal `suffix` key after processing
8. Returns milestones in canonical order (matching `milestone_map` key order), with `Pending` entries for missing fields
9. Appends `Discharged` at end if present as extra CF

**`_planned_from_eta(currentETA, buffer_days)`** — Parses ETA, adds `buffer_days` via `timedelta`, returns ISO string.

**`_get_cf_date(milestones_list, cf_name)`** — Finds `actualDate` by case-insensitive `customField` match.

### A.5 SEA Milestone Builders (Lines 572–1419)

All SEA builders share this common pattern:
1. Extract actual dates from milestones_list via `_get_cf_date()`
2. Set `sailed_planned = currentETD`, `arrived_planned = currentETA`
3. Calculate delays only when both planned and actual exist
4. `discharged_planned = arrived_date` (Arrived.actualDate) — industry standard
5. Build ordered list of milestone dicts

**`build_sea_dtd_milestones(milestones_list, milestone_collection, dates, delivery_buffer_days=4)`** — 9 milestones:
- Opened (no planned/delay)
- Booked (no planned/delay)
- Loaded and delivered to port (no planned/delay)
- Sailed (planned=currentETD, delay=sailed_delay)
- Arrived (planned=currentETA, delay=arrived_delay; `arrived_date = ata_custom or currentActualArrival`)
- Discharged (planned=arrived_date, delay=discharged_delay; fallback to MilestoneCollection "Gate Out" if no CF)
- Loaded on Rail (from "Gate In Rail" CF; fallback to MilestoneCollection; always included even if empty)
- Arrived at Rail (from "ATA Rail" CF; fallback to MilestoneCollection)
- Delivered (planned=ETA+4 days buffer, delay=delivered_delay)

**Special logic in DTD**: Checks `milestone_collection` for `is_rail_move_flag` — searches for any milestone with "rail" in description. Rail milestones always appear regardless of flag.

**`build_sea_dtp_milestones(service_level, ...)`** — 8 milestones (same as DTD minus Delivered). Returns empty list if `service_level != "DTP"`.

**`build_sea_ptd_milestones(service_level, ...)`** — 9 milestones (same structure as DTD, with Delivered planned=ETA+buffer). Returns empty list if `service_level != "PTD"`.

**`build_sea_ptp_milestones(service_level, ...)`** — 9 milestones. Cleaner implementation: uses `calculate_delay_days()` inline with ternary. Rail milestones always included (no conditional). Returns empty list if `service_level != "PTP"`.

### A.6 AIR Milestone Builders (Lines 1426–2108)

**`build_air_milestones(service_level, ...)`** — AIR DTD, 9 milestones:
- Opened, Booked (no planned/delay)
- Picked up (no planned/delay)
- Delivered to airline (no planned/delay)
- Departed (planned=currentETD, delay computed)
- Arrival at transit point (no planned/delay — optional)
- Departure from transit point (no planned/delay — optional)
- Arrival at final destination (planned=currentETA, delay computed)
- Delivered (planned=ETA+4 days, delay computed)

Returns empty list if `service_level != "DTD"`.

**`build_air_dtp_milestones(service_level, ...)`** — AIR DTP, 8 milestones (same as DTD minus Delivered, with Picked up included).

**`build_air_ptd_milestones(service_level, ...)`** — AIR PTD, 8 milestones (no Picked up, includes Delivered).

**`build_air_ptp_milestones(service_level, ...)`** — AIR PTP, 7 milestones (no Picked up, no Delivered).

### A.7 Milestone Router (Lines 2117–2153)

**`build_milestones_new(transport_mode, service_level, milestones_list, milestone_collection, dates, delivery_buffer_days=4)`**:
1. Normalizes transport_mode and service_level to uppercase
2. Validates service_level is in `{DTD, PTD, DTP, PTP}` — returns `[]` if not
3. Routes to appropriate builder based on `(transport_mode, service_level)`
4. Returns `[]` for unknown transport modes

### A.8 Reformed Milestones (Lines 2176–2456)

**`build_milestones_reformed(transport_mode, service_level, customized_fields)`** — Completely independent logic from `milestones_new`:
1. Builds `actual_map` and `planned_map` from raw CustomizedField entries
2. **Key normalization**: `"( A )"` → `"(A)"`, `"( M )"` → `"(M)"`
3. **Special handling**:
   - `ETA Custom(A)` and `ETD Custom(A)` → stored in `planned_map` (these are planned anchors)
   - `ATA Custom(A)` and `ATD Custom(A)` → stored in `actual_map`
   - `(M)` suffix: `"Est."` prefix stripped, stored in `planned_map`, except `Picked(M)` → goes to `actual_map`
4. Uses `PLANNED_FIELD_MAP` to resolve planned keys:
   - `ATD Custom` → `ETD Custom`, `ATA Custom` → `ETA Custom`
   - `Picked` → `Pick Date`, `Gate In` → `Gate In`
   - `Delivered` → `Delivery`, `Loaded` → `Load Date`
   - `Discharged` → `Discharge Date`, `Gate In Rail` → `Gate In Rail`, `ATA Rail` → `ETA Rail`
5. Uses same `SEQUENCES` map as milestones_new (duplicated inline)
6. For each step in sequence: looks up actual from `actual_map`, planned from `planned_map` via `PLANNED_FIELD_MAP`, computes delay

### A.9 Status Derivation (Lines 2462–2497 and 3362–3387)

**`derive_statuses_from_milestones(milestones_list)`** (defined but NOT used in final code path):
- Checks if any `Delivered` milestone has `actualDate` → adds "Delivered"
- Checks all milestones for `actualDate > plannedDate` → adds "Delayed"
- Returns `(list_of_statuses, primary_status)`

**`derive_statuses()` (inline in `parse_shipment_obj`)** — Actually used:
1. Looks up the last event in the sequence for `(transport_mode, service_level)`
2. Finds that milestone in the reformed milestones list
3. If last milestone `status == "Completed"` → `"Delivered"`, else `"Active"`
4. Returns `(primary_status, derived_statuses_list)`

### A.10 XML Payload Builders (Lines 2563–2664)

**`build_shipment_xml(shipment_id)`**:
```xml
<UniversalShipmentRequest xmlns="...cargowise..." version="1.1">
  <ShipmentRequest>
    <DataContext>
      <DataTargetCollection>
        <DataTarget>
          <Type>ForwardingShipment</Type>
          <Key>{shipment_id}</Key>
        </DataTarget>
      </DataTargetCollection>
      <Company><Code>INJ</Code></Company>
      <EnterpriseID>GWS</EnterpriseID>
      <ServerID>TR2</ServerID>
    </DataContext>
  </ShipmentRequest>
</UniversalShipmentRequest>
```

**`build_documents_xml(shipment_id)`**:
```xml
<UniversalDocumentRequest xmlns="...cargowise..." version="1.1">
  <DocumentRequest>
    <DataContext>
      <DataTargetCollection>
        <DataTarget>
          <Type>ForwardingShipment</Type>
          <Key>{shipment_id}</Key>
        </DataTarget>
      </DataTargetCollection>
      <Company><Code>VWT</Code></Company>
      <DataProvider>GWSTRVWR</DataProvider>
      <EnterpriseID>GWS</EnterpriseID>
      <ServerID>TR2</ServerID>
    </DataContext>
    <ReturnDocumentDescriptionsOnly>true</ReturnDocumentDescriptionsOnly>
  </DocumentRequest>
</UniversalDocumentRequest>
```

### A.11 Document Fetching (Lines 144–195)

**`fetch_documents_for_shipment(shipment_id)`**:
1. Builds XML via `build_documents_xml()`
2. POSTs to API with `HEADERS1` (Content-Type only, no clientId) + Basic Auth
3. Parses response: `UniversalResponse → Data → UniversalEvent → Event → AttachedDocumentCollection`
4. Normalizes single doc to list
5. Extracts per document: FileName, Type, DocumentID, FileSizeInBytes, IsPublished, SaveDateUTC, SavedBy
6. Returns JSON string (empty `[]` on any error)

### A.12 DB Helpers (Lines 2669–2720)

**`fetch_eta_and_etd(shipment_id)`** — Queries existing record for `currentETA, updatedETA, currentETD, updatedETD`. Returns `(exists_flag, currentETA, updatedETA, currentETD, updatedETD)`. Opens/closes its own connection.

**`fetch_actuals(shipment_id)`** — Same pattern for `currentActualArrival, updatedActualArrival, currentActualDeparture, updatedActualDeparture`.

### A.13 `update_shipment(shipment_id)` — Main Entry Point (Lines 198–261)

This is the function called by all cron jobs:
1. Builds XML payload via `build_shipment_xml()`
2. POSTs to CargoWise API with `HEADERS1` + Basic Auth, 60s timeout, `verify=False`
3. Parses XML → dict via `xmltodict.parse()` → re-serializes via `json.dumps`/`json.loads` (normalizes OrderedDict to dict)
4. **Defensive validation** — checks for existence of each nesting level:
   - `UniversalResponse` → `Data` → `UniversalShipment` → `Shipment`
   - Returns early (no-op) if any level missing
5. Calls `fetch_documents_for_shipment()` for document metadata
6. Calls `parse_shipment_obj()` to extract all fields
7. Calls `insert_container_records()` to write to DB
8. Catches all exceptions, prints traceback

### A.14 `parse_shipment_obj()` — Field Extraction (Lines 2725–3835)

The monolithic extraction function. Step-by-step:

**Step 1 — Navigation setup (2727–2738)**:
- Extracts `subshipment` from `SubShipmentCollection → SubShipment` (takes first if list)
- Extracts service level code via `extract_service_level_code()`

**Step 2 — CustomizedField gathering (2741–2748)**:
- Collects from both `shipment` and `subshipment` levels into single list
- Handles both list and single-dict responses

**Step 3 — Extract ATA/ATD/ETA/ETD from CustomizedFields (2753–2835)**:
- Iterates all customized fields
- Normalizes `"( A )"` → `"(A)"`
- Matches exactly: `ETA Custom(A)` → `eta_custom`, `ETD Custom(A)` → `etd_custom`
- Matches exactly: `ATA Custom(A)` → `actual_arrival_raw`, `ATD Custom(A)` → `actual_departure_raw`
- Skips entries with empty values

**Step 4 — Transport mode detection (2837–2841)**:
- Tries `shipment.TransportMode.Code`, then `subshipment.TransportMode.Code`
- Uppercased (SEA/AIR/RAIL)

**Step 5 — Milestone extraction (2847–2864)**:
- Calls `extract_milestones_from_customized_fields()` for raw milestones
- Debug: dumps all custom fields if 0 milestones found

**Step 6 — Waybill / Booking IDs (2877–2903)**:
- `JS_HouseBill` from WayBillNumber (always, regardless of type)
- `masterBillNumber` from WayBillNumber only if WayBillType.Code == "MWB"
- `JS_BookingReference`:
  - **AIR**: Uses WayBillNumber (Air Waybill)
  - **SEA**: Tries BookingConfirmationReference → CarrierBookingReference → BookingReference (subshipment, then shipment)

**Step 7 — Organization Addresses (2908–2933)**:
- Iterates `OrganizationAddressCollection` (subshipment first, then shipment)
- `ConsigneeDocumentaryAddress` → extracts company_code, consignee_id, consignee, deliver_to
- `ConsignorDocumentaryAddress` / `SendersLocalClient` / `SendersDocumentaryAddress` → extracts shipper_id, pickup_from, shipper (as JSON object)
- Falls back to top-level `Consignee` and `DeliveryAddress`

**Step 8 — Ports & Trade Type (2938–2958)**:
- `JS_RL_NKOrigin` and `JS_RL_NKDestination` from PortOfOrigin/PortOfDestination
- **Trade type logic**: Extracts 2-letter country code from port code (first 2 chars of UN/LOCODE):
  - Origin country == "US" → `"Export"`
  - Destination country == "US" → `"Import"`
  - Otherwise → `"CrossTrade"`

**Step 9 — Containers (2963–3016)**:
- Extracts from `ContainerCollection → Container` (subshipment first)
- For each container: containerNumber, sealNumber (Seal or SealNumber), containerType, weight (uses shipment-level TotalWeight)
- `container_count`: from ContainerCount field, or count of containers with numbers
- `container_numbers`: comma-joined

**Step 10 — Carrier / Transport Info (3021–3097)**:
- Gets first TransportLeg from `TransportLegCollection`
- Carrier name: tries CarrierInfo.CompanyName → shipment.Carrier → CarrierName → TransportLegCarrier → leg carrier
- **SCAC extraction** (3-level fallback):
  1. Carrier's `RegistrationNumberCollection` → look for `Type.Code == "CCC"`
  2. OrganizationAddresses where type contains "shippingline" or "carrier" → RegistrationNumber with "CCC"
  3. Same addresses → OrganizationCode if length 3-5 chars
- `steamshipLine` from carrier info
- `carrier_code` from OrganizationCode/OrganizationId

**Step 11 — Order References (3102–3127)**:
- Extracts from `LocalProcessing → OrderNumberCollection → OrderNumber → OrderReference`
- Tries subshipment first, then shipment
- Joins multiple refs with ", "

**Step 12 — MilestoneCollection fallback dates (3132–3260)**:
- From system MilestoneCollection (not CustomizedFields):
  - "Departure from First Load Port" → `dep_date` fallback
  - "Arrival at Final Discharge Port" → `arrival_date` fallback, also `etaAtDestination`
  - "Arrival at Load Port Terminal" → `etaAtTerminal`
  - "Confirmed On Board" → `confirmedOnBoardDate`
  - "Discharged" → `dischargedDate`
  - "Empty Returned" → `emptyReturnedDate`

**Step 13 — ETA/ETD History Logic (3152–3178)**:
- Calls `fetch_eta_and_etd()` to get existing DB values
- **First insertion** (`!exists_in_db`):
  - `current_eta = eta_custom`, `updated_eta = current_eta` (snapshot)
  - Same for ETD
- **Existing shipment**:
  - If `eta_custom` changed from `current_eta`:
    - If no `updated_eta` yet → snapshot `current_eta` as `updated_eta`
    - Set `current_eta = eta_custom`
  - Same logic for ETD

**Step 14 — Actual Arrival/Departure History (3184–3212)**:
- Calls `fetch_actuals()` for existing DB values
- Same snapshot pattern as ETA/ETD:
  - First time → lock both current and updated to raw value
  - Subsequent → only update current if changed, keep updated frozen

**Step 15 — Build milestones_new and milestones_reformed (3317–3403)**:
- Calls `build_milestones_new()` with all dates
- Calls `build_milestones_reformed()` with raw customized_fields
- Extracts delay values from reformed milestones: sailed_delay, arrived_delay, discharged_delay, delivered_delay

**Step 16 — Status derivation (3362–3515)**:
- Defines inline `derive_statuses()` using reformed milestones and SEQUENCES
- Calls `get_last_completed_event_in_sequence()` for latest_completed tracking
- Sets `arrival_date = current_eta`, `dep_date = current_etd`

**Step 17 — Build base record (3522–3696)**:
- Constructs dict with all ~90+ fields
- Key field sources:
  - `latestStatus` → from shipment.LatestStatus
  - `delay_arrival` and `delay_actual_arrival` → both set to `arrived_delay` (from reformed milestones)
  - `delay_departure` and `delay_actual_departure` → both set to `sailed_delay`
  - `milestones` → raw extraction JSON
  - `milestones_new` → builder output JSON
  - `milestones_reformed` → reformed builder output JSON
  - `created_at` and `updated_at` → both set to `datetime.now(UTC).isoformat()`
  - `timestamp` → also set to `datetime.now(UTC).isoformat()`

**Step 18 — Container aggregation (3704–3805)**:
- Re-iterates containers to build aggregated fields
- Container numbers uppercased and space-stripped
- Uses `first_container` for dimension fields (JL_Length, JL_Height, JL_Width)
- **Dimension unit assignment**:
  - SEA with containers → `"FT"` (feet, FCL)
  - SEA without containers → `"CM"` (centimeters, LCL)
  - AIR → `None`
- `JC_ContainerNum` always set to `None` (shipment-level tracking)

**Step 19 — Return (3810)**:
- Returns `[rec]` — always a list of exactly 1 record per shipment

### A.15 DB Write Operations (Lines 3841–3945)

**`get_existing_shipments()`** — Returns set of all `JS_UniqueConsignRef` values in DB.

**`insert_container_records(container_records)`**:
1. Opens new connection via `mysql.connector`
2. Builds column list from first record's keys
3. For each record:
   - `SELECT COUNT(*) WHERE JS_UniqueConsignRef = %s`
   - If exists: `UPDATE ... SET ... WHERE JS_UniqueConsignRef = %s` (all columns except `JS_UniqueConsignRef`)
   - If not: `INSERT INTO ... VALUES (...)`
4. Commits after all records
5. No transaction rollback on partial failure

### A.16 Main Script Entry (Lines 3950–4017)

When run directly (`__name__ == "__main__"`):
1. Validates `API_URL_TEST` and `EXCEL_FILE` exist
2. Reads Excel via `pd.read_excel(EXCEL_FILE, dtype=str)`
3. Gets existing shipments from DB
4. For each row with a "Shipment ID":
   - Logs whether it's new or existing (updates even if exists)
   - Builds XML, POSTs to API, parses response
   - Calls `parse_shipment_obj()` + `insert_container_records()`

---

## Appendix B: Cron Job Detail

### B.1 `excel_ingest.py` — SFTP Excel Ingest

**SFTP download** (`get_latest_excel_from_sftp`):
1. Connects via `paramiko.Transport` with keepalive=30s
2. Lists all files on SFTP root
3. Filters by regex: `Shipment Profile Report .*\.xlsx$` (case-insensitive)
4. Excludes files younger than `SAFE_AGE_SECONDS` (60s) to avoid partial uploads
5. Selects most recent file by `st_mtime`
6. Downloads to `/tmp/{filename}` with 3 retries, 3s between retries

**Main flow**:
1. Acquires lockfile `/tmp/excel_ingest.lock`
2. Downloads latest Excel via SFTP
3. Reads "Shipment ID" column (validates it exists)
4. Normalizes IDs: `dropna → str → strip → upper`
5. Queries DB for all existing `JS_UniqueConsignRef` (also normalized to upper)
6. Computes `new_ids = excel_ids - db_ids`
7. For each new ID: calls `update_shipment(sid)` (logs success/failure individually)
8. Updates `system_flags SET key_value = NOW() WHERE key_name = 'excel_sync_last_run'`
9. Removes lockfile in `finally` block

### B.2 `sync_air.py` — AIR Shipment Refresh

1. Acquires lockfile `/tmp/sync_air.lock`
2. Checks `excel_ran_recently()` — exits if not in 10-210 min window
3. Queries: `WHERE JS_TransportMode='AIR' AND primary_status='Active'`
4. For each: calls `update_shipment(sid)`

### B.3 `sea_atd_done_eta_3days.py` — SEA Critical Window

1. Acquires lockfile `/tmp/sea_atd_done.lock`
2. Checks `excel_ran_recently()` — exits if not in window
3. Queries:
```sql
WHERE JS_TransportMode = 'SEA'
  AND primary_status = 'Active'
  AND (
    (currentETD IS NOT NULL
     AND STR_TO_DATE(currentActualDeparture, '%Y-%m-%dT%H:%i:%s') IS NULL
     AND STR_TO_DATE(currentActualDeparture, '%Y-%m-%d %H:%i:%s') IS NULL)
    OR DATE(currentETA) = CURRENT_DATE + INTERVAL 3 DAY
  )
```
- Targets: SEA shipments that have an ETD but haven't actually departed yet, OR whose ETA is exactly 3 days from today
- Uses `COALESCE(STR_TO_DATE(...), STR_TO_DATE(...))` to handle both ISO and standard datetime formats

### B.4 `sea_etd_no_atd_eta_3days.py` — SEA Midnight Reverse

1. Acquires lockfile `/tmp/sea_reverse.lock`
2. **No Excel gate check** — runs unconditionally at midnight
3. Queries (inverse of B.3):
```sql
WHERE JS_TransportMode = 'SEA'
  AND primary_status = 'Active'
  AND (
    (currentETD IS NULL
     OR STR_TO_DATE(currentActualDeparture, ...) IS NOT NULL)
    AND (currentETA IS NULL
         OR DATE(currentETA) <> CURRENT_DATE + INTERVAL 3 DAY)
  )
```
- Targets: SEA shipments where either no ETD or already departed, AND ETA is not exactly 3 days away
- Covers all active SEA shipments not handled by `sea_atd_done_eta_3days.py`

---

## Appendix C: `core/utils.py` Detail

### `create_lock(lockfile, log)`
1. If lockfile exists and age < 6 hours → return `False` (already running)
2. If lockfile exists and age >= 6 hours → log warning, overwrite (stale)
3. Writes PID to lockfile
4. Returns `True` on success, `False` on write failure

### `remove_lock(lockfile)`
- Silently removes lockfile if it exists. Catches all exceptions.

### `excel_ran_recently(cursor, log)`
1. Queries `system_flags WHERE key_name = 'excel_sync_last_run'`
2. Supports both tuple and dict cursor results
3. Parses timestamp: tries `strptime("%Y-%m-%d %H:%M:%S")`, falls back to `fromisoformat()`
4. Forces UTC if no tzinfo
5. Computes `diff_minutes = (now_utc - last_run).total_seconds() / 60`
6. Returns `False` if `diff < 10` (too recent, Excel might still be running)
7. Returns `False` if `diff > 210` (too old, data stale)
8. Returns `True` if in the 10-210 minute window
9. Returns `False` on any exception
