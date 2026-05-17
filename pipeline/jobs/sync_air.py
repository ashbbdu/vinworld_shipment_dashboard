import logging
from pipeline.jobs.processing import run_job

logger = logging.getLogger("pipeline.jobs.sync_air")

def run(db, cw_client, notifier, settings, parent_job_run_id=None):
    # """Sync all active AIR shipments."""
    # shipment_ids = db.get_active_shipments("air_sync", settings)
    # logger.info(f"Found {len(shipment_ids)} active AIR shipments")
    shipment_ids = db.get_active_shipments(
        settings.AIR_SYNC_TRANSPORT_MODE,   # "AIR"
        settings.AIR_SYNC_STATUS,           # "Active"
    )
    if shipment_ids:
        run_job("air_sync", shipment_ids, db, cw_client, notifier, settings, parent_job_run_id=parent_job_run_id)
