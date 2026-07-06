# import os
# import json
# import math
# import logging
# from pipeline.sftp import SFTPClient
# from pipeline.excel import parse_excel
# from pipeline.jobs.processing import run_job

# logger = logging.getLogger("pipeline.jobs.excel_ingest")


# def _clean_row(row):
#     """Replace NaN/NaT with None for valid JSON serialization."""
#     return {k: (None if (isinstance(v, float) and math.isnan(v)) else v)
#             for k, v in row.items()}


# # def _download_and_store(db, settings, job_run_id):
# #     """Download Excel from SFTP, parse, store metadata + rows in DB.

# #     Returns (shipment_ids, new_ids, import_id) or (None, None, None) if no file.
# #     """
# #     with SFTPClient(settings) as sftp:
# #         local_path, filename = sftp.download_latest()
# #         print("📥 Downloaded file:", filename, "at", local_path)
# #         if not local_path:
# #             logger.warning("No Excel file to process")
# #             return None, None, None

# #         # Store metadata
# #         print("💾 Saving Excel metadata to DB...")
# #         file_size = os.path.getsize(local_path)
# #         import_id = db.save_excel_metadata({
# #             "filename": filename,
# #             "sftp_path": filename,
# #             "file_size_bytes": file_size,
# #             "job_run_id": job_run_id,
# #             "local_path": local_path,
# #             "status": "downloaded",
# #         })
# #         print("✅ Metadata saved, import_id:", import_id)
# #         # Parse Excel
# #         shipment_ids, raw_rows = parse_excel(local_path)
# #         print(f"📊 Parsed {len(shipment_ids)} shipments")

# #         # Transform rows for DB storage
# #         db_rows = [
# #             {
# #                 "shipment_id": row.get("Shipment ID"),
# #                 "raw_row_data": json.dumps(_clean_row(row), default=str),
# #                 "is_new": False,
# #             }
# #             for row in raw_rows
# #             if row.get("Shipment ID")
# #         ]
# #         print(f"🚀 About to insert {len(db_rows)} rows into DB...")
# #         db.save_excel_rows(import_id, db_rows)
# #         logger.info(f"Parsed {len(shipment_ids)} shipments from {filename}")
# #         print("✅ Rows inserted successfully")

# #         # Delete from SFTP
# #         if settings.SFTP_DELETE_AFTER_INGEST:
# #             sftp.delete_file(filename)

# #         # Find new shipments
# #         existing = db.get_existing_shipment_ids()
# #         new_ids = [sid for sid in shipment_ids if sid not in existing]
# #         logger.info(f"Found {len(new_ids)} new shipments out of {len(shipment_ids)}")

# #         return shipment_ids, new_ids, import_id



# def _download_and_store(db, settings, job_run_id):
#     """
#     Download Excel from SFTP OR use local file, parse, store metadata + rows in DB.

#     Returns (shipment_ids, new_ids, import_id) or (None, None, None) if no file.
#     """

#     import os
#     import json

#     # ✅ TOGGLE (set this for local testing)
#     USE_LOCAL_FILE = True
#     LOCAL_FILE_PATH = "/Users/ashishsrivastava/Downloads/vin_world_shipment_dashboard/ShipmetList1.xlsx"

#     # =========================
#     # FILE SOURCE
#     # =========================
#     if USE_LOCAL_FILE:
#         if not LOCAL_FILE_PATH or not os.path.exists(LOCAL_FILE_PATH):
#             raise FileNotFoundError(f"❌ Local file not found: {LOCAL_FILE_PATH}")

#         logger.info(f"📂 Using LOCAL file: {LOCAL_FILE_PATH}")

#         local_path = LOCAL_FILE_PATH.strip()  # remove accidental spaces
#         filename = os.path.basename(local_path)

#     else:
#         with SFTPClient(settings) as sftp:
#             local_path, filename = sftp.download_latest()

#             if not local_path:
#                 logger.warning("No Excel file to process")
#                 return None, None, None

#             # Delete from SFTP (only in SFTP mode)
#             if settings.SFTP_DELETE_AFTER_INGEST:
#                 sftp.delete_file(filename)

