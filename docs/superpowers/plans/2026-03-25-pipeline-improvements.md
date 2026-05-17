# Pipeline Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the monolithic shipment pipeline into a service-based architecture with parallel processing, retry/resume, internal scheduling, Excel DB storage, error notifications, and S3 archival.

**Architecture:** APScheduler-based Python service running under systemd. ThreadPoolExecutor for parallel shipment processing. Event-driven job chaining (Excel → AIR/SEA sync). Per-shipment tracking in MySQL for retry/resume. All config via `.env`.

**Tech Stack:** Python 3, pymysql, DBUtils (PooledDB), APScheduler, pandas, requests, xmltodict, paramiko, boto3, python-dotenv

**Spec:** `docs/superpowers/specs/2026-03-25-pipeline-improvements-design.md`

---

## File Map

| File | Responsibility | Creates/Modifies |
|------|---------------|------------------|
| `pipeline/__init__.py` | Package init | Create |
| `pipeline/config.py` | `.env` loading, validation, settings object | Create |
| `pipeline/helpers.py` | safe_dict, safe_list, safe_text, get_value, first_non_null, date helpers | Create (extract from `new_milestones5.py`) |
| `pipeline/db.py` | Connection pool (DBUtils), all queries, tracking, upserts | Create |
| `pipeline/cargowise.py` | XML builders, API POST, rate limiting, circuit breaker | Create (extract from `new_milestones5.py`) |
| `pipeline/parser.py` | XML response → flat record dict via focused extractors | Create (extract from `new_milestones5.py`) |
| `pipeline/milestones.py` | Data-driven milestone building, delay calc, status derivation | Create (extract+refactor from `new_milestones5.py`) |
| `pipeline/sftp.py` | SFTP connect, list, download, delete | Create (extract from `cron_jobs/excel_ingest.py`) |
| `pipeline/excel.py` | Parse Excel, store rows + metadata in DB | Create |
| `pipeline/notifications.py` | SMTP email sender | Create |
| `pipeline/archiver.py` | S3 upload, local cleanup | Create |
| `pipeline/jobs/__init__.py` | Jobs package init | Create |
| `pipeline/jobs/excel_ingest.py` | Excel ingest orchestration | Create |
| `pipeline/jobs/sync_air.py` | AIR sync job | Create |
| `pipeline/jobs/sync_sea.py` | SEA sync + reverse jobs | Create |
| `pipeline/jobs/nightly_retry.py` | Retry failed shipments | Create |
| `pipeline/jobs/archive.py` | Archive job | Create |
| `pipeline/scheduler.py` | APScheduler setup, job registration, chaining | Create |
| `pipeline/service.py` | Main entry, signal handling, health check | Create |
| `pipeline/sql/migrations.sql` | New table DDL | Create |
| `tests/` | Test files per module | Create |
| `requirements.txt` | Updated dependencies | Modify |
| `.env.example` | Template with placeholders | Create |
| `pipeline/log_setup.py` | Logging setup: TimedRotatingFileHandler, named loggers | Create |
| `pipeline.service` | systemd unit file | Create |
| `run_manual.py` | Manual job runner for testing without scheduler | Create |

**Notes:**
- `pytest` is a dev dependency — install via `pip install pytest` (not in production requirements.txt)
- `.env` must be in `.gitignore` — verify during Task 1
- RAIL transport mode has no separate SEQUENCES entry — it is handled as a variation within SEA (rail milestones appear in all SEA sequences). Tests should verify RAIL mode falls back gracefully.

---

### Task 1: Foundation — Config, Helpers, Dependencies

**Files:**
- Create: `pipeline/__init__.py`
- Create: `pipeline/config.py`
- Create: `pipeline/helpers.py`
- Create: `pipeline/log_setup.py`
- Create: `.env.example`
- Modify: `requirements.txt`
- Modify: `.gitignore` (ensure `.env` is listed)
- Test: `tests/__init__.py`, `tests/test_config.py`, `tests/test_helpers.py`

- [ ] **Step 1: Create package structure and verify .gitignore**

```bash
mkdir -p pipeline/jobs pipeline/sql tests
touch pipeline/__init__.py pipeline/jobs/__init__.py tests/__init__.py
```
Verify `.env` is in `.gitignore`. If not, add it.

- [ ] **Step 2: Update requirements.txt**

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

- [ ] **Step 3: Create `.env.example`**

Copy the full `.env` template from spec Section 3 with all placeholder values. This is the reference for all configuration.

- [ ] **Step 4: Write test for config loading**

```python
# tests/test_config.py
import os
import pytest

def test_settings_loads_required_vars(monkeypatch):
    required = {"DB_HOST": "localhost", "DB_USER": "test", "DB_PASSWORD": "test",
                "DB_NAME": "test", "CW_API_URL": "http://test", "CW_USERNAME": "u",
                "CW_PASSWORD": "p", "SFTP_HOST": "h", "SFTP_USERNAME": "u",
                "SFTP_PASSWORD": "p", "SMTP_SERVER": "s", "SMTP_USERNAME": "u",
                "SMTP_PASSWORD": "p", "ERROR_EMAIL_RECIPIENTS": "a@b.com"}
    for k, v in required.items():
        monkeypatch.setenv(k, v)
    from pipeline.config import Settings
    s = Settings()
    assert s.DB_HOST == "localhost"
    assert s.MAX_PARALLEL_REQUESTS == 5  # default
    assert s.CW_AUTH_MODE == "header"  # default
    assert s.CW_VERIFY_SSL is False  # default

def test_settings_raises_on_missing_required(monkeypatch):
    monkeypatch.delenv("DB_HOST", raising=False)
    from pipeline.config import Settings
    with pytest.raises(ValueError):
        Settings()
```

- [ ] **Step 5: Implement `pipeline/config.py`**

