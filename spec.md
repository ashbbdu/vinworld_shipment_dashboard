# VIN World Shipment Dashboard — Pipeline Spec

Context snapshot for Claude / future maintainers. Last refreshed: 2026-05-28.

## Purpose

A Python data pipeline that powers the VIN World shipment-tracking dashboard.
It pulls shipment IDs from operations-generated Excel files (delivered by
Couchdrop SFTP), enriches each shipment via the CargoWise eAdaptor XML API,
computes milestone progress and delay metrics per transport mode / service
level, and writes the result into a MySQL table that the dashboard reads.

## Tech Stack

- Python 3, dependencies pinned in `requirements.txt`:
  `pymysql`, `DBUtils`, `pandas`, `requests`, `xmltodict`, `paramiko`,
  `APScheduler`, `boto3`, `python-dotenv`.
- MySQL on AWS RDS (target DB selected by `DB_NAME`).
- CargoWise eAdaptor XML API for shipment + document data.
- AWS S3 for archived shipments + Excel files (`AWS_S3_BUCKET`).
- SMTP for error and job-run notifications.
- APScheduler runs all jobs in-process (replaces the legacy crontab).
- systemd manages the service on the Ubuntu host
  (`config/pipeline-prod.service`, `pipeline-uat.service`,
  `pipeline-local.service`).

## Configuration Model

All settings live in `.env`-style files and are read **only** through
`pipeline/config.Settings`. No module calls `os.getenv()` directly.

- `PIPELINE_ENV` selects the env file:
  - `PIPELINE_ENV=prod` → `config/.env.prod`
  - `PIPELINE_ENV=uat`  → `config/.env.uat`
  - unset → repo-root `.env` (legacy fallback)
- `.env.example` is the canonical list of every variable the pipeline reads.
- `Settings._required(key)` raises on missing required keys — startup fails
  fast rather than running with half a config.

## Data Flow

```
   ┌──────────────────────┐
   │ Couchdrop SFTP       │  Shipment Profile Report *.xlsx
   └──────────┬───────────┘
              │ pipeline/sftp.py
              ▼
   ┌──────────────────────┐
   │ pipeline/excel.py    │  parse rows, extract shipment IDs
   └──────────┬───────────┘
              │ excel_imports / excel_import_rows
              ▼
   ┌──────────────────────┐
   │ jobs/excel_ingest.py │  insert new shipments, kick off chain
   └──────────┬───────────┘
              │ (event-driven, after Excel completes)
              ├──────────────────┐
              ▼                  ▼
   ┌──────────────────┐   ┌──────────────────┐
   │ jobs/sync_air.py │   │ jobs/sync_sea.py │  CargoWise enrichment
   └──────────┬───────┘   └──────────┬───────┘
              │                       │
              ▼                       ▼
   ┌────────────────────────────────────────────┐
   │ pipeline/cargowise.py  → parser.py         │
   │ pipeline/milestones.py → delay calc        │
   └──────────────────┬─────────────────────────┘
                      │
                      ▼
   ┌────────────────────────────────────────────┐
   │ MySQL: cargowise_containers_new (main)     │
   │        + job_runs / shipment_tracking      │
   └────────────────────────────────────────────┘
                      │
       ┌──────────────┼──────────────┐
       ▼              ▼              ▼
  sea_reverse   nightly_retry    archive (S3)
  (midnight)    (00:30)          (02:00)
```

## Module Map

### `pipeline/` (core)

| File | LOC | Purpose |
|------|----:|---------|
| `config.py` | 131 | `Settings` class; resolves `PIPELINE_ENV` → env file; validates required vars. |
| `db.py` | 2836 | Database layer. Pooled connections, upsert, ETA snapshot, tracking tables, interrupted-shipment recovery, archive queries. The largest module — heart of the persistence layer. |
| `cargowise.py` | 475 | CargoWise eAdaptor client. Retry + circuit breaker + rate limit. Exposes `fetch_shipment`, `fetch_documents`. |
| `parser.py` | 811 | XML/dict → flat record. Field extraction, customized-fields decoding. |
| `milestones.py` | 857 | Data-driven milestone builder. `SEQUENCES[(mode, service_level)]` defines the ordered events; one builder collapses ~8 legacy variants. Delay-day computation lives here. |
| `helpers.py` | 204 | Pure utilities (date parsing, `safe_text`, `safe_list`, delay-day math). |
| `excel.py` | 18 | Thin wrapper over `pandas` for reading the Shipment Profile workbook. |
| `sftp.py` | 84 | Paramiko-based SFTP download with safe-age + optional remote delete. |
| `notifications.py` | 89 | SMTP error / job-report / recovery-notice emails. |
| `archiver.py` | 54 | Moves completed shipments out of the live table into S3. |
| `scheduler.py` | 87 | `parse_cron_schedule()` + `setup_scheduler()` wires APScheduler jobs. |
| `service.py` | 129 | Entry point. Loads settings, sets up logging, recovers interrupted work, starts scheduler, runs health-check loop, handles SIGTERM/SIGINT. |
| `log_setup.py` | 19 | Logging config. |
| `sql/migrations.sql` | — | DDL for the v2 tracking tables. |

### `pipeline/jobs/`