#     # =========================
#     # COMMON FLOW (IMPORTANT)
#     # =========================

#     file_size = os.path.getsize(local_path)

#     import_id = db.save_excel_metadata({
#         "filename": filename,
#         "sftp_path": None if USE_LOCAL_FILE else filename,
#         "file_size_bytes": file_size,
#         "job_run_id": job_run_id,
#         "local_path": local_path,
#         "status": "downloaded",
#     })

#     # Parse Excel
#     shipment_ids, raw_rows = parse_excel(local_path)

#     # Clean + transform rows
#     def _clean_row(row):
#         return {
#             k: (None if (isinstance(v, float) and str(v) == "nan") else v)
#             for k, v in row.items()
#         }

#     db_rows = [
#         {
#             "shipment_id": row.get("Shipment ID"),
#             "raw_row_data": json.dumps(_clean_row(row), default=str),
#             "is_new": False,
#         }
#         for row in raw_rows
#         if row.get("Shipment ID")
#     ]

#     db.save_excel_rows(import_id, db_rows)

#     print("✅ All batches inserted successfully")
#     logger.info(f"Parsed {len(shipment_ids)} shipments from {filename}")

#     # Find new shipments
#     existing = db.get_existing_shipment_ids()
#     new_ids = [sid for sid in shipment_ids if sid not in existing]

#     logger.info(f"Found {len(new_ids)} new shipments out of {len(shipment_ids)}")

#     return shipment_ids, new_ids, import_id




# def run_download_only(db, settings):
#     """Download Excel from SFTP and store rows in DB. No CargoWise sync."""
#     job_run_id = db.create_job_run("excel_download")
#     try:
#         shipment_ids, new_ids, import_id = _download_and_store(db, settings, job_run_id)
#         if shipment_ids is None:
#             db.complete_job_run(job_run_id, 0, 0)
#             return job_run_id

#         logger.info(f"Download complete: {len(shipment_ids)} total, {len(new_ids)} new")
#         db.complete_job_run(job_run_id, len(shipment_ids), 0)
#         return job_run_id

#     except Exception as e:
#         logger.error(f"Excel download failed: {e}")
#         db.complete_job_run(job_run_id, 0, 0, error_summary=str(e))
#         raise


# def run(db, cw_client, notifier, settings):
#     """Excel ingest: SFTP download → parse → store → sync new shipments via CargoWise."""
#     job_run_id = db.create_job_run("excel_ingest")
#     try:
#         shipment_ids, new_ids, import_id = _download_and_store(db, settings, job_run_id)
#         if shipment_ids is None:
#             db.complete_job_run(job_run_id, 0, 0)
#             return job_run_id

#         if new_ids:
#             run_job("excel_ingest", new_ids, db, cw_client, notifier, settings , job_run_id)

#         db.complete_job_run(job_run_id, len(new_ids) if new_ids else 0, 0)
#         return job_run_id

#     except Exception as e:
#         logger.error(f"Excel ingest failed: {e}")
#         db.complete_job_run(job_run_id, 0, 0, error_summary=str(e))
#         raise




# # new code for tesing local xlxs ingestion

# def run_local_ingest(db, settings, file_path: str):
#     import os
#     import json
#     import math
#     from pipeline.excel import parse_excel

#     print(f"🚀 Starting LOCAL ingest: {file_path}")

#     if not os.path.exists(file_path):
#         raise FileNotFoundError(f"File not found: {file_path}")

#     job_run_id = db.create_job_run("local_excel_ingest")

#     file_size = os.path.getsize(file_path)
#     filename = os.path.basename(file_path)

#     import_id = db.save_excel_metadata({
#         "filename": filename,
#         "sftp_path": None,
#         "file_size_bytes": file_size,
#         "job_run_id": job_run_id,
#         "local_path": file_path,
#         "status": "completed",
#     })

#     shipment_ids, raw_rows = parse_excel(file_path)

#     def _clean_row(row):
#         return {
#             k: (None if (isinstance(v, float) and math.isnan(v)) else v)
#             for k, v in row.items()
#         }