```python
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    def __init__(self):
        # Database
        self.DB_HOST = self._required("DB_HOST")
        self.DB_USER = self._required("DB_USER")
        self.DB_PASSWORD = self._required("DB_PASSWORD")
        self.DB_NAME = self._required("DB_NAME")
        self.DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))

        # CargoWise
        self.CW_API_URL = self._required("CW_API_URL")
        self.CW_CLIENT_ID = os.getenv("CW_CLIENT_ID", "")
        self.CW_CLIENT_SECRET = os.getenv("CW_CLIENT_SECRET", "")
        self.CW_USERNAME = self._required("CW_USERNAME")
        self.CW_PASSWORD = self._required("CW_PASSWORD")
        self.CW_ORIGIN = os.getenv("CW_ORIGIN", "")
        self.CW_TIMEOUT = int(os.getenv("CW_TIMEOUT", "60"))
        self.CW_RATE_LIMIT = int(os.getenv("CW_RATE_LIMIT", "10"))
        self.CW_CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CW_CIRCUIT_BREAKER_THRESHOLD", "5"))
        self.CW_AUTH_MODE = os.getenv("CW_AUTH_MODE", "header").lower()  # "header" or "basic"
        self.CW_VERIFY_SSL = os.getenv("CW_VERIFY_SSL", "False").lower() in ("1", "true", "yes")
        self.CW_SHIPMENT_COMPANY_CODE = os.getenv("CW_SHIPMENT_COMPANY_CODE", "INJ")
        self.CW_DOCUMENT_COMPANY_CODE = os.getenv("CW_DOCUMENT_COMPANY_CODE", "VWT")
        self.CW_DOCUMENT_DATA_PROVIDER = os.getenv("CW_DOCUMENT_DATA_PROVIDER", "GWSTRVWR")
        self.CW_ENTERPRISE_ID = os.getenv("CW_ENTERPRISE_ID", "GWS")
        self.CW_SERVER_ID = os.getenv("CW_SERVER_ID", "TR2")

        # SFTP
        self.SFTP_HOST = self._required("SFTP_HOST")
        self.SFTP_PORT = int(os.getenv("SFTP_PORT", "22"))
        self.SFTP_USERNAME = self._required("SFTP_USERNAME")
        self.SFTP_PASSWORD = self._required("SFTP_PASSWORD")
        self.SFTP_REMOTE_DIR = os.getenv("SFTP_REMOTE_DIR", "")
        self.SFTP_FILE_PATTERN = os.getenv("SFTP_FILE_PATTERN", "Shipment Profile Report *.xlsx")
        self.SFTP_SAFE_AGE_SECONDS = int(os.getenv("SFTP_SAFE_AGE_SECONDS", "60"))
        self.SFTP_DELETE_AFTER_INGEST = os.getenv("SFTP_DELETE_AFTER_INGEST", "True").lower() in ("1", "true", "yes")

        # Scheduler
        self.EXCEL_INGEST_SCHEDULE = os.getenv("EXCEL_INGEST_SCHEDULE", "0 10 */3 * *")
        self.SEA_REVERSE_SCHEDULE = os.getenv("SEA_REVERSE_SCHEDULE", "0 0 * * *")
        self.NIGHTLY_RETRY_ENABLED = os.getenv("NIGHTLY_RETRY_ENABLED", "True").lower() in ("1", "true", "yes")
        self.NIGHTLY_RETRY_SCHEDULE = os.getenv("NIGHTLY_RETRY_SCHEDULE", "30 0 * * *")
        self.ARCHIVE_ENABLED = os.getenv("ARCHIVE_ENABLED", "True").lower() in ("1", "true", "yes")
        self.ARCHIVE_SCHEDULE = os.getenv("ARCHIVE_SCHEDULE", "0 2 * * *")
        self.JOB_MAX_INSTANCES = int(os.getenv("JOB_MAX_INSTANCES", "1"))

        # Sync parameters
        self.SEA_ETA_WINDOW_DAYS = int(os.getenv("SEA_ETA_WINDOW_DAYS", "3"))
        self.AIR_SYNC_TRANSPORT_MODE = os.getenv("AIR_SYNC_TRANSPORT_MODE", "AIR")
        self.AIR_SYNC_STATUS = os.getenv("AIR_SYNC_STATUS", "Active")
        self.SEA_SYNC_TRANSPORT_MODE = os.getenv("SEA_SYNC_TRANSPORT_MODE", "SEA")
        self.SEA_SYNC_STATUS = os.getenv("SEA_SYNC_STATUS", "Active")

        # Parallelism & Retry
        self.MAX_PARALLEL_REQUESTS = int(os.getenv("MAX_PARALLEL_REQUESTS", "5"))
        self.SHIPMENT_RETRY_MAX = int(os.getenv("SHIPMENT_RETRY_MAX", "3"))
        self.SHIPMENT_RETRY_DELAY = int(os.getenv("SHIPMENT_RETRY_DELAY", "30"))
        self.SHIPMENT_MAX_LIFETIME_RETRIES = int(os.getenv("SHIPMENT_MAX_LIFETIME_RETRIES", "10"))

        # Email
        self.SMTP_SERVER = self._required("SMTP_SERVER")
        self.SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
        self.SMTP_USERNAME = self._required("SMTP_USERNAME")
        self.SMTP_PASSWORD = self._required("SMTP_PASSWORD")
        self.SMTP_FROM = os.getenv("SMTP_FROM", self.SMTP_USERNAME)
        self.SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "VIN World Pipeline")
        self.ERROR_EMAIL_RECIPIENTS = [e.strip() for e in self._required("ERROR_EMAIL_RECIPIENTS").split(",") if e.strip()]
        self.JOB_REPORT_RECIPIENTS = [e.strip() for e in os.getenv("JOB_REPORT_RECIPIENTS", "").split(",") if e.strip()]

        # S3
        self.AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET", "")
        self.AWS_S3_ARCHIVE_PREFIX = os.getenv("AWS_S3_ARCHIVE_PREFIX", "archives/")
        self.AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
        self.AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
        self.AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
        self.ARCHIVE_AGE_DAYS = int(os.getenv("ARCHIVE_AGE_DAYS", "7"))

        # General
        self.DEBUG = os.getenv("DEBUG", "False").lower() in ("1", "true", "yes")
        self.LOG_FILE = os.getenv("LOG_FILE", "pipeline.log")
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
        self.LOG_ROTATION = os.getenv("LOG_ROTATION", "daily")
        self.DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/tmp/pipeline_downloads")
        self.HEALTH_CHECK_FILE = os.getenv("HEALTH_CHECK_FILE", "/tmp/pipeline_health")
        self.TRACKING_RETENTION_DAYS = int(os.getenv("TRACKING_RETENTION_DAYS", "30"))

    def _required(self, key):
        val = os.getenv(key)
        if not val:
            raise ValueError(f"Required environment variable {key} is not set")
        return val

settings = Settings()
```

- [ ] **Step 6: Write tests for helpers**

```python
# tests/test_helpers.py
from pipeline.helpers import safe_dict, safe_list, safe_text, get_value, first_non_null
from pipeline.helpers import parse_iso_dt, iso_str, calculate_delay_days, format_port

def test_safe_dict():
    assert safe_dict(None) == {}
    assert safe_dict({"a": 1}) == {"a": 1}

def test_safe_list():
    assert safe_list(None) == []
    assert safe_list({"a": 1}) == [{"a": 1}]
    assert safe_list([1, 2]) == [1, 2]

def test_safe_text():
    assert safe_text(None) is None
    assert safe_text({}) is None
    assert safe_text("hello") == "hello"
    assert safe_text("") is None

def test_get_value():
    d = {"a": {"b": {"c": "val"}}}
    assert get_value(d, ["a", "b", "c"]) == "val"
    assert get_value(d, ["a", "x"]) is None

def test_first_non_null():
    assert first_non_null(None, "", "a") == "a"
    assert first_non_null(None) is None

def test_parse_iso_dt():
    dt = parse_iso_dt("2024-03-15T10:30:00Z")
    assert dt is not None
    assert dt.hour == 10

def test_calculate_delay_days():
    assert calculate_delay_days("2024-03-15T00:00:00Z", "2024-03-17T00:00:00Z") == 2
    assert calculate_delay_days(None, "2024-03-17T00:00:00Z") is None

def test_format_port():
    assert format_port({"Name": "Dubai", "Code": "AEDXB"}) == "Dubai(AEDXB)"
    assert format_port(None) is None
```

