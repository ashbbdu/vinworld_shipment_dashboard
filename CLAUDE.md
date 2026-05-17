# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python-based data pipeline that syncs shipment data from the CargoWise XML API into a MySQL database, calculates milestones and delay metrics, and feeds a shipment tracking dashboard.

## Tech Stack

- **Python 3** — dependencies in `requirements.txt` (`pymysql`, `DBUtils`, `pandas`, `requests`, `xmltodict`, `paramiko`, `APScheduler`, `boto3`, `python-dotenv`)
- **MySQL** on AWS RDS — configured via `DB_NAME` env var
- **CargoWise eAdaptor XML API** for shipment data
- **APScheduler** — internal job scheduling (replaces system crontab)
- **systemd** — service management on Ubuntu server

## Running

```bash
python3 -m pipeline.service              # Long-running service (production)
python3 -m pytest tests/ -v              # Run all 236+ tests
```

## Architecture

### Data Flow

```
SFTP (Couchdrop) → Excel → pipeline/jobs/excel_ingest.py
                                  │
                                  ▼
                         CargoWise eAdaptor API
                                  │
                                  ▼
                    pipeline/parser.py + pipeline/milestones.py
                                  │
                                  ▼
                            MySQL (AWS RDS)
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
              sync_air.py   sync_sea.py   nightly_retry.py
              (event-driven, triggered by Excel ingest completion)
```

### Transport Modes & Service Levels

Supports SEA, AIR transport modes with service levels DTD, DTP, PTD, PTP. Milestone sequences defined as data in `pipeline/milestones.py` SEQUENCES dict.

## Configuration

All settings via `.env` — see `.env.example` for the full template. No module calls `os.getenv()` directly; all access goes through `pipeline/config.py` Settings class.

## New Pipeline Architecture (pipeline/)

The `pipeline/` package is a modular rewrite of the monolithic `new_milestones5.py`. It preserves all business logic but splits it into focused modules.

### Running (New)

```bash
python -m pipeline.service          # Long-running scheduler (replaces crontab)
python -m pipeline.jobs.excel_ingest  # One-shot excel ingest
python -m pipeline.jobs.sync_air      # One-shot AIR sync
python -m pipeline.jobs.sync_sea      # One-shot SEA sync
```

### New Module Map

- **`pipeline/config.py`** — Settings class, loads `.env`, all tunables in one place
- **`pipeline/db.py`** — Database layer with connection pooling, upsert, ETA snapshot logic
- **`pipeline/cargowise.py`** — CargoWise API client with retry and circuit breaker
- **`pipeline/parser.py`** — XML/dict response parsing, field extraction
- **`pipeline/milestones.py`** — Milestone definitions and delay calculation per mode/service level
- **`pipeline/helpers.py`** — Pure utility functions (date parsing, safe access, etc.)
- **`pipeline/excel.py`** — Excel file reading and shipment ID extraction
- **`pipeline/sftp.py`** — SFTP download of Excel files
- **`pipeline/notifications.py`** — Email alerting via SMTP
- **`pipeline/archiver.py`** — Completed shipment archival
- **`pipeline/scheduler.py`** — APScheduler-based job scheduling
- **`pipeline/service.py`** — Entry point: wires dependencies, starts scheduler
- **`pipeline/jobs/processing.py`** — Shared processing logic (`process_shipment`, `run_job`)
- **`pipeline/jobs/excel_ingest.py`** — Excel ingest job
- **`pipeline/jobs/sync_air.py`** — AIR transport sync job
- **`pipeline/jobs/sync_sea.py`** — SEA transport sync job
- **`pipeline/jobs/nightly_retry.py`** — Retry failed shipments
- **`pipeline/jobs/archive.py`** — Archival job

### Testing

```bash
python -m pytest tests/ -v          # Run all tests (232+ unit + integration)
```

### Deployment

See `docs/deployment.md` for the full checklist including systemd setup and rollback procedure.