#     db_rows = [
#         {
#             "shipment_id": row.get("Shipment ID"),
#             "raw_row_data": json.dumps(_clean_row(row), default=str),
#             "is_new": False,
#         }
#         for row in raw_rows
#         if row.get("Shipment ID")
#     ]

#     db.save_excel_rows(import_id, db_rows)

#     print(f"✅ Inserted {len(db_rows)} rows")

#     return job_run_id



# Working code without Job Opened prior to 1 Jan 2026 logic

# import os
# import json
# import math
# import logging
# from pipeline.sftp import SFTPClient
# from pipeline.excel import parse_excel
# from pipeline.jobs.processing import run_job

# logger = logging.getLogger("pipeline.jobs.excel_ingest")


# def _clean_row(row):
#     """Replace NaN/NaT with None for valid JSON serialization."""
#     return {k: (None if (isinstance(v, float) and math.isnan(v)) else v)
#             for k, v in row.items()}


# def _download_and_store(db, settings, job_run_id):
#     """Download Excel from SFTP, parse, store metadata + rows in DB.

#     Returns (shipment_ids, new_ids, import_id) or (None, None, None) if no file.
#     """
#     with SFTPClient(settings) as sftp:
#         local_path, filename = sftp.download_latest()
#         print("📥 Downloaded file:", filename, "at", local_path)
#         if not local_path:
#             logger.warning("No Excel file to process")
#             return None, None, None

#         # Store metadata
#         print("💾 Saving Excel metadata to DB...")
#         file_size = os.path.getsize(local_path)
#         import_id = db.save_excel_metadata({
#             "filename": filename,
#             "sftp_path": filename,
#             "file_size_bytes": file_size,
#             "job_run_id": job_run_id,
#             "local_path": local_path,
#             "status": "downloaded",
#         })
#         print("✅ Metadata saved, import_id:", import_id)
#         # Parse Excel
#         shipment_ids, raw_rows = parse_excel(local_path)
#         print(f"📊 Parsed {len(shipment_ids)} shipments")

#         # Transform rows for DB storage
#         db_rows = [
#             {
#                 "shipment_id": row.get("Shipment ID"),
#                 "raw_row_data": json.dumps(_clean_row(row), default=str),
#                 "is_new": False,
#             }
#             for row in raw_rows
#             if row.get("Shipment ID")
#         ]
#         print(f"🚀 About to insert {len(db_rows)} rows into DB...")
#         db.save_excel_rows(import_id, db_rows)
#         logger.info(f"Parsed {len(shipment_ids)} shipments from {filename}")
#         print("✅ Rows inserted successfully")

#         # Delete from SFTP
#         if settings.SFTP_DELETE_AFTER_INGEST:
#             sftp.delete_file(filename)

#         # Find new shipments
#         existing = db.get_existing_shipment_ids()
#         new_ids = [sid for sid in shipment_ids if sid not in existing]
#         logger.info(f"Found {len(new_ids)} new shipments out of {len(shipment_ids)}")

#         return shipment_ids, new_ids, import_id



# # def _download_and_store(db, settings, job_run_id):
# #     """
# #     Download Excel from SFTP OR use local file, parse, store metadata + rows in DB.

# #     Returns (shipment_ids, new_ids, import_id) or (None, None, None) if no file.
# #     """

# #     import os
# #     import json

# #     # ✅ TOGGLE (set this for local testing)
# #     USE_LOCAL_FILE = True
# #     LOCAL_FILE_PATH = "/Users/ashishsrivastava/Downloads/vin_world_shipment_dashboard/VWVIKPROGRR.xlsx"

# #     # =========================
# #     # FILE SOURCE
# #     # =========================
# #     if USE_LOCAL_FILE:
# #         if not LOCAL_FILE_PATH or not os.path.exists(LOCAL_FILE_PATH):
# #             raise FileNotFoundError(f"❌ Local file not found: {LOCAL_FILE_PATH}")

# #         logger.info(f"📂 Using LOCAL file: {LOCAL_FILE_PATH}")