- [ ] **Step 7: Implement `pipeline/helpers.py`**

Extract from `new_milestones5.py` lines 68-141 and 267-345: `safe_dict`, `safe_list`, `safe_text`, `dump_json`, `get_value`, `first_non_null`, `format_port`, `format_address`, `parse_iso_dt`, `iso_str`, `calculate_delay_days`, `_planned_from_eta`. Same logic, no changes.

- [ ] **Step 8: Implement `pipeline/log_setup.py`**

```python
# pipeline/log_setup.py
import logging
import os
from logging.handlers import TimedRotatingFileHandler

def setup_logging(settings):
    """Configure logging with daily rotation + console output."""
    log_dir = os.path.dirname(settings.LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger("pipeline")
    root.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")

    # File handler with daily rotation
    fh = TimedRotatingFileHandler(settings.LOG_FILE, when="midnight", backupCount=30)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler (for systemd journal)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    return root
```

All modules get loggers via `logging.getLogger("pipeline.module_name")`.

- [ ] **Step 9: Run tests, verify pass**

```bash
pytest tests/test_config.py tests/test_helpers.py -v
```

- [ ] **Step 10: Commit**

```bash
git add pipeline/ tests/ requirements.txt .env.example
git commit -m "feat: add config, helpers, and package structure"
```

---

### Task 2: Database Layer — Schema, Connection Pool, Queries

**Files:**
- Create: `pipeline/sql/migrations.sql`
- Create: `pipeline/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Create `pipeline/sql/migrations.sql`**

Copy the 4 `CREATE TABLE` statements from spec Section 5: `job_runs`, `shipment_tracking`, `excel_imports`, `excel_import_rows`. All with `ON DELETE CASCADE` foreign keys.

- [ ] **Step 2: Write DB tests**

```python
# tests/test_db.py
import pytest
from unittest.mock import MagicMock, patch

def test_database_get_existing_shipment_ids():
    from pipeline.db import Database
    db = Database.__new__(Database)
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [{"JS_UniqueConsignRef": "S001"}, {"JS_UniqueConsignRef": "S002"}]
    mock_conn.cursor.return_value = mock_cursor
    db._pool = MagicMock()
    db._pool.connection.return_value = mock_conn
    result = db.get_existing_shipment_ids()
    assert result == {"S001", "S002"}

def test_database_create_job_run():
    from pipeline.db import Database
    db = Database.__new__(Database)
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    db._pool = MagicMock()
    db._pool.connection.return_value = mock_conn
    job_id = db.create_job_run("excel_ingest")
    assert len(job_id) == 36  # UUID
    mock_cursor.execute.assert_called_once()
```

- [ ] **Step 3: Write ETA/ETD snapshot tests**

```python
# tests/test_db.py (append)
def test_eta_snapshot_first_insert():
    """First time: both currentETA and updatedETA get same value."""
    from pipeline.db import apply_eta_snapshot
    existing = {"currentETA": None, "updatedETA": None}
    result = apply_eta_snapshot(existing, "2024-03-20T00:00:00Z")
    assert result["currentETA"] == "2024-03-20T00:00:00Z"
    assert result["updatedETA"] == "2024-03-20T00:00:00Z"

def test_eta_snapshot_update_preserves_original():
    """Subsequent: currentETA changes, updatedETA stays frozen."""
    from pipeline.db import apply_eta_snapshot
    existing = {"currentETA": "2024-03-20T00:00:00Z", "updatedETA": "2024-03-20T00:00:00Z"}
    result = apply_eta_snapshot(existing, "2024-03-22T00:00:00Z")
    assert result["currentETA"] == "2024-03-22T00:00:00Z"
    assert result["updatedETA"] == "2024-03-20T00:00:00Z"  # frozen

def test_eta_snapshot_no_change():
    """Same value: nothing changes."""
    from pipeline.db import apply_eta_snapshot
    existing = {"currentETA": "2024-03-20T00:00:00Z", "updatedETA": "2024-03-20T00:00:00Z"}
    result = apply_eta_snapshot(existing, "2024-03-20T00:00:00Z")
    assert result["currentETA"] == "2024-03-20T00:00:00Z"
    assert result["updatedETA"] == "2024-03-20T00:00:00Z"
```

- [ ] **Step 4: Implement `pipeline/db.py` — connection pool and core queries**

Implement `Database` class:
- `__init__`: Create `DBUtils.PooledDB` with pymysql, `DB_POOL_SIZE` connections
- `get_connection()`: Returns pooled connection (thread-safe)
- `get_existing_shipment_ids()` → set
- `fetch_eta_etd(shipment_id)` → dict with currentETA/updatedETA/currentETD/updatedETD
- `fetch_actuals(shipment_id)` → dict with currentActualArrival/updatedActualArrival/etc.
- `upsert_shipment(record)` — INSERT or UPDATE by JS_UniqueConsignRef
- `get_active_shipments(query_template, params)` → list of shipment IDs
- SQL query templates for AIR sync, SEA sync, SEA reverse (with `STR_TO_DATE`/`COALESCE`)

Also implement standalone `apply_eta_snapshot(existing, new_value)` and `apply_actual_snapshot(existing, new_value)` — pure functions for the dual-column snapshot logic (testable without DB).

- [ ] **Step 5: Implement `pipeline/db.py` — tracking and Excel operations**

Add to `Database` class:
- `create_job_run(job_type)` → UUID string
- `complete_job_run(job_run_id, processed, failed)`
- `track_shipment(shipment_id, job_run_id, job_type, status)`
- `update_tracking(shipment_id, job_run_id, status, error=None)`
- `get_interrupted()` → list (in_progress/pending from running job_runs)
- `get_failed_shipments()` → list (failed in last 24h, lifetime < max)
- `get_dead_letter_shipments()` → list (lifetime >= max)
- `was_processed_in_cycle(shipment_id, parent_job_run_id)` → bool
- `mark_do_not_query(shipment_id)` — sets `do_not_query=1`
- `save_excel_metadata(metadata)` → import_id
- `save_excel_rows(import_id, rows)`
- `purge_old_tracking(retention_days)`

- [ ] **Step 6: Run tests, verify pass**

```bash
pytest tests/test_db.py -v
```

- [ ] **Step 5: Commit**

```bash
git add pipeline/sql/ pipeline/db.py tests/test_db.py
git commit -m "feat: add database layer with connection pool and tracking"
```

---

### Task 3: CargoWise API Client

**Files:**
- Create: `pipeline/cargowise.py`
- Test: `tests/test_cargowise.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_cargowise.py
from pipeline.cargowise import CargoWiseClient, build_shipment_xml, build_documents_xml

def test_build_shipment_xml_contains_shipment_id():
    xml = build_shipment_xml("S00012345")
    assert "S00012345" in xml
    assert "<Code>INJ</Code>" in xml
    assert "GWSTRVWR" not in xml  # shipment uses INJ, not VWT

