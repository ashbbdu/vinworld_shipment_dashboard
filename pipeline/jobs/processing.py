

"""
Shared processing logic — the core engine for all pipeline jobs.
"""

import json
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.exceptions import Timeout, ConnectionError as ReqConnectionError

from pipeline.parser import parse_shipment
from pipeline.milestones import (
    build_milestones,
    build_milestones_reformed,
    derive_status,
    get_last_completed_event,
    extract_milestones_from_customized_fields,
)
from pipeline.db import apply_eta_snapshot, apply_actual_snapshot

logger = logging.getLogger("pipeline.jobs.processing")


# ---------------------------------------------------------------------------
# PROCESS SINGLE SHIPMENT
# ---------------------------------------------------------------------------

def process_shipment(shipment_id, job_run_id, db, cw_client, settings, retry_count=0):
    try:
        print(f"\n🔄 [{shipment_id}] START processing")

        db.update_tracking(shipment_id, job_run_id, "in_progress")

        # ---------------- FETCH ----------------
        print(f"📡 [{shipment_id}] Fetching shipment...")
        shipment_dict = cw_client.fetch_shipment(shipment_id)

        print(f"📄 [{shipment_id}] Fetching documents...")
        documents = cw_client.fetch_documents(shipment_id)

        print(f"🧠 [{shipment_id}] Parsing shipment...")
        record = parse_shipment(shipment_id, shipment_dict, documents)
        
        excel_row = db.get_excel_row(shipment_id) 
        # print(excel_row , "excel row ashish")

        job_opened_date = None
        if excel_row:
            try:
                row_data = json.loads(excel_row.get("raw_row_data", "{}"))
                job_opened_date = row_data.get("Job Opened")
            except Exception:
                job_opened_date = None

        print(f"🧪 [{shipment_id}] Job Opened from Excel: {job_opened_date}")

        # job_opened_date = record.get("job_opened") or record.get("Job Opened")
           

        # ---------------- ETA / ETD ----------------
        print(f"🕒 [{shipment_id}] Processing ETA/ETD...")
        eta_custom = record.pop("eta_custom", None)
        etd_custom = record.pop("etd_custom", None)
        actual_arrival_raw = record.pop("actual_arrival_raw", None)
        actual_departure_raw = record.pop("actual_departure_raw", None)

        existing_eta = db.fetch_eta_etd(shipment_id)

        if existing_eta:
            print(f"🔁 [{shipment_id}] Existing ETA found, applying snapshot logic")

            eta_result = apply_eta_snapshot(
                {"currentETA": existing_eta.get("currentETA"), "updatedETA": existing_eta.get("updatedETA")},
                eta_custom,
            )
            etd_result = apply_eta_snapshot(
                {"currentETA": existing_eta.get("currentETD"), "updatedETA": existing_eta.get("updatedETD")},
                etd_custom,
            )

            record["currentETA"] = eta_result["currentETA"]
            record["updatedETA"] = eta_result["updatedETA"]
            record["currentETD"] = etd_result["currentETA"]
            record["updatedETD"] = etd_result["updatedETA"]
        else:
            print(f"🆕 [{shipment_id}] First time ETA/ETD insert")
            record["currentETA"] = eta_custom
            record["updatedETA"] = eta_custom
            record["currentETD"] = etd_custom
            record["updatedETD"] = etd_custom

        # ---------------- ACTUALS ----------------
        print(f"🚚 [{shipment_id}] Processing actual arrival/departure...")
        existing_actuals = db.fetch_actuals(shipment_id)

        if existing_actuals:
            arr = apply_actual_snapshot(
                {
                    "currentActualArrival": existing_actuals.get("currentActualArrival"),
                    "updatedActualArrival": existing_actuals.get("updatedActualArrival"),
                },
                actual_arrival_raw,
                "Arrival",
            )
            dep = apply_actual_snapshot(
                {
                    "currentActualDeparture": existing_actuals.get("currentActualDeparture"),
                    "updatedActualDeparture": existing_actuals.get("updatedActualDeparture"),
                },
                actual_departure_raw,
                "Departure",
            )
            record.update(arr)
            record.update(dep)
        else:
            print(f"🆕 [{shipment_id}] First time actuals insert")
            record["currentActualArrival"] = actual_arrival_raw
            record["updatedActualArrival"] = actual_arrival_raw
            record["currentActualDeparture"] = actual_departure_raw
            record["updatedActualDeparture"] = actual_departure_raw

        # ---------------- MILESTONES ----------------
        print(f"📍 [{shipment_id}] Building milestones...")

        transport_mode = (record.get("JS_TransportMode") or "").upper()
        service_level = None

        sub = shipment_dict.get("SubShipmentCollection", {}).get("SubShipment", {})
        if isinstance(sub, list):
            sub = sub[0] if sub else {}

        customized_fields = []
        for level in [shipment_dict, sub]:
            cf = (level or {}).get("CustomizedFieldCollection", {}).get("CustomizedField")
            if cf:
                if isinstance(cf, list):
                    customized_fields.extend(cf)
                elif isinstance(cf, dict):
                    customized_fields.append(cf)

        print(f"📊 [{shipment_id}] Found {len(customized_fields)} customized fields")

        raw_milestones = extract_milestones_from_customized_fields(customized_fields, transport_mode)
        record["milestones"] = json.dumps(raw_milestones)

        actuals = {
            m["customField"]: m["actualDate"]
            for m in raw_milestones
            if m.get("customField") and m.get("actualDate")
        }

        dates = {
            "currentETA": record.get("currentETA"),
            "updatedETA": record.get("updatedETA"),
            "currentETD": record.get("currentETD"),
            "updatedETD": record.get("updatedETD"),
            "currentActualArrival": record.get("currentActualArrival"),
            "updatedActualArrival": record.get("updatedActualArrival"),
            "currentActualDeparture": record.get("currentActualDeparture"),
            "updatedActualDeparture": record.get("updatedActualDeparture"),
        }

        milestones_new = build_milestones(transport_mode, service_level, actuals, dates)
        milestones_reformed = build_milestones_reformed(transport_mode, service_level, customized_fields , job_opened_date)

        print(f"📈 [{shipment_id}] milestones_new: {len(milestones_new)}, milestones_reformed: {len(milestones_reformed)}")

        record["milestones_new"] = json.dumps(milestones_new, default=str)
        record["milestones_reformed"] = json.dumps(milestones_reformed, default=str)

        # ---------------- STATUS ----------------
        print(f"📌 [{shipment_id}] Deriving status...")
        primary_status, derived_statuses = derive_status(
            milestones_reformed, transport_mode, service_level
        )

        record["primary_status"] = primary_status
        record["derived_statuses"] = json.dumps(derived_statuses)

        # # ---------------- LAST COMPLETED ----------------
        # print(f"🏁 [{shipment_id}] Getting last completed milestone...")
        # delay, actual_date, event = get_last_completed_event(
        #     milestones_reformed, transport_mode, service_level
        # )

        # record["latest_completed_delay"] = delay
        # record["latest_completed_actualDate"] = actual_date
        # record["latest_completed_event"] = event

        # # ---------------- UPSERT ----------------
        
        # ---------------- LAST COMPLETED ----------------
        print(f"🏁 [{shipment_id}] Getting last completed milestone...")
        delay, actual_date, event = get_last_completed_event(
            milestones_reformed, transport_mode, service_level
        )

        record["latest_completed_delay"] = delay
        record["latest_completed_actualDate"] = actual_date
        record["latest_completed_event"] = event

        # # ---------------- DEP DATE / ARRIVAL DATE from milestones_reformed ----------------
        # def _get_planned_date(field):
        #     for m in milestones_reformed:
        #         if m.get("customField") == field:
        #             return m.get("plannedDate")
        #     return None

        # record["dep_date"] = _get_planned_date("ATD Custom")
        # record["arrival_date"] = _get_planned_date("ATA Custom")
        
        
        # # ---------------- DELAY ARRIVAL / DEPARTURE ----------------
        # def _find_delay(ev):
        #     for m in milestones_reformed:
        #         if (m.get("eventStatus") or "").lower() == ev.lower():
        #             return m.get("delay")
        #     return None

        # record["delay_arrival"] = _find_delay("Arrived") or _find_delay("Arrival at final destination")
        # record["delay_departure"] = _find_delay("Sailed") or _find_delay("Departed")
        
        # # ---------------- DEP DATE / ARRIVAL DATE from milestones_reformed ----------------
        # def _get_milestone(field):
        #     for m in milestones_reformed:
        #         if m.get("customField") == field:
        #             return m
        #     return {}

        # atd = _get_milestone("ATD Custom")
        # ata = _get_milestone("ATA Custom")

        # # Always store planned (never overwritten)
        # record["planned_departure"] = atd.get("plannedDate")
        # record["planned_arrival"] = ata.get("plannedDate")

        # # Departure: actual wins over planned
        # if atd.get("actualDate"):
        #     record["dep_date"] = atd["actualDate"]
        #     record["dep_is_actual"] = True
        #     record["delay_departure"] = atd.get("delay")
        # else:
        #     record["dep_date"] = atd.get("plannedDate")
        #     record["dep_is_actual"] = False
        #     record["delay_departure"] = None

        # # Arrival: actual wins over planned
        # if ata.get("actualDate"):
        #     record["arrival_date"] = ata["actualDate"]
        #     record["arrival_is_actual"] = True
        #     record["delay_arrival"] = ata.get("delay")
        # else:
        #     record["arrival_date"] = ata.get("plannedDate")
        #     record["arrival_is_actual"] = False
        #     record["delay_arrival"] = None

        # # ---------------- UPSERT ----------------
        
        
        # ---------------- DEP DATE / ARRIVAL DATE from milestones_reformed ----------------
        def _get_milestone(field):
            for m in milestones_reformed:
                if m.get("customField") == field:
                    return m
            return {}

        atd = _get_milestone("ATD Custom")
        ata = _get_milestone("ATA Custom")

        # dep_date / arrival_date stay as planned (UNCHANGED)
        record["dep_date"] = atd.get("plannedDate")
        record["arrival_date"] = ata.get("plannedDate")

        # Permanent planned backup
        record["planned_departure"] = atd.get("plannedDate")
        record["planned_arrival"] = ata.get("plannedDate")

        # Display columns: actual wins over planned
        if atd.get("actualDate"):
            record["display_departure"] = atd["actualDate"]
            record["dep_is_actual"] = True
            record["delay_departure"] = atd.get("delay")
        else:
            record["display_departure"] = atd.get("plannedDate")
            record["dep_is_actual"] = False
            record["delay_departure"] = None

        if ata.get("actualDate"):
            record["display_arrival"] = ata["actualDate"]
            record["arrival_is_actual"] = True
            record["delay_arrival"] = ata.get("delay")
        else:
            record["display_arrival"] = ata.get("plannedDate")
            record["arrival_is_actual"] = False
            record["delay_arrival"] = None
        
        print(f"💾 [{shipment_id}] Saving to DB...")
        db.upsert_shipment(record)

        db.update_tracking(shipment_id, job_run_id, "completed")

        print(f"✅ [{shipment_id}] DONE\n")

        return {"status": "completed", "shipment_id": shipment_id}

    except (Timeout, ReqConnectionError) as e:
        print(f"⚠️ [{shipment_id}] Retryable error: {e}")
        if retry_count < settings.SHIPMENT_RETRY_MAX:
            return {
                "status": "retry",
                "shipment_id": shipment_id,
                "retry_count": retry_count + 1,
                "error": str(e),
            }

        db.update_tracking(shipment_id, job_run_id, "failed", error=str(e))
        return {"status": "failed", "shipment_id": shipment_id, "error": str(e)}

    except Exception as e:
        error_msg = f"{e}\n{traceback.format_exc()}"
        print(f"❌ [{shipment_id}] Exception: {e}")
        db.update_tracking(shipment_id, job_run_id, "failed", error=error_msg)
        return {"status": "failed", "shipment_id": shipment_id, "error": str(e)}


