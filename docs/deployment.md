# Deployment Checklist

1. Copy `pipeline/` directory to `/home/ubuntu/pipeline/`
2. Copy `.env` with production credentials (use `.env.example` as template)
3. Install dependencies: `pip install -r requirements.txt`
4. Run migrations: `mysql -u USER -p DB_NAME < pipeline/sql/migrations.sql`
5. Disable existing crontab entries: `crontab -e` (comment out all pipeline jobs)
6. Install systemd unit: `sudo cp pipeline.service /etc/systemd/system/`
7. Reload systemd: `sudo systemctl daemon-reload`
8. Enable and start: `sudo systemctl enable pipeline && sudo systemctl start pipeline`
9. Verify: `sudo systemctl status pipeline` and check health file
10. Monitor for 1-2 weeks
11. After validation: remove old `cron_jobs/`, `core/`, `new_milestones5.py`
12. Drop `system_flags` table: `DROP TABLE IF EXISTS system_flags;`

## Rollback

1. Stop service: `sudo systemctl stop pipeline`
2. Re-enable crontab entries
3. Old code still works independently (shares same DB table `cargowise_containers_new`)

## Monitoring

- Health check: `stat /tmp/pipeline_health` — file should be <5 min old
- Logs: `journalctl -u pipeline -f` or check `pipeline.log`
- DB: `SELECT * FROM job_runs ORDER BY started_at DESC LIMIT 10;`
