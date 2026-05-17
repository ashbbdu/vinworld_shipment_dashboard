# VIN World Shipment Pipeline — Improvements Design Spec

> Design spec for service-based architecture with retry/resume, Excel DB storage, internal scheduler, code refactoring, and error notifications. Authored 2026-03-25.

---

## 1. Goals

1. **Service with retry/resume** — run as a systemd service, track per-shipment processing state, resume from where it stopped on restart
2. **Excel records in DB** — store parsed rows and file metadata in database tables
3. **Internal job scheduler** — replace system crontab with APScheduler, schedules configurable via `.env`
4. **Code refactoring** — break the 4000-line monolith into focused DRY modules under ~200 lines each
5. **Error email notifications** — SMTP alerts to multiple recipients on failures
6. **Parallel processing** — concurrent shipment processing via ThreadPoolExecutor, configurable concurrency
7. **S3 archival** — archive old logs and downloaded files to S3, delete from SFTP after ingest
8. **All configuration in `.env`** — single source of truth, no hardcoded values anywhere

---

## 2. Architecture

### Stack

- **Python 3** — same language, no framework
- **APScheduler** — in-process cron-like scheduler, config-driven from `.env`
- **ThreadPoolExecutor** — parallel shipment processing
- **pymysql** — single MySQL driver (drops `mysql-connector-python`)
- **paramiko** — SFTP (unchanged)
- **boto3** — S3 archival
- **systemd** — service lifecycle management

### Module Structure

```
pipeline/
├── __init__.py
├── config.py            # All .env loading, single source of truth
├── service.py           # Main entry: APScheduler, systemd integration, signal handling
├── scheduler.py         # Job definitions, schedule parsing, event-driven chaining
├── sftp.py              # SFTP connect/download/list/delete
├── excel.py             # Parse Excel, store rows + metadata in DB
├── cargowise.py         # XML builders, API calls (shipment + documents), rate limiting
├── parser.py            # XML response → flat dict (addresses, ports, containers, carrier)
├── milestones.py        # Milestone sequences, builders, delay calc — data-driven, DRY
├── helpers.py           # safe_dict, safe_list, safe_text, get_value, first_non_null, date helpers
├── db.py                # Connection pool, all queries, tracking, upserts
├── notifications.py     # SMTP email: error alerts, job reports, recovery notices
├── archiver.py          # S3 upload, local cleanup, SFTP deletion
├── jobs/
│   ├── __init__.py
│   ├── excel_ingest.py  # Orchestrates: SFTP → Excel → DB → CargoWise → parse → store
│                        # Two entry points: run() for full ingest + CW sync,
│                        # run_download_only() for SFTP download + DB populate only
│   ├── sync_air.py      # AIR refresh job
│   ├── sync_sea.py      # SEA sync (critical window) + SEA reverse (remainder)
│   ├── nightly_retry.py # Retry all failed shipments (optional)
│   └── archive.py       # Daily archive job
└── sql/
    └── migrations.sql   # New tables + schema changes
```

### Refactoring Principles

- **Single MySQL driver**: `pymysql` everywhere via connection pool. Drop `mysql-connector-python`.
- **No repeated code**: 8 milestone builder functions → 1 data-driven function + sequence config dicts.
- **Parser extraction**: `parse_shipment_obj()` (1100 lines) → focused `_extract_*()` functions (20-40 lines each).
- **Each module under ~200 lines** where possible.
- **Extract, don't rewrite**: Same logic, better organization. All field paths, milestone sequences, delay calculations, SCAC extraction, and ETA/ETD snapshot logic preserved exactly.
- **RAIL support**: RAIL transport mode is preserved. Currently handled as a variation within SEA (rail milestones appear in SEA sequences). If standalone RAIL sequences are needed in future, add entries to the `SEQUENCES` dict.

---

## 3. Configuration (`.env`)

Single source of truth — every setting comes from `.env`, accessed via `config.py`. No module calls `os.getenv()` directly.