def test_build_documents_xml_contains_shipment_id():
    xml = build_documents_xml("S00012345")
    assert "S00012345" in xml
    assert "<Code>VWT</Code>" in xml
    assert "GWSTRVWR" in xml

def test_rate_limiter_allows_within_limit():
    from pipeline.cargowise import RateLimiter
    rl = RateLimiter(max_per_second=100)
    rl.acquire()  # should not block
```

- [ ] **Step 2: Implement `pipeline/cargowise.py`**

- `build_shipment_xml(shipment_id)` — Company=INJ, Enterprise=GWS, Server=TR2
- `build_documents_xml(shipment_id)` — Company=VWT, DataProvider=GWSTRVWR
- `RateLimiter` class — token bucket, thread-safe via `threading.Lock`
- `CargoWiseClient` class:
  - `__init__(settings)` — stores config, creates RateLimiter
  - `fetch_shipment(shipment_id)` → parsed Shipment dict
  - `fetch_documents(shipment_id)` → list of document dicts (guards each navigation level with `or {}` — CW can return None for nested keys)
  - `_post(xml_payload, headers)` — rate limit → POST with Basic Auth → xmltodict.parse

- [ ] **Step 3: Run tests, verify pass**

```bash
pytest tests/test_cargowise.py -v
```

- [ ] **Step 4: Commit**

```bash
git add pipeline/cargowise.py tests/test_cargowise.py
git commit -m "feat: add CargoWise API client with rate limiting"
```

---

### Task 4: Parser — XML Field Extraction

**Files:**
- Create: `pipeline/parser.py`
- Test: `tests/test_parser.py`

- [ ] **Step 1: Write tests with sample data**

```python
# tests/test_parser.py
from pipeline.parser import parse_shipment, _extract_ids, _extract_ports

SAMPLE_SHIPMENT = {
    "TransportMode": {"Code": "SEA"},
    "WayBillNumber": "HBL12345",
    "WayBillType": {"Code": "HWB", "Description": "House Waybill"},
    "PortOfOrigin": {"Name": "Dubai", "Code": "AEDXB"},
    "PortOfDestination": {"Name": "New York", "Code": "USNYC"},
    "SubShipmentCollection": {"SubShipment": {}},
}

def test_extract_ids():
    result = _extract_ids(SAMPLE_SHIPMENT, {})
    assert result["JS_HouseBill"] == "HBL12345"

def test_extract_ports_trade_type():
    result = _extract_ports(SAMPLE_SHIPMENT, {})
    assert result["tradeType"] == "Import"  # destination is US
```

- [ ] **Step 2: Implement extractors group 1 — IDs, parties, ports**

Create `pipeline/parser.py` with:
- `_extract_subshipment(shipment_dict)` — SubShipmentCollection navigation (takes first if list)
- `_extract_ids(shipment, sub)` — JS_HouseBill, JS_BookingReference (AIR=WayBillNumber, SEA=fallback chain), masterBillNumber
- `_extract_parties(shipment, sub)` — iterate OrganizationAddressCollection for consignee, shipper, addresses
- `_extract_ports(shipment, sub)` — origin, destination via format_port(), trade type (US logic)

Same logic as `new_milestones5.py` lines 2877-2958. Each function 20-40 lines.

- [ ] **Step 3: Implement extractors group 2 — containers, carrier, transport**

Add to `pipeline/parser.py`:
- `_extract_containers(shipment, sub)` — ContainerCollection, count, numbers, seals, types, dimensions (FT/CM)
- `_extract_carrier(shipment, sub)` — carrier from TransportLeg, 3-level SCAC fallback
- `_extract_transport(shipment, sub)` — mode, vessel, voyage, isRailMove, JS_ScreeningStatus, JS_PackingMode

Same logic as `new_milestones5.py` lines 2963-3097, 3552-3570.

- [ ] **Step 4: Implement extractors group 3 — dates, order refs, misc, orchestrator**

Add to `pipeline/parser.py`:
- `_extract_order_refs(shipment, sub)` — LocalProcessing → OrderNumberCollection
- `_extract_dates(shipment, sub)` — CustomizedField (A)/(M) extraction + MilestoneCollection fallbacks for Gate Out, Gate In Rail, ATA Rail, confirmedOnBoardDate, etaAtTerminal, dischargedDate, emptyReturnedDate
- `_extract_misc(shipment, sub)` — goods desc, INCO, console (JSPK), open_track, holds, history, etc.
- `parse_shipment(shipment_id, shipment_dict, documents)` — top-level orchestrator calling all extractors

Same logic as `new_milestones5.py` lines 3102-3260, 3262-3600.

- [ ] **Step 3: Run tests, verify pass**

```bash
pytest tests/test_parser.py -v
```

- [ ] **Step 4: Commit**

```bash
git add pipeline/parser.py tests/test_parser.py
git commit -m "feat: add parser with focused field extractors"
```

---

### Task 5: Milestones — Data-Driven DRY Builder

**Files:**
- Create: `pipeline/milestones.py`
- Test: `tests/test_milestones.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_milestones.py
from pipeline.milestones import build_milestones, build_milestones_reformed, derive_status
from pipeline.milestones import extract_milestones_from_customized_fields, SEQUENCES

def test_sea_dtd_has_9_milestones():
    actuals = {"Opened": "2024-01-01T00:00:00Z"}
    dates = {"currentETA": "2024-03-20T00:00:00Z", "currentETD": "2024-03-01T00:00:00Z"}
    result = build_milestones("SEA", "DTD", actuals, dates)
    assert len(result) == 9
    assert result[0]["eventStatus"] == "Opened"
    assert result[0]["status"] == "Completed"
    assert result[-1]["eventStatus"] == "Delivered"

def test_air_ptp_has_7_milestones():
    result = build_milestones("AIR", "PTP", {}, {})
    assert len(result) == 7

def test_sailed_delay_calculated():
    actuals = {"ATD Custom": "2024-03-03T00:00:00Z"}
    dates = {"currentETD": "2024-03-01T00:00:00Z"}
    result = build_milestones("SEA", "DTD", actuals, dates)
    sailed = next(m for m in result if m["eventStatus"] == "Sailed")
    assert sailed["delay"] == 2

def test_derive_status_active():
    milestones = [{"customField": "Delivered", "status": "Pending"}]
    status, statuses = derive_status(milestones, "SEA", "DTD")
    assert status == "Active"

def test_derive_status_delivered():
    milestones = [{"customField": "Delivered", "status": "Completed"}]
    status, statuses = derive_status(milestones, "SEA", "DTD")
    assert status == "Delivered"

def test_all_sequences_defined():
    expected = [("SEA","DTD"),("SEA","DTP"),("SEA","PTD"),("SEA","PTP"),
                ("AIR","DTD"),("AIR","DTP"),("AIR","PTD"),("AIR","PTP")]
    for key in expected:
        assert key in SEQUENCES, f"Missing sequence: {key}"