# #         local_path = LOCAL_FILE_PATH.strip()  # remove accidental spaces
# #         filename = os.path.basename(local_path)

# #     else:
# #         with SFTPClient(settings) as sftp:
# #             local_path, filename = sftp.download_latest()

# #             if not local_path:
# #                 logger.warning("No Excel file to process")
# #                 return None, None, None

# #             # Delete from SFTP (only in SFTP mode)
# #             if settings.SFTP_DELETE_AFTER_INGEST:
# #                 sftp.delete_file(filename)

# #     # =========================
# #     # COMMON FLOW (IMPORTANT)
# #     # =========================

# #     file_size = os.path.getsize(local_path)

# #     import_id = db.save_excel_metadata({
# #         "filename": filename,
# #         "sftp_path": None if USE_LOCAL_FILE else filename,
# #         "file_size_bytes": file_size,
# #         "job_run_id": job_run_id,
# #         "local_path": local_path,
# #         "status": "downloaded",
# #     })

# #     # Parse Excel
# #     shipment_ids, raw_rows = parse_excel(local_path)

# #     # Clean + transform rows
# #     def _clean_row(row):
# #         return {
# #             k: (None if (isinstance(v, float) and str(v) == "nan") else v)
# #             for k, v in row.items()
# #         }

# #     db_rows = [
# #         {
# #             "shipment_id": row.get("Shipment ID"),
# #             "raw_row_data": json.dumps(_clean_row(row), default=str),
# #             "is_new": False,
# #         }
# #         for row in raw_rows
# #         if row.get("Shipment ID")
# #     ]

# #     db.save_excel_rows(import_id, db_rows)

# #     print("✅ All batches inserted successfully")
# #     logger.info(f"Parsed {len(shipment_ids)} shipments from {filename}")

# #     # Find new shipments
# #     existing = db.get_existing_shipment_ids()
# #     new_ids = [sid for sid in shipment_ids if sid not in existing]

# #     logger.info(f"Found {len(new_ids)} new shipments out of {len(shipment_ids)}")

# #     return shipment_ids, new_ids, import_id




# def run_download_only(db, settings):
#     """Download Excel from SFTP and store rows in DB. No CargoWise sync."""
#     job_run_id = db.create_job_run("excel_download")
#     try:
#         shipment_ids, new_ids, import_id = _download_and_store(db, settings, job_run_id)
#         if shipment_ids is None:
#             db.complete_job_run(job_run_id, 0, 0)
#             return job_run_id

#         logger.info(f"Download complete: {len(shipment_ids)} total, {len(new_ids)} new")
#         db.complete_job_run(job_run_id, len(shipment_ids), 0)
#         return job_run_id

#     except Exception as e:
#         logger.error(f"Excel download failed: {e}")
#         db.complete_job_run(job_run_id, 0, 0, error_summary=str(e))
#         raise


# def run(db, cw_client, notifier, settings):
#     """Excel ingest: SFTP download → parse → store → sync new shipments via CargoWise."""
#     job_run_id = db.create_job_run("excel_ingest")
#     try:
#         shipment_ids, new_ids, import_id = _download_and_store(db, settings, job_run_id)
#         if shipment_ids is None:
#             db.complete_job_run(job_run_id, 0, 0)
#             return job_run_id

#         if new_ids:
#             run_job("excel_ingest", new_ids, db, cw_client, notifier, settings , job_run_id)

#         db.complete_job_run(job_run_id, len(new_ids) if new_ids else 0, 0)
#         return job_run_id

#     except Exception as e:
#         logger.error(f"Excel ingest failed: {e}")
#         db.complete_job_run(job_run_id, 0, 0, error_summary=str(e))
#         raise




# # new code for tesing local xlxs ingestion

# def run_local_ingest(db, settings, file_path: str):
#     import os
#     import json
#     import math
#     from pipeline.excel import parse_excel

#     print(f"🚀 Starting LOCAL ingest: {file_path}")

#     if not os.path.exists(file_path):
#         raise FileNotFoundError(f"File not found: {file_path}")

#     job_run_id = db.create_job_run("local_excel_ingest")