```env
# ── Database ──
DB_HOST=<your-db-host>
DB_USER=<your-db-user>
DB_PASSWORD=<your-db-password>
DB_NAME=<your-db-name>
DB_POOL_SIZE=5

# ── CargoWise API ──
CW_API_URL=<your-cargowise-eadaptor-url>
CW_CLIENT_ID=<your-client-id>
CW_CLIENT_SECRET=<your-client-secret>
CW_USERNAME=<your-cw-username>
CW_PASSWORD=<your-cw-password>
CW_ORIGIN=<your-cw-origin>
CW_TIMEOUT=60
CW_RATE_LIMIT=10
CW_CIRCUIT_BREAKER_THRESHOLD=5
CW_AUTH_MODE=header
# Auth modes: "header" (clientId/clientSecret/Origin in headers) or "basic" (HTTP Basic Auth)
CW_VERIFY_SSL=False
CW_SHIPMENT_COMPANY_CODE=INJ
CW_DOCUMENT_COMPANY_CODE=VWT
CW_DOCUMENT_DATA_PROVIDER=GWSTRVWR
CW_ENTERPRISE_ID=GWS
CW_SERVER_ID=TR2

# ── SFTP ──
SFTP_HOST=<your-sftp-host>
SFTP_PORT=22
SFTP_USERNAME=<your-sftp-user>
SFTP_PASSWORD=<your-sftp-password>
SFTP_REMOTE_DIR=/vinworld_shipment_dashboard
SFTP_FILE_PATTERN=Shipment Profile Report *.xlsx
# Actual filenames look like: Shipment Profile Report (2026-03-25 13-04-57).XLSX
# Pattern uses * wildcard (case-insensitive match)
SFTP_SAFE_AGE_SECONDS=60
SFTP_DELETE_AFTER_INGEST=True

# ── Scheduler ──
EXCEL_INGEST_SCHEDULE=0 10 */3 * *
SEA_REVERSE_SCHEDULE=0 0 * * *
NIGHTLY_RETRY_ENABLED=True
NIGHTLY_RETRY_SCHEDULE=30 0 * * *
ARCHIVE_ENABLED=True
ARCHIVE_SCHEDULE=0 2 * * *
JOB_MAX_INSTANCES=1

# ── Sync Parameters ──
SEA_ETA_WINDOW_DAYS=3
AIR_SYNC_TRANSPORT_MODE=AIR
AIR_SYNC_STATUS=Active
SEA_SYNC_TRANSPORT_MODE=SEA
SEA_SYNC_STATUS=Active

# ── Parallelism & Retry ──
MAX_PARALLEL_REQUESTS=5
SHIPMENT_RETRY_MAX=3
SHIPMENT_RETRY_DELAY=30
SHIPMENT_MAX_LIFETIME_RETRIES=10

# ── Email ──
SMTP_SERVER=<your-smtp-server>
SMTP_PORT=587
SMTP_USERNAME=<your-smtp-user>
SMTP_PASSWORD=<your-smtp-password>
SMTP_FROM=<your-from-address>
SMTP_FROM_NAME=VIN World Pipeline
ERROR_EMAIL_RECIPIENTS=user1@example.com,user2@example.com
JOB_REPORT_RECIPIENTS=

# ── S3 Archive ──
AWS_S3_BUCKET=<your-s3-bucket>
AWS_S3_ARCHIVE_PREFIX=archives/
AWS_ACCESS_KEY_ID=<your-aws-key>
AWS_SECRET_ACCESS_KEY=<your-aws-secret>
AWS_REGION=us-east-1
ARCHIVE_AGE_DAYS=7

# ── General ──
DEBUG=False
LOG_FILE=pipeline.log
LOG_LEVEL=INFO
LOG_ROTATION=daily
DOWNLOAD_DIR=/tmp/pipeline_downloads
HEALTH_CHECK_FILE=/tmp/pipeline_health
TRACKING_RETENTION_DAYS=30
```

> **Note**: Actual credentials are stored in the deployed `.env` file only (gitignored). This spec uses placeholders.

### Sync Query Design

Raw SQL queries are **not** stored in `.env` — this avoids SQL injection risk, typo breakage, and `STR_TO_DATE` format complexity. Instead, `.env` provides only the **parameters** (`SEA_ETA_WINDOW_DAYS`, transport mode, status). The SQL templates live in `db.py` with proper `STR_TO_DATE`/`COALESCE` handling for dual datetime formats:

```python
# db.py — query templates (not in .env)
SEA_SYNC_QUERY = """
    SELECT JS_UniqueConsignRef FROM cargowise_containers_new
    WHERE JS_TransportMode = %(mode)s AND primary_status = %(status)s
    AND (
        (currentETD IS NOT NULL
         AND COALESCE(
             STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%dT%%H:%%i:%%s'),
             STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%d %%H:%%i:%%s')
         ) IS NULL)
        OR DATE(currentETA) = CURRENT_DATE + INTERVAL %(window)s DAY
    )
"""
```

`config.py` loads `.env` once at import, validates required vars, exposes a `settings` object.

---

## 4. Job Scheduling & Event-Driven Chaining

### Schedule Design

Only 3 jobs are time-triggered. AIR Sync and SEA Sync are event-driven — triggered by Excel Ingest completion. This eliminates the fragile `excel_ran_recently()` timing-window hack.

| Job | Trigger | `.env` Control |
|-----|---------|----------------|
| Excel Ingest | Cron schedule | `EXCEL_INGEST_SCHEDULE` |
| AIR Sync | Triggered by Excel completion | `AIR_SYNC_QUERY` |
| SEA Sync | Triggered by Excel completion | `SEA_SYNC_QUERY` |
| SEA Reverse | Cron schedule (midnight) | `SEA_REVERSE_SCHEDULE`, `SEA_REVERSE_QUERY` |
| Nightly Retry | Cron schedule (optional) | `NIGHTLY_RETRY_ENABLED`, `NIGHTLY_RETRY_SCHEDULE` |
| Archive | Cron schedule (optional) | `ARCHIVE_ENABLED`, `ARCHIVE_SCHEDULE` |