# ---------------------------------------------------------------------------
# RUN JOB
# ---------------------------------------------------------------------------

def run_job(job_type, shipment_ids, db, cw_client, notifier, settings, job_run_id=None, parent_job_run_id=None):

    print(f"\n🚀 run_job started with {len(shipment_ids)} shipments")

    if job_run_id is None:
        print("🆕 Creating new job_run...")
        job_run_id = db.create_job_run(job_type)

    if parent_job_run_id:
        print("🔍 Filtering already processed shipments...")
        shipment_ids = [sid for sid in shipment_ids if not db.was_processed_in_cycle(sid, parent_job_run_id)]

    if not shipment_ids:
        print("⚠️ No shipments to process")
        db.complete_job_run(job_run_id, 0, 0)
        return job_run_id

    print(f"📥 Inserting tracking for {len(shipment_ids)} shipments")
    db.bulk_track_shipments(shipment_ids, job_run_id, job_type)

    completed = 0
    failed = 0
    retry_queue = []

    print(f"⚙️ Starting ThreadPool with {settings.MAX_PARALLEL_REQUESTS} workers")

    with ThreadPoolExecutor(max_workers=settings.MAX_PARALLEL_REQUESTS) as pool:
        futures = {
            pool.submit(process_shipment, sid, job_run_id, db, cw_client, settings): sid
            for sid in shipment_ids
        }

        for fut in as_completed(futures):
            result = fut.result()

            if result["status"] == "completed":
                completed += 1
                if completed <= 5 or completed % 10 == 0:
                    print(f"✅ Progress: {completed}/{len(shipment_ids)}")
            elif result["status"] == "retry":
                retry_queue.append(result)
            else:
                failed += 1
                print(f"❌ Failed: {result['shipment_id']}")

    print(f"🔁 Retrying {len(retry_queue)} shipments...")

    for item in retry_queue:
        result = process_shipment(
            item["shipment_id"],
            job_run_id,
            db,
            cw_client,
            settings,
            retry_count=item["retry_count"],
        )
        if result["status"] == "completed":
            completed += 1
        else:
            failed += 1

    db.complete_job_run(job_run_id, completed, failed)

    print(f"🏁 Job finished → ✅ completed : {completed} | ❌ failed : {failed}\n")

    return job_run_id