#     file_size = os.path.getsize(file_path)
#     filename = os.path.basename(file_path)

#     import_id = db.save_excel_metadata({
#         "filename": filename,
#         "sftp_path": None,
#         "file_size_bytes": file_size,
#         "job_run_id": job_run_id,
#         "local_path": file_path,
#         "status": "completed",
#     })

#     shipment_ids, raw_rows = parse_excel(file_path)

#     def _clean_row(row):
#         return {
#             k: (None if (isinstance(v, float) and math.isnan(v)) else v)
#             for k, v in row.items()
#         }

#     db_rows = [
#         {
#             "shipment_id": row.get("Shipment ID"),
#             "raw_row_data": json.dumps(_clean_row(row), default=str),
#             "is_new": False,
#         }
#         for row in raw_rows
#         if row.get("Shipment ID")
#     ]

#     db.save_excel_rows(import_id, db_rows)

#     print(f"✅ Inserted {len(db_rows)} rows")

#     return job_run_id

# Working code without Job Opened prior to 1 Jan 2026 logic



import os
import json
import math
import logging
from datetime import datetime
from dateutil import parser

from pipeline.sftp import SFTPClient
from pipeline.excel import parse_excel
from pipeline.jobs.processing import run_job

logger = logging.getLogger("pipeline.jobs.excel_ingest")

FILTER_DATE = datetime(2026, 1, 1)


def _clean_row(row):
    return {
        k: (None if (isinstance(v, float) and math.isnan(v)) else v)
        for k, v in row.items()
    }


def _parse_job_opened(job_opened):
    """Robust parser for ALL Excel date formats"""

    if not job_opened:
        return None

    # If already datetime
    if isinstance(job_opened, datetime):
        return job_opened

    try:
        # 🔥 MAGIC LINE (handles ALL formats)
        return parser.parse(str(job_opened), dayfirst=True)

    except Exception as e:
        print(f"⚠️ Date parse failed: {job_opened}")
        return None

def _is_valid_job_opened(job_opened):
    parsed_date = _parse_job_opened(job_opened)

    if not parsed_date:
        return False

    return parsed_date >= FILTER_DATE


# def _download_and_store(db, settings, job_run_id):
#     with SFTPClient(settings) as sftp:
#         local_path, filename = sftp.download_latest()
#         print("📥 Downloaded file:", filename, "at", local_path)

#         if not local_path:
#             logger.warning("No Excel file to process")
#             return None, None, None

#         file_size = os.path.getsize(local_path)

#         import_id = db.save_excel_metadata({
#             "filename": filename,
#             "sftp_path": filename,
#             "file_size_bytes": file_size,
#             "job_run_id": job_run_id,
#             "local_path": local_path,
#             "status": "downloaded",
#         })

#         shipment_ids, raw_rows = parse_excel(local_path)
#         print(f"📊 Parsed {len(raw_rows)} total rows")

#         db_rows = []
#         filtered_shipment_ids = []

#         for row in raw_rows:
#             shipment_id = row.get("Shipment ID")
#             job_opened = row.get("Job Opened")

#             if not shipment_id:
#                 continue

#             if not _is_valid_job_opened(job_opened):
#                 continue

#             db_rows.append({
#                 "shipment_id": shipment_id,
#                 "raw_row_data": json.dumps(_clean_row(row), default=str),
#                 "is_new": False,
#             })

#             filtered_shipment_ids.append(shipment_id)

#         print(f"✅ Rows after date filter: {len(db_rows)}")

#         db.save_excel_rows(import_id, db_rows)

#         if settings.SFTP_DELETE_AFTER_INGEST:
#             sftp.delete_file(filename)

#         existing = db.get_existing_shipment_ids()
#         new_ids = [sid for sid in filtered_shipment_ids if sid not in existing]

#         logger.info(f"Found {len(new_ids)} new shipments out of {len(filtered_shipment_ids)}")

#         return filtered_shipment_ids, new_ids, import_id


# =========================
# ✅ UPDATED LOCAL VERSION (FOR PROD SWITCH)
# =========================