### Job Overlap Prevention

APScheduler configured with `max_instances=1` per job (`JOB_MAX_INSTANCES`). If a job is still running when the next trigger fires, the trigger is skipped and logged.

### Duplicate Processing Guard

AIR/SEA Sync skips any `shipment_id` already processed in the current Excel Ingest cycle. Checked via `shipment_tracking` for the parent cycle's `job_run_id` with `status='completed'`.

### Data Flow Decision Logic

```
Excel Ingest:   Excel IDs  →  "is it in cargowise_containers_new?"  →  NO  →  query CW  →  insert
AIR Sync:       DB query   →  "active AIR in cargowise_containers_new?"   →  YES →  query CW  →  update
SEA Sync:       DB query   →  "critical SEA in cargowise_containers_new?" →  YES →  query CW  →  update
SEA Reverse:    DB query   →  "remaining active SEA?"                     →  YES →  query CW  →  update
```

All jobs query CargoWise API for fresh data. The DB is only used to decide WHICH shipments to query.

---

## 5. Database Changes — New Tables

### `job_runs` — Job execution history

```sql
CREATE TABLE job_runs (
    id VARCHAR(36) PRIMARY KEY,
    job_type VARCHAR(50) NOT NULL,
    status ENUM('running', 'completed', 'failed') DEFAULT 'running',
    total_shipments INT DEFAULT 0,
    processed_count INT DEFAULT 0,
    failed_count INT DEFAULT 0,
    error_summary TEXT NULL,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME NULL,
    INDEX idx_type_status (job_type, status)
);
```

### `shipment_tracking` — Per-shipment processing state

```sql
CREATE TABLE shipment_tracking (
    id INT AUTO_INCREMENT PRIMARY KEY,
    shipment_id VARCHAR(100) NOT NULL,
    job_type ENUM('excel_ingest', 'air_sync', 'sea_sync', 'sea_reverse', 'nightly_retry') NOT NULL,
    job_run_id VARCHAR(36) NOT NULL,
    status ENUM('pending', 'in_progress', 'completed', 'failed') DEFAULT 'pending',
    retry_count INT DEFAULT 0,
    lifetime_retry_count INT DEFAULT 0,
    error_message TEXT NULL,
    started_at DATETIME NULL,
    completed_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_shipment (shipment_id),
    INDEX idx_job_run (job_run_id),
    FOREIGN KEY (job_run_id) REFERENCES job_runs(id) ON DELETE CASCADE
);
```

### `excel_imports` — File metadata

```sql
CREATE TABLE excel_imports (
    id INT AUTO_INCREMENT PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    sftp_path VARCHAR(500) NULL,
    file_size_bytes BIGINT NULL,
    file_modified_at DATETIME NULL,
    row_count INT DEFAULT 0,
    new_shipment_count INT DEFAULT 0,
    job_run_id VARCHAR(36) NOT NULL,
    status ENUM('downloaded', 'parsed', 'processing', 'completed', 'failed') DEFAULT 'downloaded',
    local_path VARCHAR(500) NULL,
    s3_archive_path VARCHAR(500) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_job_run (job_run_id),
    FOREIGN KEY (job_run_id) REFERENCES job_runs(id) ON DELETE CASCADE
);
```

### `excel_import_rows` — Parsed Excel rows

```sql
CREATE TABLE excel_import_rows (
    id INT AUTO_INCREMENT PRIMARY KEY,
    excel_import_id INT NOT NULL,
    shipment_id VARCHAR(100) NOT NULL,
    raw_row_data JSON NULL,
    is_new BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (excel_import_id) REFERENCES excel_imports(id) ON DELETE CASCADE,
    INDEX idx_shipment (shipment_id),
    INDEX idx_import (excel_import_id)
);
```

### Relationships

- Each job execution gets a `job_run_id` (UUID)
- `job_runs` → overall execution status and summary
- `shipment_tracking` → per-shipment status within a job run
- `excel_imports` → file metadata per download
- `excel_import_rows` → every row from the Excel, linked to its import
- All link via `job_run_id`

### Tracking Retention

Archive job purges records older than `TRACKING_RETENTION_DAYS`. All foreign keys use `ON DELETE CASCADE`, so deleting from `job_runs` automatically cascades to `shipment_tracking`, `excel_imports`, and `excel_import_rows`:
```sql
DELETE FROM job_runs WHERE started_at < NOW() - INTERVAL {TRACKING_RETENTION_DAYS} DAY;
-- CASCADE handles: shipment_tracking, excel_imports → excel_import_rows
```

