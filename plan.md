# Working Notes for Claude

Operating manual for whoever (usually me, Claude) is about to touch this
repo. Pair with `spec.md` for the system snapshot. Last refreshed:
2026-05-28.

## Read This First

In order, before doing anything non-trivial:

1. `CLAUDE.md` — project instructions baked into the repo.
2. `spec.md` — current architecture + module map.
3. `.env.example` — every env var the pipeline reads.
4. `docs/deployment.md` — what production looks like and the rollback path.
5. `pipeline/config.py` — single source of truth for settings.

## Navigation Cheat Sheet

When the request is… look here:

| Request | Files to open |
|---------|---------------|
| Change which events appear in a milestone sequence | `pipeline/milestones.py` → `SEQUENCES[(mode, service_level)]` |
| Change a delay calculation | `pipeline/milestones.py` + `pipeline/helpers.py::calculate_delay_days` |
| Add a new env var | `.env.example` + `pipeline/config.py::Settings.__init__` + (usually) `tests/test_config.py` |
| Change a job's schedule | `.env` (`*_SCHEDULE` cron vars); no code change needed |
| Add a new scheduled job | new file in `pipeline/jobs/`, wire in `pipeline/scheduler.py::setup_scheduler`, add a `*_SCHEDULE` + optional `*_ENABLED` setting, add a test |
| Change how a CargoWise field is extracted | `pipeline/parser.py` |
| Change CargoWise auth / retry / rate-limit | `pipeline/cargowise.py` + `CW_*` settings |
| Change DB schema | `pipeline/sql/migrations.sql` + matching code in `pipeline/db.py` |
| Change main-table columns | also touch `sql/tables.sql` so fresh installs match |
| Change Excel parsing | `pipeline/excel.py` (small) + `pipeline/jobs/excel_ingest.py` (orchestration) |
| Change SFTP behaviour | `pipeline/sftp.py` + `SFTP_*` settings |
| Change archival rules | `pipeline/archiver.py` + `pipeline/jobs/archive.py` + `ARCHIVE_*` settings |
| Change which shipments AIR/SEA sync picks up | `pipeline/jobs/sync_air.py`, `pipeline/jobs/sync_sea.py` + `*_SYNC_TRANSPORT_MODE`, `*_SYNC_STATUS`, `SEA_ETA_WINDOW_DAYS` |
| Change how interrupted work recovers | `pipeline/service.py::recover_interrupted` + `Database.get_interrupted` |

## Conventions To Respect

- **Settings never via `os.getenv`** outside `pipeline/config.py`. Always read
  from a `Settings` instance passed in as an argument. If you see a new
  `os.getenv` outside config.py, move it.
- **Dependencies are passed in, not imported globally.** `service.py`
  constructs `Database`, `CargoWiseClient`, `EmailNotifier`, `Settings` and
  threads them through. Jobs receive them as args — they don't import
  singletons. Keep it that way (makes tests trivial).
- **Tests mirror module names.** `pipeline/foo.py` → `tests/test_foo.py`.
  Same for jobs (`tests/test_jobs.py` is shared across them).
- **Don't introduce a new monolith.** The v2 rewrite explicitly split the
  old `new_milestones5.py` into focused modules; resist adding cross-cutting
  helpers to one file.
- **The data-driven `SEQUENCES` dict replaces per-variant builders.** If
  tempted to write a new builder function for a new mode/service-level,
  add a `SEQUENCES` entry instead.
- **Health-check file must keep ticking.** Don't block the main thread for
  more than ~60s in `service.py`; long work belongs in scheduler jobs.

## Known Gotchas

- The **heads of `pipeline/jobs/processing.py` and `pipeline/milestones.py`
  are commented-out historical blocks.** The live code is further down the
  file. Don't waste time treating those leading comments as the current
  implementation — scroll past them.
- **`.DS_Store` is dirty in git.** That's macOS noise, not a real change.
- **Old per-day log files (`pipeline.log.2026-MM-DD`) accumulate in the
  repo root** and several are untracked. They're runtime artifacts — don't
  commit them, don't read them as source.
- **Two SQL locations exist:** `sql/tables.sql` (legacy main table DDL) and
  `pipeline/sql/migrations.sql` (v2 tracking tables). New schema work goes
  in `pipeline/sql/migrations.sql`; only touch `sql/tables.sql` if the main
  table structure itself is changing.
- **There are three systemd units** in `config/` (`pipeline-prod.service`,
  `pipeline-uat.service`, `pipeline-local.service`) plus a legacy
  `pipeline.service` in the repo root. The `config/` versions are
  authoritative; the root file is left over from before multi-env.
- **`process_shipment` reads the original Excel row** via `db.get_excel_row`
  to recover `Job Opened` date. Don't drop the `excel_import_rows`
  retention without checking — `TRACKING_RETENTION_DAYS` controls this.
- **`run_manual.py` is hand-operated**, not scheduled. It bypasses
  APScheduler — be careful, it'll happily double-process if the service is
  also running.

## Pending Cleanup (from `docs/deployment.md`)

After the production cutover is validated:

- [ ] Remove `cron_jobs/`, `core/`, `new_milestones5.py` (legacy monolith).
- [ ] `DROP TABLE IF EXISTS system_flags;` — replaced by `job_runs` /
      `shipment_tracking`.
- [ ] Old crontab entries should already be commented out on the host;
      confirm before deleting code.

Don't do these speculatively — they're load-bearing during rollback.

## Verification Before Claiming "Done"

For any non-trivial change, before declaring success:

```bash
# Type-/syntax-check by import
python3 -c "import pipeline.service, pipeline.scheduler, pipeline.db, pipeline.milestones"

# Full test suite
python3 -m pytest tests/ -v

# Targeted run if you only touched a couple of modules
python3 -m pytest tests/test_<module>.py -v

# Settings smoke test (catches missing required vars early)
PIPELINE_ENV=uat python3 -c "from pipeline.config import Settings; Settings()"
```

If a UI/dashboard change is involved: the dashboard is a separate consumer
of MySQL — this repo doesn't render it, so verification stops at "the DB
column has the value the dashboard expects."

## When Asked To Add A Feature

Default scaffold for a new scheduled job (the most common ask):

1. New file `pipeline/jobs/<name>.py` exposing `run(db, cw_client, notifier, settings)`.
2. Add `<NAME>_SCHEDULE` (cron) and `<NAME>_ENABLED` (bool) to
   `.env.example` and `pipeline/config.Settings`.
3. Wire into `pipeline/scheduler.setup_scheduler` behind the `_ENABLED` flag.
4. Add `tests/test_jobs.py::test_<name>_*` covering the happy path + at
   least one failure path.
5. Update `spec.md` "Scheduled Jobs" table.

For a new milestone event: edit `SEQUENCES` in `pipeline/milestones.py` and
add an assertion in `tests/test_milestones.py`. No other code changes
should be needed.

## What Lives Outside This Repo

- The **dashboard front-end** reads from MySQL directly; it lives in a
  separate codebase. This pipeline is upstream.
- **CargoWise eAdaptor** is the source of truth for shipment data —
  questions like "why is this field empty?" usually trace back there, not
  to a parsing bug.
- **Couchdrop SFTP** is the inbox for the Shipment Profile Reports;
  operations drops files there.
- **AWS RDS / S3** host the DB and the archive bucket — managed outside
  this repo.