def _download_and_store(db, settings, job_run_id):
    USE_LOCAL_FILE = True
    LOCAL_FILE_PATH = "/Users/ashishsrivastava/Documents/lavinstar_project/vin_world_shipment_dashboard/excel_files_latest/test.xlsx"

    if USE_LOCAL_FILE:
        if not os.path.exists(LOCAL_FILE_PATH):
            raise FileNotFoundError(f"❌ Local file not found: {LOCAL_FILE_PATH}")

        local_path = LOCAL_FILE_PATH
        filename = os.path.basename(local_path)
    
    else:
        with SFTPClient(settings) as sftp:
            local_path, filename = sftp.download_latest()

            if not local_path:
                return None, None, None

            if settings.SFTP_DELETE_AFTER_INGEST:
                sftp.delete_file(filename)

    file_size = os.path.getsize(local_path)

    import_id = db.save_excel_metadata({
        "filename": filename,
        "sftp_path": None,
        "file_size_bytes": file_size,
        "job_run_id": job_run_id,
        "local_path": local_path,
        "status": "downloaded",
    })

    shipment_ids, raw_rows = parse_excel(local_path)

    db_rows = []
    filtered_shipment_ids = []

    for row in raw_rows:
        shipment_id = row.get("Shipment ID")
        job_opened = row.get("Job Opened")

        if not shipment_id:
            continue

        if not _is_valid_job_opened(job_opened):
            continue

        db_rows.append({
            "shipment_id": shipment_id,
            "raw_row_data": json.dumps(_clean_row(row), default=str),
            "is_new": False,
        })

        filtered_shipment_ids.append(shipment_id)

    db.save_excel_rows(import_id, db_rows)

    existing = db.get_existing_shipment_ids()
    new_ids = [sid for sid in filtered_shipment_ids if sid not in existing]

    return filtered_shipment_ids, new_ids, import_id



def run_download_and_ingest(db, cw_client, notifier, settings):
    """Single function for cron: download once → parse → sync → then delete from SFTP."""
    job_run_id = db.create_job_run("download_and_ingest")

    # ✅ TOGGLE for local testing
    USE_LOCAL_FILE = True
    LOCAL_FILE_PATH = "/Users/ashishsrivastava/Documents/lavinstar_project/vin_world_shipment_dashboard/excel_files_latest/test.xlsx"

    try:
        sftp_context = None
        filename = None

        if USE_LOCAL_FILE:
            if not os.path.exists(LOCAL_FILE_PATH):
                raise FileNotFoundError(f"❌ Local file not found: {LOCAL_FILE_PATH}")
            local_path = LOCAL_FILE_PATH
            filename = os.path.basename(local_path)
            print(f"📂 Using LOCAL file: {filename}")
        else:
            sftp_context = SFTPClient(settings)
            sftp_context.connect()
            local_path, filename = sftp_context.download_latest()
            print(f"📥 Downloaded file: {filename} at {local_path}")

            if not local_path:
                print("⚠️ No file found on SFTP")
                sftp_context.close()
                db.complete_job_run(job_run_id, 0, 0)
                return job_run_id

        # Parse + store rows
        file_size = os.path.getsize(local_path)
        import_id = db.save_excel_metadata({
            "filename": filename,
            "sftp_path": None if USE_LOCAL_FILE else filename,
            "file_size_bytes": file_size,
            "job_run_id": job_run_id,
            "local_path": local_path,
            "status": "downloaded",
        })

        shipment_ids, raw_rows = parse_excel(local_path)
        print(f"📊 Parsed {len(raw_rows)} total rows")

        db_rows = []
        filtered_shipment_ids = []

        for row in raw_rows:
            shipment_id = row.get("Shipment ID")
            job_opened = row.get("Job Opened")

            if not shipment_id:
                continue
            if not _is_valid_job_opened(job_opened):
                continue

            db_rows.append({
                "shipment_id": shipment_id,
                "raw_row_data": json.dumps(_clean_row(row), default=str),
                "is_new": False,
            })
            filtered_shipment_ids.append(shipment_id)

        print(f"✅ Rows after date filter: {len(db_rows)}")
        db.save_excel_rows(import_id, db_rows)

        # Find new shipments
        existing = db.get_existing_shipment_ids()
        new_ids = [sid for sid in filtered_shipment_ids if sid not in existing]
        logger.info(f"Found {len(new_ids)} new out of {len(filtered_shipment_ids)}")

        print(f"📋 Total shipments in Excel: {len(filtered_shipment_ids)}")
        print(f"📋 Already existing in DB: {len(filtered_shipment_ids) - len(new_ids)}")
        print(f"📋 New shipments: {len(new_ids)}")

        if new_ids:
            print(f"🚀 Syncing {len(new_ids)} new shipments via CargoWise...")
            run_job("excel_ingest", new_ids, db, cw_client, notifier, settings, job_run_id)
        else:
            print("ℹ️ No new shipments to sync — all already exist in DB")

        # Delete from SFTP AFTER successful ingest (skip for local)
        if not USE_LOCAL_FILE and settings.SFTP_DELETE_AFTER_INGEST and sftp_context:
            sftp_context.delete_file(filename)

        if sftp_context:
            sftp_context.close()

        db.complete_job_run(job_run_id, len(new_ids) if new_ids else 0, 0)
        print(f"✅ Done — {len(filtered_shipment_ids)} parsed, {len(new_ids)} new, {len(filtered_shipment_ids) - len(new_ids)} skipped")
        return job_run_id

    except Exception as e:
        logger.error(f"Download + ingest failed: {e}")
        db.complete_job_run(job_run_id, 0, 0, error_summary=str(e))
        if sftp_context:
            sftp_context.close()
        raise