---

## 6. Service Lifecycle & Retry/Resume

### Service Entry (`service.py`)

```
startup:
    1. Load config from .env
    2. Validate all required env vars present
    3. Test DB connection
    4. Test SMTP connection (non-fatal warning if fails)
    5. Recover interrupted work (see below)
    6. Register signal handlers (SIGTERM, SIGINT → graceful shutdown)
    7. Start APScheduler with job schedules from .env
    8. Start health check heartbeat (touches HEALTH_CHECK_FILE every 60s)
    9. Log "Service started"

running:
    - APScheduler fires jobs per schedule
    - Event-driven triggers chain Excel → AIR/SEA
    - ThreadPoolExecutor processes shipments in parallel
    - Health check file touched every 60 seconds
    - All exceptions caught, logged, emailed — service never crashes

shutdown (SIGTERM from systemd):
    1. Stop accepting new jobs
    2. Wait for in-progress shipments to complete (up to 60s grace)
    3. Mark any remaining in_progress as 'pending' for resume
    4. Log "Service stopped"
    5. Exit cleanly
```

### Retry Logic (per shipment)

```
process_shipment(shipment_id):
    mark status = 'in_progress', started_at = now

    try:
        call CargoWise API (shipment)
        call CargoWise API (documents)
        parse response
        fetch ETA/ETD history from DB → apply snapshot logic
        build milestones
        derive status
        upsert to cargowise_containers_new
        mark status = 'completed', completed_at = now

    except (Timeout, ConnectionError):
        if retry_count < SHIPMENT_RETRY_MAX:
            retry_count += 1
            re-queue to a retry list (processed after main batch completes)
            # Note: retries are NOT sleep-blocked inside the thread pool.
            # Instead, failed shipments are collected and re-submitted
            # in a second pass after SHIPMENT_RETRY_DELAY seconds.
        else:
            mark status = 'failed'
            store error_message
            increment lifetime_retry_count

    except Exception:
        mark status = 'failed'
        store error_message + traceback
        increment lifetime_retry_count
```

### Dead Letter Handling

When `lifetime_retry_count >= SHIPMENT_MAX_LIFETIME_RETRIES`:
- Set `do_not_query=1` in `cargowise_containers_new`
- Send dedicated alert: "Shipment X permanently failed — manual intervention required"
- Stop retrying this shipment in all future jobs

### Resume on Restart

```
recover_interrupted():
    1. SELECT * FROM shipment_tracking WHERE status IN ('in_progress', 'pending')
       AND job_run_id IN (SELECT id FROM job_runs WHERE status = 'running')
    2. Create new job_run (type='recovery', status='running')
    3. Re-associate orphaned shipments with the new recovery job_run_id
    4. Reset status to 'pending'
    5. UPDATE job_runs SET status = 'failed' WHERE status = 'running' AND id != recovery_run_id
    6. Log "Recovered N interrupted shipments"
    7. Send recovery notice email (if any recovered)
    8. Process recovered shipments immediately (same parallel flow as run_job)
```

### Parallel Processing

```
run_job(job_type, shipment_ids):
    job_run_id = uuid4()
    insert job_runs record (status='running')
    bulk_insert shipment_tracking (all shipments as 'pending')

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_REQUESTS) as pool:
        futures = {
            pool.submit(process_shipment, sid, job_run_id): sid
            for sid in shipment_ids
        }
        for future in as_completed(futures):
            # results collected, errors handled inside process_shipment

    update job_runs: processed_count, failed_count, status, completed_at

    if failed_count > 0:
        send_job_failure_email(job_run_id)
```

### Circuit Breaker