def test_rail_mode_returns_empty_sequence():
    """RAIL has no separate sequence — handled as variation within SEA."""
    result = build_milestones("RAIL", "DTD", {}, {})
    assert result == []  # No RAIL-specific sequence; RAIL uses SEA flows via transport mode detection in parser

def test_unknown_service_level_returns_empty():
    result = build_milestones("SEA", "UNKNOWN", {}, {})
    assert result == []
```

- [ ] **Step 2: Implement `pipeline/milestones.py`**

- `SEQUENCES` dict — all 8 transport/service level combinations as data tuples `(cf_key, label, planned_source, calc_delay)`
- `PLANNED_FIELD_MAP` — for reformed milestones
- `build_milestones(transport_mode, service_level, actuals, dates, buffer_days=4)` — single builder
- `_resolve_planned(source, dates, actuals, buffer_days)` — maps source key to date value
- `build_milestones_reformed(transport_mode, service_level, customized_fields)` — uses actual/planned maps + PLANNED_FIELD_MAP
- `extract_milestones_from_customized_fields(customized_fields, transport_mode)` — raw extraction with (A)/(M) priority
- `derive_status(milestones, transport_mode, service_level)` — checks last milestone completion
- `get_last_completed_event(milestones, transport_mode, service_level)` — returns delay/date/event of last completed

- [ ] **Step 3: Run tests, verify pass**

```bash
pytest tests/test_milestones.py -v
```

- [ ] **Step 4: Commit**

```bash
git add pipeline/milestones.py tests/test_milestones.py
git commit -m "feat: add data-driven milestone builder (8 builders → 1)"
```

---

### Task 6: SFTP and Excel

**Files:**
- Create: `pipeline/sftp.py`
- Create: `pipeline/excel.py`
- Test: `tests/test_sftp.py`, `tests/test_excel.py`

- [ ] **Step 1: Write SFTP tests**

```python
# tests/test_sftp.py
import re
import time
from unittest.mock import MagicMock
from pipeline.sftp import find_latest_matching_file

def test_find_latest_file_selects_newest():
    pattern = re.compile(r"Shipment Profile Report .*\.xlsx$", re.IGNORECASE)
    now = time.time()
    file1 = MagicMock()
    file1.filename = "Shipment Profile Report (2024-03-18 09-10-00).XLSX"
    file1.st_mtime = now - 300  # 5 min old
    file2 = MagicMock()
    file2.filename = "Shipment Profile Report (2024-03-19 14-30-00).XLSX"
    file2.st_mtime = now - 120  # 2 min old
    file3 = MagicMock()
    file3.filename = "other_file.xlsx"
    file3.st_mtime = now - 60
    result = find_latest_matching_file([file1, file2, file3], pattern, safe_age=60)
    assert result.filename == "Shipment Profile Report (2024-03-19 14-30-00).XLSX"

def test_find_latest_file_skips_too_recent():
    pattern = re.compile(r"Shipment Profile Report .*\.xlsx$", re.IGNORECASE)
    now = time.time()
    file1 = MagicMock()
    file1.filename = "Shipment Profile Report (2024-03-18 09-10-00).XLSX"
    file1.st_mtime = now - 10  # only 10s old, below safe_age=60
    result = find_latest_matching_file([file1], pattern, safe_age=60)
    assert result is None
```

- [ ] **Step 2: Implement `pipeline/sftp.py`**

Extract from `cron_jobs/excel_ingest.py` lines 39-95:
- `SFTPClient` class with `__init__(settings)`, `download_latest(pattern)` → local path, `delete_file(filename)`, `close()`
- File pattern matching via `re.compile`
- Safe age check, retry logic (3 attempts, 3s delay)
- Keepalive=30s on transport

- [ ] **Step 3: Write Excel tests**

```python
# tests/test_excel.py
def test_parse_excel_extracts_shipment_ids(tmp_path):
    import pandas as pd
    df = pd.DataFrame({"Shipment ID": ["S001", "S002", None, "S003"]})
    path = tmp_path / "test.xlsx"
    df.to_excel(path, index=False)
    from pipeline.excel import parse_excel
    ids, rows = parse_excel(str(path))
    assert ids == ["S001", "S002", "S003"]
    assert len(rows) == 3
```

- [ ] **Step 4: Implement `pipeline/excel.py`**

- `parse_excel(file_path)` → `(shipment_ids, rows_as_dicts)`
  - Reads with pandas, normalizes IDs (dropna, str, strip, upper)
  - Returns list of IDs and list of raw row dicts (original Excel column names)
  - **Important**: The caller (`excel_ingest.py`) must transform rows before passing to `db.save_excel_rows()`:
    - Map `"Shipment ID"` → `"shipment_id"`
    - Serialize full row dict as JSON string → `"raw_row_data"`
    - Skip rows where `"Shipment ID"` is null/empty
    - Set `"is_new"` flag

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_sftp.py tests/test_excel.py -v
```

- [ ] **Step 6: Commit**

```bash
git add pipeline/sftp.py pipeline/excel.py tests/test_sftp.py tests/test_excel.py
git commit -m "feat: add SFTP client and Excel parser"
```

---

### Task 7: Email Notifications

**Files:**
- Create: `pipeline/notifications.py`
- Test: `tests/test_notifications.py`

- [ ] **Step 1: Write notification tests**

```python
# tests/test_notifications.py
from unittest.mock import patch, MagicMock
from pipeline.notifications import EmailNotifier

def test_job_failure_email_subject():
    settings = MagicMock()
    settings.SMTP_FROM_NAME = "Test Pipeline"
    settings.ERROR_EMAIL_RECIPIENTS = ["a@b.com"]
    notifier = EmailNotifier(settings)
    with patch.object(notifier, '_send') as mock_send:
        job_run = {"job_type": "AIR Sync", "id": "abc-123", "total": 45, "failed": 3}
        notifier.send_job_failure(job_run, [{"shipment_id": "S001", "error": "timeout"}])
        mock_send.assert_called_once()
        subject = mock_send.call_args[0][1]
        assert "AIR Sync" in subject
        assert "3" in subject

def test_send_catches_smtp_errors():
    settings = MagicMock()
    settings.SMTP_SERVER = "bad-server"
    settings.SMTP_PORT = 587
    settings.SMTP_USERNAME = "user"
    settings.SMTP_PASSWORD = "pass"
    settings.SMTP_FROM = "from@test.com"
    notifier = EmailNotifier(settings)
    # Should not raise — logs error instead
    notifier._send(["to@test.com"], "Test", "Body")  # will fail SMTP but not crash

def test_recovery_notice_includes_count():
    settings = MagicMock()
    settings.ERROR_EMAIL_RECIPIENTS = ["a@b.com"]
    notifier = EmailNotifier(settings)
    with patch.object(notifier, '_send') as mock_send:
        notifier.send_recovery_notice(12)
        body = mock_send.call_args[0][2]
        assert "12" in body
```

- [ ] **Step 2: Implement `pipeline/notifications.py`**