| File | LOC | Purpose |
|------|----:|---------|
| `processing.py` | 800 | Shared engine: `process_shipment()` + `run_job()`. Threaded fan-out, retry, tracking-row updates. |
| `excel_ingest.py` | 883 | Downloads Excel, parses rows, inserts new shipments, fires AIR + SEA sync on completion. |
| `sync_air.py` | 15 | Thin entry — selects active AIR shipments, delegates to `run_job`. |
| `sync_sea.py` | 115 | Two entry points: `run_sync` (chained after Excel) and `run_reverse` (midnight scan of ETA window). |
| `nightly_retry.py` | 23 | Picks up `failed` tracking rows under `SHIPMENT_MAX_LIFETIME_RETRIES`. |
| `archive.py` | 25 | Moves shipments older than `ARCHIVE_AGE_DAYS` to S3. |

### Top-level scripts

- `run_manual.py` — operator script for ad-hoc reprocessing.
- `pipeline.service` (root) — legacy systemd unit. Real units live in `config/`.

## Scheduled Jobs

Defined in `pipeline/scheduler.py`; cron strings come from settings.

| Job ID | Default cron | What it does |
|--------|--------------|--------------|
| `excel_ingest` | `0 10 */3 * *` (10:00 every 3rd day) | Pulls Excel, ingests new shipments, then **chains** `sync_air.run()` and `sync_sea.run_sync()`. |
| `sea_reverse` | `0 0 * * *` (midnight) | Re-scans SEA shipments whose ETA falls inside `SEA_ETA_WINDOW_DAYS`. Independent of Excel. |
| `nightly_retry` | `30 0 * * *` | Retries failed shipments. Gated by `NIGHTLY_RETRY_ENABLED`. |
| `archive` | `0 2 * * *` | Archives completed shipments > `ARCHIVE_AGE_DAYS` to S3. Gated by `ARCHIVE_ENABLED`. |

`JOB_MAX_INSTANCES` (default `1`) prevents overlapping runs.

## Transport Modes & Service Levels

`pipeline/milestones.py::SEQUENCES` is keyed by `(transport_mode,
service_level)`:

- Transport modes: `SEA`, `AIR`.
- Service levels: `DTD` (door-to-door), `DTP` (door-to-port),
  `PTD` (port-to-door), `PTP` (port-to-port).

Each entry is an ordered list of `(cf_key, label, planned_source, calc_delay)`
tuples. `planned_source` is one of `None`, `"etd"`, `"eta"`, `"arrived"`,
`"eta_buffer"`. To add or reorder a milestone, edit this dict — no builder
code changes needed.

## Database Schema (essentials)

Defined in `sql/tables.sql` (legacy main table) and
`pipeline/sql/migrations.sql` (v2 tracking tables).

- **`cargowise_containers_new`** — main shipment table. Unique key
  `uniq_shipment` on `JS_UniqueConsignRef`. Holds raw CargoWise fields,
  computed milestones (`milestones`, `milestones_new`, `milestones_reformed`),
  delay columns (`delay_in_departure`, `delay_in_arrival`, `delay_status`,
  `delay_actual_*`, `latest_completed_*`), and ETA/ETD snapshots
  (`currentETA`/`updatedETA`, `currentETD`/`updatedETD`).
- **`job_runs`** — one row per scheduled job execution
  (`running` / `completed` / `failed`, counts, error summary).
- **`shipment_tracking`** — one row per shipment per job run
  (`pending` / `in_progress` / `completed` / `failed`, `retry_count`,
  `lifetime_retry_count`). FK to `job_runs`.
- **`excel_imports`** — one row per Excel file ingested, with S3 archive path.
- **`excel_import_rows`** — per-row payload from the Excel file
  (`raw_row_data` JSON), used later when processing needs the original
  "Job Opened" date etc.
- **`system_flags`** — legacy table, scheduled for drop after the v2 cutover
  (see `docs/deployment.md`).

## Resilience

- **Circuit breaker** on CargoWise client (`CW_CIRCUIT_BREAKER_THRESHOLD`).
- **Rate limit** (`CW_RATE_LIMIT` requests/sec).
- **Per-shipment retry** (`SHIPMENT_RETRY_MAX` × `SHIPMENT_RETRY_DELAY`) plus
  a lifetime cap (`SHIPMENT_MAX_LIFETIME_RETRIES`).
- **Crash recovery**: `service.py::recover_interrupted()` runs on startup,
  finds tracking rows still `in_progress` from a prior process, marks the
  old job run failed, and re-queues them under a new `recovery` job run.
- **Health-check file** (`HEALTH_CHECK_FILE`, default `/tmp/pipeline_health`)
  is touched every 60s — external monitor checks staleness.

## Entry Points

```bash
# Long-running production service (one process, all jobs scheduled)
python3 -m pipeline.service

# One-shot job runs (useful for debugging or manual catch-up)
python3 -m pipeline.jobs.excel_ingest
python3 -m pipeline.jobs.sync_air
python3 -m pipeline.jobs.sync_sea
python3 -m pipeline.jobs.nightly_retry
python3 -m pipeline.jobs.archive

# Operator-driven ad-hoc reprocessing
python3 run_manual.py
```

Multi-env launch:

```bash
PIPELINE_ENV=prod python3 -m pipeline.service
PIPELINE_ENV=uat  python3 -m pipeline.service
```

## Testing

```bash
python3 -m pytest tests/ -v
```

236+ tests; per-module files in `tests/` matching the `pipeline/` layout
(`test_db.py`, `test_milestones.py`, `test_parser.py`, …) plus
`test_integration.py` and `test_processing.py`.

## Deployment

See `docs/deployment.md` for the full checklist (copy code, install deps,
run migrations, install systemd unit, validate, then drop legacy
`cron_jobs/`, `core/`, `new_milestones5.py`, and the `system_flags` table).
