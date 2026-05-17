# import logging
# from pipeline.jobs.processing import run_job

# logger = logging.getLogger("pipeline.jobs.sync_sea")

# def run_sync(db, cw_client, notifier, settings, parent_job_run_id=None):
#     """Sync critical SEA shipments (ETD set but no ATD, or ETA 3 days out)."""
#     shipment_ids = db.get_active_shipments("sea_sync", settings)
#     logger.info(f"Found {len(shipment_ids)} critical SEA shipments")
#     if shipment_ids:
#         run_job("sea_sync", shipment_ids, db, cw_client, notifier, settings, parent_job_run_id=parent_job_run_id)

# def run_reverse(db, cw_client, notifier, settings):
#     """Sync remaining active SEA shipments (midnight job)."""
#     shipment_ids = db.get_active_shipments("sea_reverse", settings)
#     logger.info(f"Found {len(shipment_ids)} reverse SEA shipments")
#     if shipment_ids:
#         run_job("sea_reverse", shipment_ids, db, cw_client, notifier, settings)




import logging
from pipeline.jobs.processing import run_job

logger = logging.getLogger("pipeline.jobs.sync_sea")



SEA_SYNC_EXTRA = """
(
    (
        currentETD IS NOT NULL
        AND COALESCE(
            STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%dT%%H:%%i:%%s'),
            STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%d %%H:%%i:%%s')
        ) IS NULL
    )
    OR DATE(currentETA) = CURRENT_DATE + INTERVAL %(window)s DAY
)
"""


SEA_REVERSE_EXTRA = """
(
    (
        currentETD IS NULL
        OR COALESCE(
            STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%dT%%H:%%i:%%s'),
            STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%d %%H:%%i:%%s')
        ) IS NOT NULL
    )
    AND (
        currentETA IS NULL
        OR DATE(currentETA) <> CURRENT_DATE + INTERVAL %(window)s DAY
    )
)
"""


def run_sync(db, cw_client, notifier, settings, parent_job_run_id=None):
    """
    Sync critical SEA shipments:
    - ETD exists but ATD missing
    - OR ETA within configured window
    """
    shipment_ids = db.get_active_shipments(
        settings.SEA_SYNC_TRANSPORT_MODE,   # "SEA"
        settings.SEA_SYNC_STATUS,           # "Active"
        extra_where=SEA_SYNC_EXTRA,        
        params={
            "window": settings.SEA_ETA_WINDOW_DAYS
        },
    )

    logger.info(f"[SEA SYNC] Found {len(shipment_ids)} critical shipments")

    if shipment_ids:
        run_job(
            "sea_sync",
            shipment_ids,
            db,
            cw_client,
            notifier,
            settings,
            parent_job_run_id=parent_job_run_id,
        )


def run_reverse(db, cw_client, notifier, settings , parent_job_run_id=None):
    """
    Sync remaining SEA shipments (non-critical):
    - ETD missing OR ATD already present
    - AND ETA not in window
    """
    shipment_ids = db.get_active_shipments(
        settings.SEA_SYNC_TRANSPORT_MODE,   # "SEA"
        settings.SEA_SYNC_STATUS,           # "Active"
        extra_where=SEA_REVERSE_EXTRA,     
        params={
            "window": settings.SEA_ETA_WINDOW_DAYS
        },
    )

    logger.info(f"[SEA REVERSE] Found {len(shipment_ids)} reverse shipments")

    if shipment_ids:
        run_job(
            "sea_reverse",
            shipment_ids,
            db,
            cw_client,
            notifier,
            settings,
            parent_job_run_id=parent_job_run_id,
        )