- `EmailNotifier` class:
  - `__init__(settings)` — stores SMTP config
  - `send_job_failure(job_run, failed_shipments)` — formats failure email per spec Section 11
  - `send_job_report(job_run)` — optional completion report
  - `send_recovery_notice(recovered_count)` — restart notification
  - `send_circuit_breaker_alert(job_run, consecutive_failures)`
  - `send_dead_letter_alert(shipment_id, total_retries)`
  - `_send(recipients, subject, body, attachments=None)` — SMTP with TLS, catches errors, logs but never crashes

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_notifications.py -v
```

- [ ] **Step 4: Commit**

```bash
git add pipeline/notifications.py tests/test_notifications.py
git commit -m "feat: add email notifications with SMTP"
```

---

### Task 8: Shared Processing Logic — process_shipment and run_job

**Files:**
- Create: `pipeline/jobs/processing.py`
- Test: `tests/test_processing.py`

- [ ] **Step 1: Write processing tests**

```python
# tests/test_processing.py
from unittest.mock import MagicMock, patch, PropertyMock
from requests.exceptions import Timeout, ConnectionError

def test_process_shipment_marks_completed_on_success():
    from pipeline.jobs.processing import process_shipment
    db = MagicMock()
    db.fetch_eta_etd.return_value = {"currentETA": None, "updatedETA": None, "currentETD": None, "updatedETD": None}
    db.fetch_actuals.return_value = {"currentActualArrival": None, "updatedActualArrival": None, "currentActualDeparture": None, "updatedActualDeparture": None}
    cw = MagicMock()
    cw.fetch_shipment.return_value = {"TransportMode": {"Code": "AIR"}, "SubShipmentCollection": {}}
    cw.fetch_documents.return_value = []
    settings = MagicMock()
    settings.SHIPMENT_RETRY_MAX = 3
    result = process_shipment("S001", "run-1", db, cw, settings)
    assert result["status"] == "completed"
    db.update_tracking.assert_called()

def test_process_shipment_returns_retry_on_timeout():
    from pipeline.jobs.processing import process_shipment
    db = MagicMock()
    cw = MagicMock()
    cw.fetch_shipment.side_effect = Timeout("timed out")
    settings = MagicMock()
    settings.SHIPMENT_RETRY_MAX = 3
    result = process_shipment("S001", "run-1", db, cw, settings, retry_count=0)
    assert result["status"] == "retry"
    assert result["retry_count"] == 1

def test_process_shipment_fails_after_max_retries():
    from pipeline.jobs.processing import process_shipment
    db = MagicMock()
    cw = MagicMock()
    cw.fetch_shipment.side_effect = Timeout("timed out")
    settings = MagicMock()
    settings.SHIPMENT_RETRY_MAX = 3
    result = process_shipment("S001", "run-1", db, cw, settings, retry_count=3)
    assert result["status"] == "failed"

def test_circuit_breaker_stops_after_threshold():
    from pipeline.jobs.processing import run_job
    db = MagicMock()
    cw = MagicMock()
    cw.fetch_shipment.side_effect = ConnectionError("down")
    notifier = MagicMock()
    settings = MagicMock()
    settings.MAX_PARALLEL_REQUESTS = 1
    settings.CW_CIRCUIT_BREAKER_THRESHOLD = 3
    settings.SHIPMENT_RETRY_MAX = 0
    settings.SHIPMENT_RETRY_DELAY = 0
    shipment_ids = [f"S{i:03d}" for i in range(10)]
    run_job("test", shipment_ids, db, cw, notifier, settings)
    notifier.send_circuit_breaker_alert.assert_called_once()
```

- [ ] **Step 2: Implement `pipeline/jobs/processing.py`**

- `process_shipment(shipment_id, job_run_id, db, cw_client, settings, retry_count=0)`:
  - Mark in_progress → fetch shipment → fetch docs → parse → ETA/ETD snapshot → milestones → upsert → mark completed
  - Returns `{"status": "completed"|"retry"|"failed", ...}`
  - On Timeout/ConnectionError: returns `retry` if under max, else `failed`
  - On other Exception: returns `failed` with traceback
  - Increments `lifetime_retry_count` on failure; checks dead letter threshold

- `run_job(job_type, shipment_ids, db, cw_client, notifier, settings, parent_job_run_id=None)`:
  - Create job_run → bulk insert tracking → ThreadPoolExecutor
  - Circuit breaker: counts consecutive failures, stops after threshold
  - Retry collection: gathers `retry` results, waits `SHIPMENT_RETRY_DELAY`, re-submits
  - Duplicate guard: skips if `db.was_processed_in_cycle(sid, parent_job_run_id)`
  - Updates job_run summary, sends failure email if needed

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_processing.py -v
```

- [ ] **Step 4: Commit**

```bash
git add pipeline/jobs/processing.py tests/test_processing.py
git commit -m "feat: add shared processing logic with parallel execution and circuit breaker"
```

---

### Task 9: Individual Job Implementations

**Files:**
- Create: `pipeline/jobs/excel_ingest.py`
- Create: `pipeline/jobs/sync_air.py`
- Create: `pipeline/jobs/sync_sea.py`
- Create: `pipeline/jobs/nightly_retry.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write job tests**

```python
# tests/test_jobs.py
from unittest.mock import MagicMock, patch

def test_excel_ingest_calls_sftp_and_stores_rows():
    from pipeline.jobs.excel_ingest import run
    db = MagicMock()
    db.get_existing_shipment_ids.return_value = {"S001"}
    cw = MagicMock()
    notifier = MagicMock()
    settings = MagicMock()
    settings.SFTP_DELETE_AFTER_INGEST = False
    with patch("pipeline.jobs.excel_ingest.SFTPClient") as mock_sftp, \
         patch("pipeline.jobs.excel_ingest.parse_excel") as mock_excel, \
         patch("pipeline.jobs.excel_ingest.run_job") as mock_run:
        mock_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp.return_value)
        mock_sftp.return_value.__exit__ = MagicMock(return_value=False)
        mock_sftp.return_value.download_latest.return_value = "/tmp/test.xlsx"
        mock_excel.return_value = (["S001", "S002"], [{"Shipment ID": "S001"}, {"Shipment ID": "S002"}])
        run(db, cw, notifier, settings)
        db.save_excel_metadata.assert_called_once()
        db.save_excel_rows.assert_called_once()
        # Only S002 is new (S001 already in DB)
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "S002" in call_args[0][1]  # shipment_ids arg
        assert "S001" not in call_args[0][1]

def test_sync_air_skips_duplicates_from_parent():
    from pipeline.jobs.sync_air import run
    db = MagicMock()
    db.get_active_shipments.return_value = ["S001", "S002", "S003"]
    db.was_processed_in_cycle.side_effect = lambda sid, _: sid == "S001"
    with patch("pipeline.jobs.sync_air.run_job") as mock_run:
        run(db, MagicMock(), MagicMock(), MagicMock(), parent_job_run_id="parent-123")
        call_args = mock_run.call_args
        shipment_ids = call_args[0][1]
        assert "S001" not in shipment_ids
        assert "S002" in shipment_ids