After `CW_CIRCUIT_BREAKER_THRESHOLD` consecutive failures within a single job run:
- Stop submitting new shipments to the thread pool
- Mark remaining shipments as `pending` (not failed — they weren't attempted)
- Send single "CargoWise appears to be down" email
- Job completes with partial results
- Pending shipments picked up next cycle or by nightly retry

### systemd Unit File

```ini
[Unit]
Description=VIN World Shipment Pipeline
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/ubuntu/pipeline/service.py
WorkingDirectory=/home/ubuntu/pipeline
EnvironmentFile=/home/ubuntu/pipeline/.env
Restart=always
RestartSec=10
User=ubuntu

[Install]
WantedBy=multi-user.target
```

---

## 7. CargoWise API Client (`cargowise.py`)

```python
class CargoWiseClient:
    def __init__(self, settings):
        # API URL, auth, timeout from settings
        # Rate limiter: token bucket for CW_RATE_LIMIT
        # CW_AUTH_MODE determines auth strategy:
        #   "header" → clientId/clientSecret/Origin in headers, no Basic Auth
        #   "basic"  → HTTP Basic Auth, Content-Type only header
        # SSL verify from CW_VERIFY_SSL (default False)

    def fetch_shipment(self, shipment_id) -> dict:
        # build_shipment_xml(shipment_id) — Company from CW_SHIPMENT_COMPANY_CODE
        # POST via _post(xml)
        # Returns parsed Shipment dict or raises

    def fetch_documents(self, shipment_id) -> list:
        # build_documents_xml(shipment_id) — Company from CW_DOCUMENT_COMPANY_CODE
        # POST via _post(xml)
        # Navigates response with `or {}` guards at each level (CW can return None for nested keys)
        # Returns list of document dicts (empty list on failure or missing data)

    def _post(self, xml_payload) -> dict:
        # Rate limit wait → POST with self._headers + self._auth
        # verify=CW_VERIFY_SSL
        # raise_for_status → xmltodict.parse
```

**Auth modes** (`CW_AUTH_MODE`):
- `"header"` (default): sends `clientId`, `clientSecret`, `Origin` as HTTP headers alongside `Content-Type`. No Basic Auth. Used when CW is configured for header-based authentication.
- `"basic"`: sends only `Content-Type: application/xml` header, with HTTP Basic Auth (`CW_USERNAME`/`CW_PASSWORD`). Used for endpoints requiring standard Basic Auth.

### Rate Limiting

Token bucket algorithm respecting `CW_RATE_LIMIT` requests per second. Each `_post()` call acquires a token before sending. Thread-safe via `threading.Lock`.

---

## 8. Parser (`parser.py`)

Replaces the 1100-line `parse_shipment_obj()` with focused extractors:

```python
def parse_shipment(shipment_id, shipment_dict, documents) -> dict:
    sub = _extract_subshipment(shipment_dict)
    record = {}
    record.update(_extract_ids(shipment_dict, sub))
    record.update(_extract_parties(shipment_dict, sub))
    record.update(_extract_ports(shipment_dict, sub))
    record.update(_extract_containers(shipment_dict, sub))
    record.update(_extract_carrier(shipment_dict, sub))
    record.update(_extract_transport(shipment_dict, sub))
    record.update(_extract_order_refs(shipment_dict, sub))
    record.update(_extract_dates(shipment_dict, sub))
    record.update(_extract_misc(shipment_dict, sub))
    record["documents"] = json.dumps(documents)
    return record
```

Each `_extract_*` function: 20-40 lines, testable independently, same field extraction logic as current code.

### Key extractors:

- **`_extract_ids`**: JS_HouseBill, JS_BookingReference (AIR=WayBillNumber, SEA=BookingConfirmationReference fallback chain), masterBillNumber
- **`_extract_parties`**: Iterates OrganizationAddressCollection for ConsigneeDocumentaryAddress, ConsignorDocumentaryAddress, SendersLocalClient, SendersDocumentaryAddress
- **`_extract_ports`**: PortOfOrigin/Destination via format_port(), trade type (US origin=Export, US dest=Import, else CrossTrade)
- **`_extract_containers`**: ContainerCollection parsing, count, numbers, seals, types, dimensions (FT for SEA FCL, CM for LCL)
- **`_extract_carrier`**: Carrier name from TransportLeg, 3-level SCAC fallback (RegistrationNumber CCC → OrganizationAddress CCC → OrganizationCode 3-5 chars)
- **`_extract_transport`**: JS_TransportMode, JS_PackingMode, voyageNumber, vessel, flight_vessel, isRailMove, JS_ScreeningStatus
- **`_extract_dates`**: CustomizedField (A)/(M) extraction for ETA/ETD/ATA/ATD, **plus MilestoneCollection fallback** for Gate Out (Discharged), Gate In Rail, ATA Rail, confirmedOnBoardDate, etaAtTerminal, etaAtDestination, emptyReturnedDate
- **`_extract_misc`**: JS_GoodsDescription, JS_INCO, JS_F3_NKPackType, company_code, order_ref, status, latestStatus, console (JSPK from DataSourceCollection), open_track, holds, history, currentLocation, lastKnownPosition

### Raw milestone extraction

The `milestones` column (raw CustomizedField extraction) is populated by `extract_milestones_from_customized_fields()`, which moves to `milestones.py`. This function is called in the parser pipeline before `build_milestones()`:

```python
# In the job processing flow:
raw_milestones = extract_milestones_from_customized_fields(customized_fields, transport_mode)
record["milestones"] = json.dumps(raw_milestones)

# MilestoneCollection fallback: _extract_dates populates actuals dict
# with fallback dates from MilestoneCollection when CustomizedFields are missing.
# This actuals dict is then passed to build_milestones() and build_milestones_reformed().
```

---

## 9. Milestones (`milestones.py`) — Data-Driven DRY Design

### Current Problem

8 builder functions sharing ~80% identical code. Each is 100-200 lines.

### Solution: Sequence Definitions as Data

```python
SEQUENCES = {
    ("SEA", "DTD"): [
        # (cf_key,          label,                         planned_source, calc_delay)
        ("Opened",          "Opened",                      None,           False),
        ("Carrier Booking", "Booked",                      None,           False),
        ("Loaded",          "Loaded and delivered to port", None,           False),
        ("ATD Custom",      "Sailed",                      "etd",          True),
        ("ATA Custom",      "Arrived",                     "eta",          True),
        ("Gate Out",        "Discharged",                  "arrived",      True),
        ("Gate In Rail",    "Loaded on Rail",              None,           False),
        ("ATA Rail",        "Arrived at Rail",             None,           False),
        ("Delivered",       "Delivered",                   "eta_buffer",   True),
    ],
    ("SEA", "DTP"): [ ... ],  # 8 milestones, no Delivered
    ("SEA", "PTD"): [ ... ],  # 9 milestones
    ("SEA", "PTP"): [ ... ],  # 9 milestones
    ("AIR", "DTD"): [ ... ],  # 9 milestones, with Picked up
    ("AIR", "DTP"): [ ... ],  # 8 milestones, with Picked up, no Delivered
    ("AIR", "PTD"): [ ... ],  # 8 milestones, no Picked up
    ("AIR", "PTP"): [ ... ],  # 7 milestones, no Picked up, no Delivered
}
```

### Single Builder Function

```python
def build_milestones(transport_mode, service_level, actuals, dates, buffer_days=4):
    sequence = SEQUENCES.get((transport_mode, service_level), [])
    milestones = []
    for cf_key, label, planned_source, calc_delay in sequence:
        actual = actuals.get(cf_key)
        planned = _resolve_planned(planned_source, dates, actuals, buffer_days)
        delay = calculate_delay_days(planned, actual) if calc_delay and planned and actual else None
        milestones.append({
            "eventStatus": label,
            "customField": cf_key,
            "actualDate": actual,
            "plannedDate": planned,
            "status": "Completed" if actual else "Pending",
            "delay": delay,
        })
    return milestones

def _resolve_planned(source, dates, actuals, buffer_days):
    if source is None: return None
    if source == "etd": return dates.get("currentETD")
    if source == "eta": return dates.get("currentETA")
    if source == "arrived": return actuals.get("ATA Custom")
    if source == "eta_buffer": return _planned_from_eta(dates.get("currentETA"), buffer_days)
    return None
```

**8 functions → 1 function + data tables. ~75% less code. Same output.**

### Reformed Milestones

Same data-driven approach with `PLANNED_FIELD_MAP` for resolving planned dates from (M) suffix fields:
```python
PLANNED_FIELD_MAP = {
    "ATD Custom": "ETD Custom",
    "ATA Custom": "ETA Custom",
    "Picked": "Pick Date",
    "Gate In": "Gate In",
    "Delivered": "Delivery",
    "Loaded": "Load Date",
    "Discharged": "Discharge Date",
    "Gate In Rail": "Gate In Rail",
    "ATA Rail": "ETA Rail",
}
```

### Status Derivation

```python
def derive_status(milestones, transport_mode, service_level):
    sequence = SEQUENCES.get((transport_mode, service_level), [])
    if not sequence: return "Active", ["Active"]
    last_cf_key = sequence[-1][0]
    last = next((m for m in milestones if m["customField"] == last_cf_key), None)
    if last and last["status"] == "Completed":
        return "Delivered", ["Delivered"]
    return "Active", ["Active"]
```

---

## 10. Database Layer (`db.py`)

Unified database operations. Single driver (`pymysql`), connection pool via `DBUtils.PooledDB` (thread-safe pooling for pymysql).

```python
class Database:
    def __init__(self, settings):
        # pymysql connection pool, size from DB_POOL_SIZE

    def get_connection(self):
        # Returns pooled connection (thread-safe)

    # ── Shipment operations ──
    def upsert_shipment(self, record: dict): ...
    def get_active_shipments(self, query: str) -> list: ...
    def get_existing_shipment_ids(self) -> set: ...
    def fetch_eta_etd(self, shipment_id) -> dict: ...
    def fetch_actuals(self, shipment_id) -> dict: ...

    # ── Job tracking ──
    def create_job_run(self, job_type) -> str: ...
    def complete_job_run(self, job_run_id, processed, failed): ...
    def track_shipment(self, shipment_id, job_run_id, job_type, status): ...
    def update_tracking(self, shipment_id, job_run_id, status, error=None): ...
    def get_interrupted(self) -> list: ...
    def get_failed_shipments(self) -> list: ...
    def get_dead_letter_shipments(self) -> list: ...
    def was_processed_in_cycle(self, shipment_id, parent_job_run_id) -> bool: ...

    # ── Excel imports ──
    def save_excel_metadata(self, metadata: dict) -> int: ...
    def save_excel_rows(self, import_id, rows: list): ...
    # rows must be pre-transformed dicts: {"shipment_id": str, "raw_row_data": json_str, "is_new": bool}
    # The caller (excel_ingest.py) maps Excel column "Shipment ID" → "shipment_id" and serializes full row as JSON

    # ── Maintenance ──
    def purge_old_tracking(self, retention_days): ...
```

### ETA/ETD Snapshot Logic (preserved)

The dual-column snapshot pattern is unchanged:
- First insertion: `current_* = updated_* = value` (snapshot)
- Subsequent: if value changed → update `current_*`, keep `updated_*` frozen
- Applied via `fetch_eta_etd()` + `fetch_actuals()` before upsert

---

## 11. Email Notifications (`notifications.py`)

### Email Types

| Type | When | Recipients |
|------|------|------------|
| Job failure summary | Job completes with failures | `ERROR_EMAIL_RECIPIENTS` |
| Service restart recovery | Service restarts with interrupted work | `ERROR_EMAIL_RECIPIENTS` |
| Circuit breaker alert | CW API appears down | `ERROR_EMAIL_RECIPIENTS` |
| Dead letter alert | Shipment exhausts lifetime retries | `ERROR_EMAIL_RECIPIENTS` |
| Job completion report | Every job completion (optional) | `JOB_REPORT_RECIPIENTS` |

### Implementation

```python
class EmailNotifier:
    def __init__(self, settings):
        # SMTP config: server, port, username, password, from address

    def send_job_failure(self, job_run, failed_shipments): ...
    def send_job_report(self, job_run): ...
    def send_recovery_notice(self, recovered_count): ...
    def send_circuit_breaker_alert(self, job_run, consecutive_failures): ...
    def send_dead_letter_alert(self, shipment_id, total_retries): ...

    def _send(self, recipients, subject, body, attachments=None):
        # SMTP with TLS on port 587
        # Catches SMTP errors — logs but never crashes the service
```

### Job Failure Email Format

```
Subject: [Pipeline Alert] AIR Sync — 3 of 45 shipments failed

Job: AIR Sync
Run ID: abc-123-def
Started: 2026-03-25 10:40:00 UTC
Completed: 2026-03-25 10:52:00 UTC

Summary: 42 completed, 3 failed

Failed Shipments:
─────────────────
1. S00012345 — ConnectionTimeout: CargoWise API did not respond (retried 3x)
2. S00012399 — XMLParseError: Unexpected response format
3. S00012401 — KeyError: 'SubShipmentCollection' missing

Full log attached.
```

---

## 12. S3 Archival & File Management (`archiver.py`)

### File Lifecycle

```
SFTP download → DOWNLOAD_DIR/{filename}
    → Parse & store rows in DB (excel_imports + excel_import_rows)
    → Delete from SFTP (if SFTP_DELETE_AFTER_INGEST=True)
    → Process shipments
    → Mark excel_imports.status = 'completed'
    → Archive job (2 AM daily):
        → Files older than ARCHIVE_AGE_DAYS → S3
        → Log files older than ARCHIVE_AGE_DAYS → S3
        → Update excel_imports.s3_archive_path
        → Delete local copies
        → Purge old tracking records
```

### S3 Bucket Structure

```
s3://{AWS_S3_BUCKET}/{AWS_S3_ARCHIVE_PREFIX}
├── excel/
│   ├── 2026-03-18/Shipment Profile Report (2026-03-18 09-10-00).XLSX
│   └── 2026-03-19/Shipment Profile Report (2026-03-19 09-10-00).XLSX
└── logs/
    ├── 2026-03-18/pipeline-2026-03-18.log
    └── 2026-03-19/pipeline-2026-03-19.log
```

### SFTP Deletion

After Excel rows are confirmed stored in `excel_import_rows`:
1. `sftp.remove(remote_filename)`
2. Log "Deleted {filename} from SFTP"
3. On failure: log warning, continue (non-fatal)

Only executes when `SFTP_DELETE_AFTER_INGEST=True`.

---

## 13. Logging

### Current → New

| Current | New |
|---------|-----|
| Single `cron.log`, append forever | Daily rotation via `TimedRotatingFileHandler` |
| Custom `log()` function | Python `logging` module with named loggers |
| No log levels | Configurable `LOG_LEVEL` |
| No structured format | `[2026-03-25 10:40:00] [INFO] [pipeline.cargowise] message` |

Each module gets its own named logger:
- `pipeline.service`
- `pipeline.sftp`
- `pipeline.cargowise`
- `pipeline.parser`
- `pipeline.milestones`
- `pipeline.db`
- `pipeline.notifications`

Console output goes to systemd journal. File output goes to `LOG_FILE` with daily rotation.

---

## 14. Health Check

Service writes a heartbeat file every 60 seconds:

```env
HEALTH_CHECK_FILE=/tmp/pipeline_health
```

External monitors (Nagios, uptime scripts) check file age. If older than 5 minutes → service is hung or dead.

---

## 15. Complete End-to-End Data Flow

### Excel Ingest Cycle

```
 1. APScheduler fires excel_ingest job
 2. Create job_run record (UUID, type='excel_ingest', status='running')
 3. SFTP connect → chdir to SFTP_REMOTE_DIR (if set) → list files → find latest matching SFTP_FILE_PATTERN
        └── older than SFTP_SAFE_AGE_SECONDS
 4. Download to DOWNLOAD_DIR/{filename}
 5. Store metadata in excel_imports
 6. Parse Excel → transform rows (map "Shipment ID" → shipment_id, serialize full row as JSON for raw_row_data, skip null/empty IDs) → store in excel_import_rows
 7. Delete file from SFTP (if SFTP_DELETE_AFTER_INGEST=True)
 8. Compare with cargowise_containers_new → identify NEW shipment IDs
        └── mark is_new=True in excel_import_rows
 9. For each new shipment (parallel, MAX_PARALLEL_REQUESTS):
        ├── Insert shipment_tracking (status='pending')
        ├── Rate limit check (CW_RATE_LIMIT)
        ├── Circuit breaker check (abort if threshold hit)
        ├── Mark 'in_progress'
        ├── CargoWiseClient.fetch_shipment(sid)
        ├── CargoWiseClient.fetch_documents(sid)
        ├── parser.parse_shipment() → flat record
        ├── Fetch ETA/ETD history → apply snapshot logic
        ├── milestones.build_milestones() → milestones_new
        ├── milestones.build_milestones_reformed() → milestones_reformed
        ├── Derive status (Active/Delivered)
        ├── db.upsert_shipment(record)
        ├── Mark 'completed' (or retry/fail)
        └── Dead letter check (lifetime retries)
10. Update job_run summary
11. Send failure email if any failures
12. Update excel_imports.status = 'completed'
13. Trigger AIR Sync (event-driven, skips duplicates from step 9)
14. Trigger SEA Sync (event-driven, skips duplicates from step 9)
```

### Nightly Jobs

```
Midnight:
├── SEA Reverse → query SEA_REVERSE_QUERY → parallel process
├── Nightly Retry (if enabled) → query failed shipments → reset retry_count → re-process

2 AM:
└── Archive → S3 upload old files/logs → purge old tracking records → local cleanup
```

### Service Restart

```
Service starts → recover_interrupted()
    ├── Find orphaned shipments (in_progress/pending from interrupted job_runs)
    ├── Create recovery job_run, re-associate orphaned shipments
    ├── Mark old interrupted job_runs as 'failed'
    ├── Process recovered shipments immediately (parallel)
    ├── Send recovery notice email
    └── APScheduler starts for future scheduled jobs
```

---

## 16. Updated Dependencies

```
pymysql>=1.1.0
DBUtils>=3.1.0
pandas>=2.0.0
requests>=2.31.0
xmltodict>=0.13.0
python-dotenv>=1.0.0
paramiko>=3.4.0
APScheduler>=3.10.0
boto3>=1.34.0
```

Added: `DBUtils` (connection pooling for pymysql), `APScheduler`, `boto3`.
Removed: `mysql-connector-python` (unified on `pymysql`).

---

## 17. Migration Path

1. Deploy new `pipeline/` directory alongside existing `cron_jobs/`
2. Run `migrations.sql` to create new tables (non-destructive — existing tables untouched)
3. Disable system crontab entries
4. Install and start systemd service
5. Monitor via health check file + email alerts
6. Validate for 1-2 weeks — compare output with old system
7. Remove old `cron_jobs/`, `core/`, `new_milestones5.py` after validation
8. Drop `system_flags` table (no longer needed — event-driven chaining replaces `excel_sync_last_run` flag; `excel_ran_recently()` function eliminated)
9. Remove `core/utils.py` lockfile mechanism (replaced by APScheduler `max_instances` + `shipment_tracking`)

**Note**: During the validation period, do NOT run old cron jobs and new service simultaneously — they would both write to `cargowise_containers_new` and could conflict.

---

## 18. Manual Job Runner (`run_manual.py`)

For testing individual jobs without the scheduler:

```bash
python3 run_manual.py download        # SFTP download + store rows in DB only (no CW sync)
python3 run_manual.py ingest          # Full ingest: download + CW sync + AIR/SEA chain
python3 run_manual.py air             # AIR sync only
python3 run_manual.py sea             # SEA sync (critical window) only
python3 run_manual.py reverse         # SEA reverse (midnight job)
python3 run_manual.py retry           # Nightly retry (failed shipments)
python3 run_manual.py archive         # Archive old files to S3 + purge tracking
python3 run_manual.py all             # Full cycle: ingest → air → sea → reverse
```

The `download` command uses `run_download_only()` which shares the `_download_and_store()` helper with the full `run()` function — DRY, same SFTP/parse/store logic.