def run_download_only(db, settings):
    job_run_id = db.create_job_run("excel_download")

    try:
        shipment_ids, new_ids, import_id = _download_and_store(db, settings, job_run_id)

        if shipment_ids is None:
            db.complete_job_run(job_run_id, 0, 0)
            return job_run_id

        db.complete_job_run(job_run_id, len(shipment_ids), 0)
        return job_run_id

    except Exception as e:
        logger.error(f"Excel download failed: {e}")
        db.complete_job_run(job_run_id, 0, 0, error_summary=str(e))
        raise


def run(db, cw_client, notifier, settings):
    job_run_id = db.create_job_run("excel_ingest")

    try:
        shipment_ids, new_ids, import_id = _download_and_store(db, settings, job_run_id)

        if shipment_ids is None:
            db.complete_job_run(job_run_id, 0, 0)
            return job_run_id

        if new_ids:
            run_job("excel_ingest", new_ids, db, cw_client, notifier, settings, job_run_id)

        db.complete_job_run(job_run_id, len(new_ids), 0)

        return job_run_id

    except Exception as e:
        logger.error(f"Excel ingest failed: {e}")
        db.complete_job_run(job_run_id, 0, 0, error_summary=str(e))
        raise


def run_local_ingest(db, settings, file_path: str):
    print(f"🚀 Starting LOCAL ingest: {file_path}")

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    job_run_id = db.create_job_run("local_excel_ingest")

    file_size = os.path.getsize(file_path)
    filename = os.path.basename(file_path)

    import_id = db.save_excel_metadata({
        "filename": filename,
        "sftp_path": None,
        "file_size_bytes": file_size,
        "job_run_id": job_run_id,
        "local_path": file_path,
        "status": "completed",
    })

    shipment_ids, raw_rows = parse_excel(file_path)

    db_rows = []
    filtered_shipment_ids = []

    for row in raw_rows:
        shipment_id = row.get("Shipment ID")
        job_opened = row.get("Job Opened")

        if not shipment_id:
            continue

        if not _is_valid_job_opened(job_opened):
            continue

        db_rows.append({
            "shipment_id": shipment_id,
            "raw_row_data": json.dumps(_clean_row(row), default=str),
            "is_new": False,
        })

        filtered_shipment_ids.append(shipment_id)

    db.save_excel_rows(import_id, db_rows)

    print(f"✅ Inserted {len(db_rows)} filtered rows")

    return job_run_id