def test_nightly_retry_skips_dead_letter():
    from pipeline.jobs.nightly_retry import run
    db = MagicMock()
    db.get_failed_shipments.return_value = [
        {"shipment_id": "S001", "lifetime_retry_count": 5},
        {"shipment_id": "S002", "lifetime_retry_count": 15},  # over threshold
    ]
    settings = MagicMock()
    settings.SHIPMENT_MAX_LIFETIME_RETRIES = 10
    with patch("pipeline.jobs.nightly_retry.run_job") as mock_run:
        run(db, MagicMock(), MagicMock(), settings)
        call_args = mock_run.call_args
        assert "S001" in call_args[0][1]
        assert "S002" not in call_args[0][1]
```

- [ ] **Step 2: Implement `pipeline/jobs/excel_ingest.py`**

Three functions sharing a common helper:

- `_clean_row(row)` — replaces NaN with None for valid JSON serialization
- `_download_and_store(db, settings, job_run_id)` — shared helper:
  1. SFTP download via SFTPClient
  2. Store metadata via `db.save_excel_metadata`
  3. Parse Excel, transform rows (map "Shipment ID" → shipment_id, clean NaN, serialize as JSON, skip nulls)
  4. Store rows via `db.save_excel_rows`
  5. Delete from SFTP (if enabled)
  6. Compare with DB → identify new IDs
  7. Return `(shipment_ids, new_ids, import_id)` or `(None, None, None)` if no file

- `run_download_only(db, settings)` — download + DB populate only (no CW sync)
- `run(db, cw_client, notifier, settings)` — full ingest: calls `_download_and_store()` then `run_job()` for new shipments

- [ ] **Step 2b: Implement `run_manual.py`**

Manual job runner for testing without the scheduler:
```bash
python3 run_manual.py download    # SFTP download + DB populate only
python3 run_manual.py ingest      # Full ingest + AIR/SEA chain
python3 run_manual.py air         # AIR sync only
python3 run_manual.py sea         # SEA sync only
python3 run_manual.py reverse     # SEA reverse
python3 run_manual.py retry       # Nightly retry
python3 run_manual.py archive     # Archive + purge
python3 run_manual.py all         # Full cycle
```

- [ ] **Step 3: Implement `pipeline/jobs/sync_air.py` and `pipeline/jobs/sync_sea.py`**

- AIR: `run(db, cw, notifier, settings, parent_job_run_id=None)` — query, filter duplicates, run_job
- SEA sync: `run_sync(db, cw, notifier, settings, parent_job_run_id=None)` — critical window query
- SEA reverse: `run_reverse(db, cw, notifier, settings)` — remainder query

- [ ] **Step 4: Implement `pipeline/jobs/nightly_retry.py`**

- `run(db, cw, notifier, settings)`:
  - Get failed shipments, filter out dead letters, call `run_job()`
  - Mark dead letter shipments (`do_not_query=1`, send alert)

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_jobs.py -v
```

- [ ] **Step 6: Commit**

```bash
git add pipeline/jobs/ tests/test_jobs.py
git commit -m "feat: add Excel ingest, AIR/SEA sync, and nightly retry jobs"
```

---

### Task 10: Archiver — S3 Upload and Cleanup

**Files:**
- Create: `pipeline/archiver.py`
- Create: `pipeline/jobs/archive.py`
- Test: `tests/test_archiver.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_archiver.py
from unittest.mock import MagicMock, patch
from pipeline.archiver import Archiver

def test_archive_identifies_old_files(tmp_path):
    import os, time
    old_file = tmp_path / "old.xlsx"
    old_file.write_text("data")
    os.utime(old_file, (time.time() - 86400 * 10, time.time() - 86400 * 10))
    # Test that archiver identifies this as eligible for upload
```

- [ ] **Step 2: Implement `pipeline/archiver.py`**

- `Archiver` class:
  - `__init__(settings)` — boto3 S3 client
  - `archive_excel_files(db)` — query excel_imports where s3_archive_path IS NULL and old enough, upload, update path
  - `archive_logs()` — scan log directory, upload old logs
  - `cleanup_local()` — remove orphaned local files

- [ ] **Step 3: Implement `pipeline/jobs/archive.py`**

- `run(db, settings)`:
  1. Create archiver
  2. `archiver.archive_excel_files(db)`
  3. `archiver.archive_logs()`
  4. `archiver.cleanup_local()`
  5. `db.purge_old_tracking(settings.TRACKING_RETENTION_DAYS)`

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_archiver.py -v
```

- [ ] **Step 5: Commit**

```bash
git add pipeline/archiver.py pipeline/jobs/archive.py tests/test_archiver.py
git commit -m "feat: add S3 archiver with retention cleanup"
```

---

### Task 11: Scheduler and Service Entry Point

**Files:**
- Create: `pipeline/scheduler.py`
- Create: `pipeline/service.py`
- Create: `pipeline.service` (systemd unit)
- Test: `tests/test_scheduler.py`, `tests/test_service.py`

- [ ] **Step 1: Write scheduler tests**

```python
# tests/test_scheduler.py
from pipeline.scheduler import parse_cron_schedule

def test_parse_cron_schedule():
    result = parse_cron_schedule("0 10 */3 * *")
    assert result["minute"] == "0"
    assert result["hour"] == "10"

def test_parse_cron_schedule_midnight():
    result = parse_cron_schedule("0 0 * * *")
    assert result["hour"] == "0"
```

- [ ] **Step 2: Implement `pipeline/scheduler.py`**

- `parse_cron_schedule(cron_str)` — splits "min hour day month dow" into APScheduler CronTrigger kwargs
- `setup_scheduler(settings, db, cw_client, notifier)`:
  1. Create `BackgroundScheduler`
  2. Register excel_ingest on `EXCEL_INGEST_SCHEDULE` with `max_instances=JOB_MAX_INSTANCES`
  3. Register sea_reverse on `SEA_REVERSE_SCHEDULE`
  4. Register nightly_retry on `NIGHTLY_RETRY_SCHEDULE` (if enabled)
  5. Register archive on `ARCHIVE_SCHEDULE` (if `ARCHIVE_ENABLED=True`)
  6. Excel ingest callback chains to AIR + SEA sync on completion
  7. Return scheduler

- [ ] **Step 3: Write service tests**

```python
# tests/test_service.py
from unittest.mock import MagicMock, patch
import os
import tempfile

def test_recover_interrupted_creates_recovery_run():
    from pipeline.service import recover_interrupted
    db = MagicMock()
    db.get_interrupted.return_value = [
        {"shipment_id": "S001", "job_run_id": "old-run"},
        {"shipment_id": "S002", "job_run_id": "old-run"},
    ]
    notifier = MagicMock()
    settings = MagicMock()
    with patch("pipeline.service.run_job") as mock_run:
        recover_interrupted(db, MagicMock(), notifier, settings)
        db.create_job_run.assert_called_with("recovery")
        notifier.send_recovery_notice.assert_called_with(2)
        mock_run.assert_called_once()

