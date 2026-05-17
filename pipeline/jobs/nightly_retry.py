import logging
from pipeline.jobs.processing import run_job

logger = logging.getLogger("pipeline.jobs.nightly_retry")

def run(db, cw_client, notifier, settings):
    """Retry all failed shipments from last 24h. Mark dead letters."""
    failed = db.get_failed_shipments()
    eligible = []
    for f in failed:
        if f.get("lifetime_retry_count", 0) >= settings.SHIPMENT_MAX_LIFETIME_RETRIES:
            sid = f["shipment_id"]
            db.mark_do_not_query(sid)
            notifier.send_dead_letter_alert(sid, f["lifetime_retry_count"])
            logger.warning(f"Dead letter: {sid} after {f['lifetime_retry_count']} retries")
        else:
            eligible.append(f["shipment_id"])

    if eligible:
        logger.info(f"Retrying {len(eligible)} failed shipments")
        run_job("nightly_retry", eligible, db, cw_client, notifier, settings)
    else:
        logger.info("No eligible shipments to retry")