def test_health_check_touches_file():
    from pipeline.service import touch_health_check
    with tempfile.NamedTemporaryFile(delete=False) as f:
        path = f.name
    touch_health_check(path)
    assert os.path.exists(path)
    os.unlink(path)

def test_graceful_shutdown_marks_pending():
    from pipeline.service import graceful_shutdown
    db = MagicMock()
    # Verify it marks in_progress shipments as pending
    graceful_shutdown(db)
    db.update_tracking.assert_called()  # or specific pending marking
```

- [ ] **Step 4: Implement `pipeline/service.py`**

- `recover_interrupted(db, cw_client, notifier, settings)`:
  1. `db.get_interrupted()` → orphaned shipments
  2. `db.create_job_run("recovery")` → new run ID
  3. Re-associate and reset to pending
  4. Mark old running job_runs as failed
  5. `notifier.send_recovery_notice(count)` — send email
  6. Process recovered shipments via `run_job()`

- `touch_health_check(path)` — writes timestamp to file

- `graceful_shutdown(db)` — marks in_progress as pending, logs

- `main()`:
  1. `setup_logging(settings)` from `pipeline/log_setup.py`
  2. Create `Database`, `CargoWiseClient`, `EmailNotifier`
  3. `recover_interrupted()` — with email notification
  4. Register SIGTERM/SIGINT → `graceful_shutdown()`
  5. Start health check thread (touches file every 60s)
  6. `setup_scheduler()` → `scheduler.start()`
  7. Block until shutdown signal

- [ ] **Step 5: Create systemd unit file**

```ini
# pipeline.service
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

- [ ] **Step 6: Run all tests**

```bash
pytest tests/ -v
```

- [ ] **Step 7: Commit**

```bash
git add pipeline/scheduler.py pipeline/service.py pipeline.service tests/test_scheduler.py tests/test_service.py
git commit -m "feat: add scheduler and service entry point with systemd"
```

---

### Task 12: Integration Test and Migration

**Files:**
- Modify: `pipeline/sql/migrations.sql` (finalize)
- Test: `tests/test_integration.py`

- [ ] **Step 1: Write integration tests**

```python
# tests/test_integration.py
"""
End-to-end smoke test using mocked external services.
"""
from unittest.mock import MagicMock, patch
import json

SAMPLE_CW_RESPONSE = {
    "TransportMode": {"Code": "SEA"},
    "WayBillNumber": "HBL999",
    "WayBillType": {"Code": "HWB", "Description": "House Waybill"},
    "PortOfOrigin": {"Name": "Dubai", "Code": "AEDXB"},
    "PortOfDestination": {"Name": "Houston", "Code": "USHOU"},
    "SubShipmentCollection": {"SubShipment": {
        "ServiceLevel": {"Code": "DTD"},
        "CustomizedFieldCollection": {"CustomizedField": [
            {"Key": "Opened(A)", "Value": "2024-01-01T00:00:00Z"},
            {"Key": "ATD Custom(A)", "Value": "2024-03-03T00:00:00Z"},
            {"Key": "ETD Custom(A)", "Value": "2024-03-01T00:00:00Z"},
        ]},
    }},
}

def test_full_shipment_processing_pipeline():
    from pipeline.jobs.processing import process_shipment
    db = MagicMock()
    db.fetch_eta_etd.return_value = {"currentETA": None, "updatedETA": None, "currentETD": None, "updatedETD": None}
    db.fetch_actuals.return_value = {"currentActualArrival": None, "updatedActualArrival": None, "currentActualDeparture": None, "updatedActualDeparture": None}
    cw = MagicMock()
    cw.fetch_shipment.return_value = SAMPLE_CW_RESPONSE
    cw.fetch_documents.return_value = []
    settings = MagicMock()
    settings.SHIPMENT_RETRY_MAX = 3
    settings.SHIPMENT_MAX_LIFETIME_RETRIES = 10
    result = process_shipment("S999", "run-1", db, cw, settings)
    assert result["status"] == "completed"
    # Verify upsert was called with a record containing milestones
    upsert_call = db.upsert_shipment.call_args[0][0]
    assert upsert_call["JS_UniqueConsignRef"] == "S999"
    assert upsert_call["JS_TransportMode"] == "SEA"
    assert upsert_call["tradeType"] == "Import"  # destination is US
    milestones = json.loads(upsert_call["milestones_new"])
    assert len(milestones) == 9  # SEA DTD
    sailed = next(m for m in milestones if m["eventStatus"] == "Sailed")
    assert sailed["status"] == "Completed"
    assert sailed["delay"] == 2  # 2 days late

def test_excel_ingest_chains_to_air_sync():
    from pipeline.scheduler import setup_scheduler
    settings = MagicMock()
    settings.EXCEL_INGEST_SCHEDULE = "0 10 */3 * *"
    settings.SEA_REVERSE_SCHEDULE = "0 0 * * *"
    settings.NIGHTLY_RETRY_ENABLED = False
    settings.ARCHIVE_SCHEDULE = "0 2 * * *"
    settings.JOB_MAX_INSTANCES = 1
    db = MagicMock()
    cw = MagicMock()
    notifier = MagicMock()
    scheduler = setup_scheduler(settings, db, cw, notifier)
    # Verify excel_ingest job is registered
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert "excel_ingest" in jobs
    scheduler.shutdown(wait=False)
```

- [ ] **Step 2: Run integration tests**

```bash
pytest tests/test_integration.py -v
```

- [ ] **Step 3: Finalize migrations.sql**

Ensure all 4 tables are correct, add any indexes discovered during implementation.

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

- [ ] **Step 5: Commit**

```bash
git add pipeline/sql/migrations.sql tests/test_integration.py
git commit -m "feat: add integration tests and finalize migrations"
```

- [ ] **Step 6: Update CLAUDE.md for new architecture**

Update `CLAUDE.md` to document:
- New module structure under `pipeline/`
- How to run: `python pipeline/service.py` or via systemd
- How to deploy: copy to server, run migrations, install systemd unit
- Configuration via `.env` (reference `.env.example`)

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for new pipeline architecture"
```

- [ ] **Step 7: Create deployment checklist**

Add to `docs/deployment.md`:

```markdown
# Deployment Checklist

1. Copy `pipeline/` directory to `/home/ubuntu/pipeline/`
2. Copy `.env` with production credentials
3. Install dependencies: `pip install -r requirements.txt`
4. Run migrations: `mysql -u USER -p DB_NAME < pipeline/sql/migrations.sql`
5. Disable existing crontab entries: `crontab -e` (comment out all pipeline jobs)
6. Install systemd unit: `sudo cp pipeline.service /etc/systemd/system/`
7. Enable and start: `sudo systemctl enable pipeline && sudo systemctl start pipeline`
8. Verify: `sudo systemctl status pipeline` and check health file
9. Monitor for 1-2 weeks
10. After validation: remove old `cron_jobs/`, `core/`, `new_milestones5.py`
11. Drop `system_flags` table: `DROP TABLE system_flags;`
```

```bash
git add docs/deployment.md
git commit -m "docs: add deployment checklist"
```
