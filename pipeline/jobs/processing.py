# # """
# # Shared processing logic — the core engine for all pipeline jobs.

# # process_shipment() handles one shipment end-to-end:
# #   CW fetch -> parse -> ETA/ETD snapshot -> milestones -> delays -> status -> upsert

# # run_job() orchestrates parallel processing with circuit breaker and retry.
# # """

# # import json
# # import logging
# # import traceback
# # import threading
# # from concurrent.futures import ThreadPoolExecutor, as_completed
# # from datetime import datetime, timezone
# # from requests.exceptions import Timeout, ConnectionError as ReqConnectionError

# # from pipeline.parser import parse_shipment
# # from pipeline.milestones import (
# #     build_milestones,
# #     build_milestones_reformed,
# #     derive_status,
# #     get_last_completed_event,
# #     extract_milestones_from_customized_fields,
# #     extract_service_level_code,
# #     SEQUENCES,
# # )
# # from pipeline.db import apply_eta_snapshot, apply_actual_snapshot
# # from pipeline.helpers import dump_json

# # logger = logging.getLogger("pipeline.jobs.processing")


# # def process_shipment(shipment_id, job_run_id, db, cw_client, settings, retry_count=0):
# #     """Process a single shipment: fetch from CW, parse, build milestones, upsert."""
# #     try:
# #         # Mark in_progress
# #         db.update_tracking(shipment_id, job_run_id, "in_progress")

# #         # 1. Fetch from CargoWise
# #         shipment_dict = cw_client.fetch_shipment(shipment_id)
# #         documents = cw_client.fetch_documents(shipment_id)

# #         # 2. Parse into flat record
# #         record = parse_shipment(shipment_id, shipment_dict, documents)

# #         # 3. Extract dates from parser output
# #         eta_custom = record.pop("eta_custom", None)
# #         etd_custom = record.pop("etd_custom", None)
# #         actual_arrival_raw = record.pop("actual_arrival_raw", None)
# #         actual_departure_raw = record.pop("actual_departure_raw", None)

# #         # 4. Apply ETA/ETD snapshot logic
# #         existing_eta = db.fetch_eta_etd(shipment_id)
# #         if existing_eta:
# #             eta_result = apply_eta_snapshot(
# #                 {"currentETA": existing_eta.get("currentETA"), "updatedETA": existing_eta.get("updatedETA")},
# #                 eta_custom,
# #             )
# #             etd_result = apply_eta_snapshot(
# #                 {"currentETA": existing_eta.get("currentETD"), "updatedETA": existing_eta.get("updatedETD")},
# #                 etd_custom,
# #             )
# #             record["currentETA"] = eta_result["currentETA"]
# #             record["updatedETA"] = eta_result["updatedETA"]
# #             record["currentETD"] = etd_result["currentETA"]
# #             record["updatedETD"] = etd_result["updatedETA"]
# #         else:
# #             # First insertion
# #             record["currentETA"] = eta_custom
# #             record["updatedETA"] = eta_custom
# #             record["currentETD"] = etd_custom
# #             record["updatedETD"] = etd_custom

# #         # 5. Apply Actual Arrival/Departure snapshot
# #         existing_actuals = db.fetch_actuals(shipment_id)
# #         if existing_actuals:
# #             arr = apply_actual_snapshot(
# #                 {
# #                     "currentActualArrival": existing_actuals.get("currentActualArrival"),
# #                     "updatedActualArrival": existing_actuals.get("updatedActualArrival"),
# #                 },
# #                 actual_arrival_raw,
# #                 "Arrival",
# #             )
# #             dep = apply_actual_snapshot(
# #                 {
# #                     "currentActualDeparture": existing_actuals.get("currentActualDeparture"),
# #                     "updatedActualDeparture": existing_actuals.get("updatedActualDeparture"),
# #                 },
# #                 actual_departure_raw,
# #                 "Departure",
# #             )
# #             record.update(arr)
# #             record.update(dep)
# #         else:
# #             record["currentActualArrival"] = actual_arrival_raw
# #             record["updatedActualArrival"] = actual_arrival_raw
# #             record["currentActualDeparture"] = actual_departure_raw
# #             record["updatedActualDeparture"] = actual_departure_raw

# #         # 6. Build milestones
# #         transport_mode = (record.get("JS_TransportMode") or "").upper()
# #         # Get service level from the shipment dict
# #         sub = shipment_dict.get("SubShipmentCollection", {}).get("SubShipment", {})
# #         if isinstance(sub, list):
# #             sub = sub[0] if sub else {}
# #         service_level = extract_service_level_code(shipment_dict, sub)

# #         # Get customized fields for milestones
# #         customized_fields = []
# #         for level in [shipment_dict, sub]:
# #             cf = (level or {}).get("CustomizedFieldCollection", {}).get("CustomizedField")
# #             if cf:
# #                 if isinstance(cf, list):
# #                     customized_fields.extend(cf)
# #                 elif isinstance(cf, dict):
# #                     customized_fields.append(cf)

# #         # Raw milestones
# #         raw_milestones = extract_milestones_from_customized_fields(customized_fields, transport_mode)
# #         record["milestones"] = json.dumps(raw_milestones)

# #         # Build actuals dict for milestone builder
# #         actuals = {}
# #         for m in raw_milestones:
# #             cf = m.get("customField")
# #             ad = m.get("actualDate")
# #             if cf and ad:
# #                 actuals[cf] = ad

# #         dates = {
# #             "currentETA": record.get("currentETA"),
# #             "updatedETA": record.get("updatedETA"),
# #             "currentETD": record.get("currentETD"),
# #             "updatedETD": record.get("updatedETD"),
# #             "currentActualArrival": record.get("currentActualArrival"),
# #             "updatedActualArrival": record.get("updatedActualArrival"),
# #             "currentActualDeparture": record.get("currentActualDeparture"),
# #             "updatedActualDeparture": record.get("updatedActualDeparture"),
# #         }

# #         milestones_new = build_milestones(transport_mode, service_level, actuals, dates)
# #         milestones_reformed = build_milestones_reformed(transport_mode, service_level, customized_fields)
# #         record["milestones_new"] = json.dumps(milestones_new, default=str)
# #         record["milestones_reformed"] = json.dumps(milestones_reformed, default=str)

# #         # 7. Derive status
# #         primary_status, derived_statuses = derive_status(milestones_reformed, transport_mode, service_level)
# #         record["primary_status"] = primary_status
# #         record["derived_statuses"] = json.dumps(derived_statuses)

# #         # 8. Get last completed event
# #         delay, actual_date, event = get_last_completed_event(milestones_reformed, transport_mode, service_level)
# #         record["latest_completed_delay"] = delay
# #         record["latest_completed_actualDate"] = actual_date
# #         record["latest_completed_event"] = event

# #         # 9. Extract delay values from reformed milestones
# #         def _find_delay(ev):
# #             for m in milestones_reformed:
# #                 if (m.get("eventStatus") or "").lower() == ev.lower():
# #                     return m.get("delay")
# #             return None

# #         record["delay_arrival"] = _find_delay("Arrived") or _find_delay("Arrival at final destination")
# #         record["delay_departure"] = _find_delay("Sailed") or _find_delay("Departed")
# #         record["delay_actual_arrival"] = record["delay_arrival"]
# #         record["delay_actual_departure"] = record["delay_departure"]

# #         # Set date aliases
# #         record["arrival_date"] = record.get("currentETA")
# #         record["dep_date"] = record.get("currentETD")
# #         record["vesselArrivedDate"] = record.get("currentActualArrival")

# #         # 10. Upsert
# #         db.upsert_shipment(record)
# #         db.update_tracking(shipment_id, job_run_id, "completed")
# #         return {"status": "completed", "shipment_id": shipment_id}

# #     except (Timeout, ReqConnectionError) as e:
# #         logger.warning(f"Transient error for {shipment_id}: {e}")
# #         if retry_count < settings.SHIPMENT_RETRY_MAX:
# #             return {
# #                 "status": "retry",
# #                 "shipment_id": shipment_id,
# #                 "retry_count": retry_count + 1,
# #                 "error": str(e),
# #             }
# #         logger.error(f"Max retries exceeded for {shipment_id}: {e}")
# #         db.update_tracking(shipment_id, job_run_id, "failed", error=str(e))
# #         return {"status": "failed", "shipment_id": shipment_id, "error": str(e)}

# #     except Exception as e:
# #         error_msg = f"{e}\n{traceback.format_exc()}"
# #         logger.error(f"Failed processing {shipment_id}: {e}")
# #         db.update_tracking(shipment_id, job_run_id, "failed", error=error_msg)
# #         return {"status": "failed", "shipment_id": shipment_id, "error": str(e)}


# # # def run_job(job_type, shipment_ids, db, cw_client, notifier, settings, parent_job_run_id=None):
# # # def run_job(job_type, shipment_ids, db, cw_client, notifier, settings, job_run_id, parent_job_run_id=None):
# # #     print(f"🚀 run_job started with {len(shipment_ids)} shipments")
# # #     """Orchestrate parallel processing of shipments with circuit breaker and retry."""
    
   
# # #     job_run_id = db.create_job_run(job_type)

# # #     # Filter duplicates if parent cycle provided
# # #     if parent_job_run_id:
# # #         shipment_ids = [sid for sid in shipment_ids if not db.was_processed_in_cycle(sid, parent_job_run_id)]

# # #     if not shipment_ids:
# # #         logger.info(f"[{job_type}] No shipments to process")
# # #         db.complete_job_run(job_run_id, 0, 0)
# # #         return job_run_id

# # #     # db.bulk_track_shipments(shipment_ids, job_run_id, job_type)
    
    
# # #     TRACK_BATCH_SIZE = 50   # ✅ your requirement

# # #     print(f"📊 Tracking {len(shipment_ids)} shipments in batches...")

# # #     for i in range(0, len(shipment_ids), TRACK_BATCH_SIZE):
# # #         batch = shipment_ids[i:i+TRACK_BATCH_SIZE]

# # #         print(f"📦 Tracking batch {i} → {i+len(batch)}")

# # #         db.bulk_track_shipments(batch, job_run_id, job_type)
        
    
# # #     logger.info(f"[{job_type}] Processing {len(shipment_ids)} shipments")


# # #     completed = 0
# # #     failed = 0
# # #     failed_details = []
# # #     consecutive_failures = 0
# # #     circuit_broken = False
# # #     retry_queue = []

# # #     # Process with ThreadPoolExecutor, feeding work incrementally so the
# # #     # circuit breaker can halt submission before all futures are in flight.
# # #     with ThreadPoolExecutor(max_workers=settings.MAX_PARALLEL_REQUESTS) as pool:
# # #         pending_futures = {}
# # #         sid_iter = iter(shipment_ids)

# # #         def _submit_next():
# # #             """Submit the next shipment from the iterator, if available."""
# # #             try:
# # #                 sid = next(sid_iter)
# # #                 fut = pool.submit(process_shipment, sid, job_run_id, db, cw_client, settings)
# # #                 pending_futures[fut] = sid
# # #                 return True
# # #             except StopIteration:
# # #                 return False

# # #         # Seed the pool up to max_workers
# # #         for _ in range(min(settings.MAX_PARALLEL_REQUESTS, len(shipment_ids))):
# # #             _submit_next()

# # #         while pending_futures:
# # #             # Wait for any single future to complete
# # #             done_set = set()
# # #             for fut in as_completed(pending_futures):
# # #                 done_set.add(fut)
# # #                 break  # process one at a time for circuit breaker accuracy

# # #             for fut in done_set:
# # #                 pending_futures.pop(fut)
# # #                 result = fut.result()

# # #                 if result["status"] == "completed":
# # #                     completed += 1
# # #                     consecutive_failures = 0
# # #                 elif result["status"] == "retry":
# # #                     retry_queue.append(result)
# # #                     consecutive_failures += 1
# # #                 else:
# # #                     failed += 1
# # #                     failed_details.append(result)
# # #                     consecutive_failures += 1

# # #                 if consecutive_failures >= settings.CW_CIRCUIT_BREAKER_THRESHOLD:
# # #                     circuit_broken = True
# # #                     logger.warning(
# # #                         f"[{job_type}] Circuit breaker triggered after "
# # #                         f"{consecutive_failures} consecutive failures"
# # #                     )

# # #             # Submit more work only if circuit is healthy
# # #             if not circuit_broken:
# # #                 _submit_next()
# # #             elif pending_futures:
# # #                 # Cancel remaining futures and drain them
# # #                 for remaining_fut in list(pending_futures):
# # #                     remaining_fut.cancel()
# # #                 # Drain any that were already running
# # #                 for remaining_fut in as_completed(pending_futures):
# # #                     res = remaining_fut.result()
# # #                     if res["status"] == "completed":
# # #                         completed += 1
# # #                     elif res["status"] == "retry":
# # #                         retry_queue.append(res)
# # #                     else:
# # #                         failed += 1
# # #                         failed_details.append(res)
# # #                 pending_futures.clear()

# # #     # Circuit breaker alert
# # #     if circuit_broken:
# # #         notifier.send_circuit_breaker_alert(
# # #             {"job_type": job_type, "id": job_run_id}, consecutive_failures
# # #         )

# # #     # Retry pass (if any retries collected)
# # #     if retry_queue and not circuit_broken:
# # #         import time

# # #         if settings.SHIPMENT_RETRY_DELAY > 0:
# # #             time.sleep(settings.SHIPMENT_RETRY_DELAY)
# # #         for item in retry_queue:
# # #             result = process_shipment(
# # #                 item["shipment_id"],
# # #                 job_run_id,
# # #                 db,
# # #                 cw_client,
# # #                 settings,
# # #                 retry_count=item["retry_count"],
# # #             )
# # #             if result["status"] == "completed":
# # #                 completed += 1
# # #             else:
# # #                 failed += 1
# # #                 failed_details.append(result)

# # #     # Complete job run
# # #     db.complete_job_run(job_run_id, completed, failed)

# # #     if failed > 0:
# # #         notifier.send_job_failure(
# # #             {
# # #                 "job_type": job_type,
# # #                 "id": job_run_id,
# # #                 "total_shipments": len(shipment_ids),
# # #                 "failed_count": failed,
# # #             },
# # #             [
# # #                 {"shipment_id": d["shipment_id"], "error_message": d.get("error", "unknown")}
# # #                 for d in failed_details
# # #             ],
# # #         )

# # #     logger.info(f"[{job_type}] Done: {completed} completed, {failed} failed")
# # #     return job_run_id


# # def run_job(job_type, shipment_ids, db, cw_client, notifier, settings, job_run_id, parent_job_run_id=None):
# #     """Orchestrate parallel processing of shipments with circuit breaker and retry."""

# #     print(f"🚀 run_job started with {len(shipment_ids)} shipments")

# #     # 🔥 IMPORTANT: DO NOT create job_run_id again here

# #     # Filter duplicates if parent cycle provided
# #     if parent_job_run_id:
# #         shipment_ids = [sid for sid in shipment_ids if not db.was_processed_in_cycle(sid, parent_job_run_id)]

# #     if not shipment_ids:
# #         logger.info(f"[{job_type}] No shipments to process")
# #         db.complete_job_run(job_run_id, 0, 0)
# #         return job_run_id

# #     # =========================
# #     # 🔥 BATCH TRACKING INSERT
# #     # =========================
# #     TRACK_BATCH_SIZE = 50

# #     print(f"📊 Tracking {len(shipment_ids)} shipments in batches...")

# #     for i in range(0, len(shipment_ids), TRACK_BATCH_SIZE):
# #         batch = shipment_ids[i:i+TRACK_BATCH_SIZE]

# #         print(f"📦 Tracking batch {i} → {i+len(batch)}")

# #         db.bulk_track_shipments(batch, job_run_id, job_type)

# #     logger.info(f"[{job_type}] Processing {len(shipment_ids)} shipments")

# #     completed = 0
# #     failed = 0
# #     failed_details = []
# #     consecutive_failures = 0
# #     circuit_broken = False
# #     retry_queue = []

# #     # =========================
# #     # THREAD PROCESSING
# #     # =========================
# #     with ThreadPoolExecutor(max_workers=settings.MAX_PARALLEL_REQUESTS) as pool:
# #         pending_futures = {}
# #         sid_iter = iter(shipment_ids)

# #         def _submit_next():
# #             try:
# #                 sid = next(sid_iter)
# #                 fut = pool.submit(process_shipment, sid, job_run_id, db, cw_client, settings)
# #                 pending_futures[fut] = sid
# #                 return True
# #             except StopIteration:
# #                 return False

# #         # Seed initial threads
# #         for _ in range(min(settings.MAX_PARALLEL_REQUESTS, len(shipment_ids))):
# #             _submit_next()

# #         while pending_futures:
# #             done_set = set()

# #             for fut in as_completed(pending_futures):
# #                 done_set.add(fut)
# #                 break  # process one at a time

# #             for fut in done_set:
# #                 pending_futures.pop(fut)
# #                 result = fut.result()

# #                 if result["status"] == "completed":
# #                     completed += 1
# #                     consecutive_failures = 0

# #                 elif result["status"] == "retry":
# #                     retry_queue.append(result)
# #                     consecutive_failures += 1

# #                 else:
# #                     failed += 1
# #                     failed_details.append(result)
# #                     consecutive_failures += 1

# #                 # 🔥 Circuit breaker
# #                 if consecutive_failures >= settings.CW_CIRCUIT_BREAKER_THRESHOLD:
# #                     circuit_broken = True
# #                     logger.warning(
# #                         f"[{job_type}] Circuit breaker triggered after "
# #                         f"{consecutive_failures} consecutive failures"
# #                     )

# #             # Submit next only if safe
# #             if not circuit_broken:
# #                 _submit_next()
# #             elif pending_futures:
# #                 for remaining_fut in list(pending_futures):
# #                     remaining_fut.cancel()

# #                 for remaining_fut in as_completed(pending_futures):
# #                     res = remaining_fut.result()

# #                     if res["status"] == "completed":
# #                         completed += 1
# #                     elif res["status"] == "retry":
# #                         retry_queue.append(res)
# #                     else:
# #                         failed += 1
# #                         failed_details.append(res)

# #                 pending_futures.clear()

# #     # =========================
# #     # CIRCUIT BREAKER ALERT
# #     # =========================
# #     if circuit_broken:
# #         notifier.send_circuit_breaker_alert(
# #             {"job_type": job_type, "id": job_run_id}, consecutive_failures
# #         )

# #     # =========================
# #     # RETRY LOGIC
# #     # =========================
# #     if retry_queue and not circuit_broken:
# #         import time

# #         if settings.SHIPMENT_RETRY_DELAY > 0:
# #             time.sleep(settings.SHIPMENT_RETRY_DELAY)

# #         for item in retry_queue:
# #             result = process_shipment(
# #                 item["shipment_id"],
# #                 job_run_id,
# #                 db,
# #                 cw_client,
# #                 settings,
# #                 retry_count=item["retry_count"],
# #             )

# #             if result["status"] == "completed":
# #                 completed += 1
# #             else:
# #                 failed += 1
# #                 failed_details.append(result)

# #     # =========================
# #     # COMPLETE JOB
# #     # =========================
# #     db.complete_job_run(job_run_id, completed, failed)

# #     if failed > 0:
# #         notifier.send_job_failure(
# #             {
# #                 "job_type": job_type,
# #                 "id": job_run_id,
# #                 "total_shipments": len(shipment_ids),
# #                 "failed_count": failed,
# #             },
# #             [
# #                 {"shipment_id": d["shipment_id"], "error_message": d.get("error", "unknown")}
# #                 for d in failed_details
# #             ],
# #         )

# #     logger.info(f"[{job_type}] Done: {completed} completed, {failed} failed")

# #     return job_run_id


# """
# Shared processing logic — the core engine for all pipeline jobs.

# process_shipment() handles one shipment end-to-end:
#   CW fetch -> parse -> ETA/ETD snapshot -> milestones -> delays -> status -> upsert

# run_job() orchestrates parallel processing with circuit breaker and retry.
# """

# import json
# import logging
# import traceback
# import threading
# from concurrent.futures import ThreadPoolExecutor, as_completed
# from datetime import datetime, timezone
# from requests.exceptions import Timeout, ConnectionError as ReqConnectionError

# from pipeline.parser import parse_shipment
# from pipeline.milestones import (
#     build_milestones,
#     build_milestones_reformed,
#     derive_status,
#     get_last_completed_event,
#     extract_milestones_from_customized_fields,
#     extract_service_level_code,
#     SEQUENCES,
# )
# from pipeline.db import apply_eta_snapshot, apply_actual_snapshot
# from pipeline.helpers import dump_json

# logger = logging.getLogger("pipeline.jobs.processing")


# def process_shipment(shipment_id, job_run_id, db, cw_client, settings, retry_count=0):
#     """Process a single shipment: fetch from CW, parse, build milestones, upsert."""
#     try:
#         # Mark in_progress
#         db.update_tracking(shipment_id, job_run_id, "in_progress")

#         # 1. Fetch from CargoWise
#         shipment_dict = cw_client.fetch_shipment(shipment_id)
#         documents = cw_client.fetch_documents(shipment_id)

#         # 2. Parse into flat record
#         record = parse_shipment(shipment_id, shipment_dict, documents)

#         # 3. Extract dates from parser output
#         eta_custom = record.pop("eta_custom", None)
#         etd_custom = record.pop("etd_custom", None)
#         actual_arrival_raw = record.pop("actual_arrival_raw", None)
#         actual_departure_raw = record.pop("actual_departure_raw", None)

#         # 4. Apply ETA/ETD snapshot logic
#         existing_eta = db.fetch_eta_etd(shipment_id)
#         if existing_eta:
#             eta_result = apply_eta_snapshot(
#                 {"currentETA": existing_eta.get("currentETA"), "updatedETA": existing_eta.get("updatedETA")},
#                 eta_custom,
#             )
#             etd_result = apply_eta_snapshot(
#                 {"currentETA": existing_eta.get("currentETD"), "updatedETA": existing_eta.get("updatedETD")},
#                 etd_custom,
#             )
#             record["currentETA"] = eta_result["currentETA"]
#             record["updatedETA"] = eta_result["updatedETA"]
#             record["currentETD"] = etd_result["currentETA"]
#             record["updatedETD"] = etd_result["updatedETA"]
#         else:
#             # First insertion
#             record["currentETA"] = eta_custom
#             record["updatedETA"] = eta_custom
#             record["currentETD"] = etd_custom
#             record["updatedETD"] = etd_custom

#         # 5. Apply Actual Arrival/Departure snapshot
#         existing_actuals = db.fetch_actuals(shipment_id)
#         if existing_actuals:
#             arr = apply_actual_snapshot(
#                 {
#                     "currentActualArrival": existing_actuals.get("currentActualArrival"),
#                     "updatedActualArrival": existing_actuals.get("updatedActualArrival"),
#                 },
#                 actual_arrival_raw,
#                 "Arrival",
#             )
#             dep = apply_actual_snapshot(
#                 {
#                     "currentActualDeparture": existing_actuals.get("currentActualDeparture"),
#                     "updatedActualDeparture": existing_actuals.get("updatedActualDeparture"),
#                 },
#                 actual_departure_raw,
#                 "Departure",
#             )
#             record.update(arr)
#             record.update(dep)
#         else:
#             record["currentActualArrival"] = actual_arrival_raw
#             record["updatedActualArrival"] = actual_arrival_raw
#             record["currentActualDeparture"] = actual_departure_raw
#             record["updatedActualDeparture"] = actual_departure_raw

#         # 6. Build milestones
#         transport_mode = (record.get("JS_TransportMode") or "").upper()
#         # Get service level from the shipment dict
#         sub = shipment_dict.get("SubShipmentCollection", {}).get("SubShipment", {})
#         if isinstance(sub, list):
#             sub = sub[0] if sub else {}
#         service_level = extract_service_level_code(shipment_dict, sub)

#         # Get customized fields for milestones
#         customized_fields = []
#         for level in [shipment_dict, sub]:
#             cf = (level or {}).get("CustomizedFieldCollection", {}).get("CustomizedField")
#             if cf:
#                 if isinstance(cf, list):
#                     customized_fields.extend(cf)
#                 elif isinstance(cf, dict):
#                     customized_fields.append(cf)

#         # Raw milestones
#         raw_milestones = extract_milestones_from_customized_fields(customized_fields, transport_mode)
#         record["milestones"] = json.dumps(raw_milestones)

#         # Build actuals dict for milestone builder
#         actuals = {}
#         for m in raw_milestones:
#             cf = m.get("customField")
#             ad = m.get("actualDate")
#             if cf and ad:
#                 actuals[cf] = ad

#         dates = {
#             "currentETA": record.get("currentETA"),
#             "updatedETA": record.get("updatedETA"),
#             "currentETD": record.get("currentETD"),
#             "updatedETD": record.get("updatedETD"),
#             "currentActualArrival": record.get("currentActualArrival"),
#             "updatedActualArrival": record.get("updatedActualArrival"),
#             "currentActualDeparture": record.get("currentActualDeparture"),
#             "updatedActualDeparture": record.get("updatedActualDeparture"),
#         }

#         milestones_new = build_milestones(transport_mode, service_level, actuals, dates)
#         milestones_reformed = build_milestones_reformed(transport_mode, service_level, customized_fields)
#         record["milestones_new"] = json.dumps(milestones_new, default=str)
#         record["milestones_reformed"] = json.dumps(milestones_reformed, default=str)

#         # 7. Derive status
#         primary_status, derived_statuses = derive_status(milestones_reformed, transport_mode, service_level)
#         record["primary_status"] = primary_status
#         record["derived_statuses"] = json.dumps(derived_statuses)

#         # 8. Get last completed event
#         delay, actual_date, event = get_last_completed_event(milestones_reformed, transport_mode, service_level)
#         record["latest_completed_delay"] = delay
#         record["latest_completed_actualDate"] = actual_date
#         record["latest_completed_event"] = event

#         # 9. Extract delay values from reformed milestones
#         def _find_delay(ev):
#             for m in milestones_reformed:
#                 if (m.get("eventStatus") or "").lower() == ev.lower():
#                     return m.get("delay")
#             return None

#         record["delay_arrival"] = _find_delay("Arrived") or _find_delay("Arrival at final destination")
#         record["delay_departure"] = _find_delay("Sailed") or _find_delay("Departed")
#         record["delay_actual_arrival"] = record["delay_arrival"]
#         record["delay_actual_departure"] = record["delay_departure"]

#         # Set date aliases
#         record["arrival_date"] = record.get("currentETA")
#         record["dep_date"] = record.get("currentETD")
#         record["vesselArrivedDate"] = record.get("currentActualArrival")

#         # 10. Upsert
#         db.upsert_shipment(record)
#         db.update_tracking(shipment_id, job_run_id, "completed")
#         return {"status": "completed", "shipment_id": shipment_id}

#     except (Timeout, ReqConnectionError) as e:
#         logger.warning(f"Transient error for {shipment_id}: {e}")
#         if retry_count < settings.SHIPMENT_RETRY_MAX:
#             return {
#                 "status": "retry",
#                 "shipment_id": shipment_id,
#                 "retry_count": retry_count + 1,
#                 "error": str(e),
#             }
#         logger.error(f"Max retries exceeded for {shipment_id}: {e}")
#         db.update_tracking(shipment_id, job_run_id, "failed", error=str(e))
#         return {"status": "failed", "shipment_id": shipment_id, "error": str(e)}

#     except Exception as e:
#         error_msg = f"{e}\n{traceback.format_exc()}"
#         logger.error(f"Failed processing {shipment_id}: {e}")
#         db.update_tracking(shipment_id, job_run_id, "failed", error=error_msg)
#         return {"status": "failed", "shipment_id": shipment_id, "error": str(e)}


# def run_job(job_type, shipment_ids, db, cw_client, notifier, settings, job_run_id=None, parent_job_run_id=None):
#     print(f"🚀 run_job started with {len(shipment_ids)} shipments")
#     """Orchestrate parallel processing of shipments with circuit breaker and retry."""
    
   
#     if job_run_id is None:
#         job_run_id = db.create_job_run(job_type)

#     # Filter duplicates if parent cycle provided
#     if parent_job_run_id:
#         shipment_ids = [sid for sid in shipment_ids if not db.was_processed_in_cycle(sid, parent_job_run_id)]

#     if not shipment_ids:
#         logger.info(f"[{job_type}] No shipments to process")
#         db.complete_job_run(job_run_id, 0, 0)
#         return job_run_id

#     db.bulk_track_shipments(shipment_ids, job_run_id, job_type)
#     logger.info(f"[{job_type}] Processing {len(shipment_ids)} shipments")


#     completed = 0
#     failed = 0
#     failed_details = []
#     consecutive_failures = 0
#     circuit_broken = False
#     retry_queue = []

#     # Process with ThreadPoolExecutor, feeding work incrementally so the
#     # circuit breaker can halt submission before all futures are in flight.
#     with ThreadPoolExecutor(max_workers=settings.MAX_PARALLEL_REQUESTS) as pool:
#         pending_futures = {}
#         sid_iter = iter(shipment_ids)

#         def _submit_next():
#             """Submit the next shipment from the iterator, if available."""
#             try:
#                 sid = next(sid_iter)
#                 fut = pool.submit(process_shipment, sid, job_run_id, db, cw_client, settings)
#                 pending_futures[fut] = sid
#                 return True
#             except StopIteration:
#                 return False

#         # Seed the pool up to max_workers
#         for _ in range(min(settings.MAX_PARALLEL_REQUESTS, len(shipment_ids))):
#             _submit_next()

#         while pending_futures:
#             # Wait for any single future to complete
#             done_set = set()
#             for fut in as_completed(pending_futures):
#                 done_set.add(fut)
#                 break  # process one at a time for circuit breaker accuracy

#             for fut in done_set:
#                 pending_futures.pop(fut)
#                 result = fut.result()

#                 if result["status"] == "completed":
#                     completed += 1
#                     consecutive_failures = 0
#                 elif result["status"] == "retry":
#                     retry_queue.append(result)
#                     consecutive_failures += 1
#                 else:
#                     failed += 1
#                     failed_details.append(result)
#                     consecutive_failures += 1

#                 if consecutive_failures >= settings.CW_CIRCUIT_BREAKER_THRESHOLD:
#                     circuit_broken = True
#                     logger.warning(
#                         f"[{job_type}] Circuit breaker triggered after "
#                         f"{consecutive_failures} consecutive failures"
#                     )

#             # Submit more work only if circuit is healthy
#             if not circuit_broken:
#                 _submit_next()
#             elif pending_futures:
#                 # Cancel remaining futures and drain them
#                 for remaining_fut in list(pending_futures):
#                     remaining_fut.cancel()
#                 # Drain any that were already running
#                 for remaining_fut in as_completed(pending_futures):
#                     res = remaining_fut.result()
#                     if res["status"] == "completed":
#                         completed += 1
#                     elif res["status"] == "retry":
#                         retry_queue.append(res)
#                     else:
#                         failed += 1
#                         failed_details.append(res)
#                 pending_futures.clear()

#     # Circuit breaker alert
#     if circuit_broken:
#         notifier.send_circuit_breaker_alert(
#             {"job_type": job_type, "id": job_run_id}, consecutive_failures
#         )

#     # Retry pass (if any retries collected)
#     if retry_queue and not circuit_broken:
#         import time

#         if settings.SHIPMENT_RETRY_DELAY > 0:
#             time.sleep(settings.SHIPMENT_RETRY_DELAY)
#         for item in retry_queue:
#             result = process_shipment(
#                 item["shipment_id"],
#                 job_run_id,
#                 db,
#                 cw_client,
#                 settings,
#                 retry_count=item["retry_count"],
#             )
#             if result["status"] == "completed":
#                 completed += 1
#             else:
#                 failed += 1
#                 failed_details.append(result)

#     # Complete job run
#     db.complete_job_run(job_run_id, completed, failed)

#     if failed > 0:
#         notifier.send_job_failure(
#             {
#                 "job_type": job_type,
#                 "id": job_run_id,
#                 "total_shipments": len(shipment_ids),
#                 "failed_count": failed,
#             },
#             [
#                 {"shipment_id": d["shipment_id"], "error_message": d.get("error", "unknown")}
#                 for d in failed_details
#             ],
#         )

#     logger.info(f"[{job_type}] Done: {completed} completed, {failed} failed")
#     return job_run_id



# working code for service levels

# """
# Shared processing logic — the core engine for all pipeline jobs.

# process_shipment() handles one shipment end-to-end:
#   CW fetch -> parse -> ETA/ETD snapshot -> milestones -> delays -> status -> upsert

# run_job() orchestrates parallel processing with circuit breaker and retry.
# """

# import json
# import logging
# import traceback
# import threading
# from concurrent.futures import ThreadPoolExecutor, as_completed
# from datetime import datetime, timezone
# from requests.exceptions import Timeout, ConnectionError as ReqConnectionError

# from pipeline.parser import parse_shipment
# from pipeline.milestones import (
#     build_milestones,
#     build_milestones_reformed,
#     derive_status,
#     get_last_completed_event,
#     extract_milestones_from_customized_fields,
#     extract_service_level_code,
#     SEQUENCES,
# )
# from pipeline.db import apply_eta_snapshot, apply_actual_snapshot
# from pipeline.helpers import dump_json

# logger = logging.getLogger("pipeline.jobs.processing")


# def process_shipment(shipment_id, job_run_id, db, cw_client, settings, retry_count=0):
#     """Process a single shipment: fetch from CW, parse, build milestones, upsert."""
#     try:
#         # Mark in_progress
#         db.update_tracking(shipment_id, job_run_id, "in_progress")

#         # 1. Fetch from CargoWise
#         print(f"  🔄 [{shipment_id}] Fetching from CargoWise...")
#         shipment_dict = cw_client.fetch_shipment(shipment_id)
#         print(f"  📦 [{shipment_id}] Shipment fetched, fetching documents...")
#         documents = cw_client.fetch_documents(shipment_id)
#         print(f"  📄 [{shipment_id}] Documents fetched, parsing...")

#         # 2. Parse into flat record
#         record = parse_shipment(shipment_id, shipment_dict, documents)

#         # 3. Extract dates from parser output
#         eta_custom = record.pop("eta_custom", None)
#         etd_custom = record.pop("etd_custom", None)
#         actual_arrival_raw = record.pop("actual_arrival_raw", None)
#         actual_departure_raw = record.pop("actual_departure_raw", None)

#         # 4. Apply ETA/ETD snapshot logic
#         existing_eta = db.fetch_eta_etd(shipment_id)
#         if existing_eta:
#             eta_result = apply_eta_snapshot(
#                 {"currentETA": existing_eta.get("currentETA"), "updatedETA": existing_eta.get("updatedETA")},
#                 eta_custom,
#             )
#             etd_result = apply_eta_snapshot(
#                 {"currentETA": existing_eta.get("currentETD"), "updatedETA": existing_eta.get("updatedETD")},
#                 etd_custom,
#             )
#             record["currentETA"] = eta_result["currentETA"]
#             record["updatedETA"] = eta_result["updatedETA"]
#             record["currentETD"] = etd_result["currentETA"]
#             record["updatedETD"] = etd_result["updatedETA"]
#         else:
#             # First insertion
#             record["currentETA"] = eta_custom
#             record["updatedETA"] = eta_custom
#             record["currentETD"] = etd_custom
#             record["updatedETD"] = etd_custom

#         # 5. Apply Actual Arrival/Departure snapshot
#         existing_actuals = db.fetch_actuals(shipment_id)
#         if existing_actuals:
#             arr = apply_actual_snapshot(
#                 {
#                     "currentActualArrival": existing_actuals.get("currentActualArrival"),
#                     "updatedActualArrival": existing_actuals.get("updatedActualArrival"),
#                 },
#                 actual_arrival_raw,
#                 "Arrival",
#             )
#             dep = apply_actual_snapshot(
#                 {
#                     "currentActualDeparture": existing_actuals.get("currentActualDeparture"),
#                     "updatedActualDeparture": existing_actuals.get("updatedActualDeparture"),
#                 },
#                 actual_departure_raw,
#                 "Departure",
#             )
#             record.update(arr)
#             record.update(dep)
#         else:
#             record["currentActualArrival"] = actual_arrival_raw
#             record["updatedActualArrival"] = actual_arrival_raw
#             record["currentActualDeparture"] = actual_departure_raw
#             record["updatedActualDeparture"] = actual_departure_raw

#         # 6. Build milestones
#         transport_mode = (record.get("JS_TransportMode") or "").upper()
#         # Get service level from the shipment dict
#         sub = shipment_dict.get("SubShipmentCollection", {}).get("SubShipment", {})
#         if isinstance(sub, list):
#             sub = sub[0] if sub else {}
#         service_level = extract_service_level_code(shipment_dict, sub)

#         # Get customized fields for milestones
#         customized_fields = []
#         for level in [shipment_dict, sub]:
#             cf = (level or {}).get("CustomizedFieldCollection", {}).get("CustomizedField")
#             if cf:
#                 if isinstance(cf, list):
#                     customized_fields.extend(cf)
#                 elif isinstance(cf, dict):
#                     customized_fields.append(cf)

#         # Raw milestones
#         raw_milestones = extract_milestones_from_customized_fields(customized_fields, transport_mode)
#         record["milestones"] = json.dumps(raw_milestones)

#         # Build actuals dict for milestone builder
#         actuals = {}
#         for m in raw_milestones:
#             cf = m.get("customField")
#             ad = m.get("actualDate")
#             if cf and ad:
#                 actuals[cf] = ad

#         dates = {
#             "currentETA": record.get("currentETA"),
#             "updatedETA": record.get("updatedETA"),
#             "currentETD": record.get("currentETD"),
#             "updatedETD": record.get("updatedETD"),
#             "currentActualArrival": record.get("currentActualArrival"),
#             "updatedActualArrival": record.get("updatedActualArrival"),
#             "currentActualDeparture": record.get("currentActualDeparture"),
#             "updatedActualDeparture": record.get("updatedActualDeparture"),
#         }

#         milestones_new = build_milestones(transport_mode, service_level, actuals, dates)
#         milestones_reformed = build_milestones_reformed(transport_mode, service_level, customized_fields)
#         record["milestones_new"] = json.dumps(milestones_new, default=str)
#         record["milestones_reformed"] = json.dumps(milestones_reformed, default=str)

#         # 7. Derive status
#         primary_status, derived_statuses = derive_status(milestones_reformed, transport_mode, service_level)
#         record["primary_status"] = primary_status
#         record["derived_statuses"] = json.dumps(derived_statuses)

#         # 8. Get last completed event
#         delay, actual_date, event = get_last_completed_event(milestones_reformed, transport_mode, service_level)
#         record["latest_completed_delay"] = delay
#         record["latest_completed_actualDate"] = actual_date
#         record["latest_completed_event"] = event

#         # 9. Extract delay values from reformed milestones
#         def _find_delay(ev):
#             for m in milestones_reformed:
#                 if (m.get("eventStatus") or "").lower() == ev.lower():
#                     return m.get("delay")
#             return None

#         record["delay_arrival"] = _find_delay("Arrived") or _find_delay("Arrival at final destination")
#         record["delay_departure"] = _find_delay("Sailed") or _find_delay("Departed")
#         record["delay_actual_arrival"] = record["delay_arrival"]
#         record["delay_actual_departure"] = record["delay_departure"]

#         # Set date aliases
#         record["arrival_date"] = record.get("currentETA")
#         record["dep_date"] = record.get("currentETD")
#         record["vesselArrivedDate"] = record.get("currentActualArrival")

#         # 10. Upsert
#         print(f"  💾 [{shipment_id}] Upserting to DB...")
#         db.upsert_shipment(record)
#         db.update_tracking(shipment_id, job_run_id, "completed")
#         print(f"  ✅ [{shipment_id}] Done!")
#         return {"status": "completed", "shipment_id": shipment_id}

#     except (Timeout, ReqConnectionError) as e:
#         logger.warning(f"Transient error for {shipment_id}: {e}")
#         print(f"  ⚠️ [{shipment_id}] Transient error: {e}")
#         if retry_count < settings.SHIPMENT_RETRY_MAX:
#             return {
#                 "status": "retry",
#                 "shipment_id": shipment_id,
#                 "retry_count": retry_count + 1,
#                 "error": str(e),
#             }
#         logger.error(f"Max retries exceeded for {shipment_id}: {e}")
#         db.update_tracking(shipment_id, job_run_id, "failed", error=str(e))
#         return {"status": "failed", "shipment_id": shipment_id, "error": str(e)}

#     except Exception as e:
#         error_msg = f"{e}\n{traceback.format_exc()}"
#         logger.error(f"Failed processing {shipment_id}: {e}")
#         print(f"  ❌ [{shipment_id}] Exception: {e}")
#         db.update_tracking(shipment_id, job_run_id, "failed", error=error_msg)
#         return {"status": "failed", "shipment_id": shipment_id, "error": str(e)}


# def run_job(job_type, shipment_ids, db, cw_client, notifier, settings, job_run_id=None, parent_job_run_id=None):
#     print(f"🚀 run_job started with {len(shipment_ids)} shipments")
#     """Orchestrate parallel processing of shipments with circuit breaker and retry."""

#     print(f"⏳ 1. Creating job run...")
#     if job_run_id is None:
#         job_run_id = db.create_job_run(job_type)
#     print(f"✅ 1. job_run created: {job_run_id}")

#     # Filter duplicates if parent cycle provided
#     print(f"⏳ 2. Filtering duplicates...")
#     if parent_job_run_id:
#         shipment_ids = [sid for sid in shipment_ids if not db.was_processed_in_cycle(sid, parent_job_run_id)]
#     print(f"✅ 2. After filter: {len(shipment_ids)} shipments")

#     if not shipment_ids:
#         logger.info(f"[{job_type}] No shipments to process")
#         db.complete_job_run(job_run_id, 0, 0)
#         return job_run_id

#     print(f"⏳ 3. Inserting tracking rows for {len(shipment_ids)} shipments...")
#     db.bulk_track_shipments(shipment_ids, job_run_id, job_type)
#     print(f"✅ 3. Tracking rows inserted")

#     total = len(shipment_ids)
#     logger.info(f"[{job_type}] Processing {total} shipments")
#     print(f"📋 Starting processing of {total} shipments with {settings.MAX_PARALLEL_REQUESTS} parallel workers...")

#     completed = 0
#     failed = 0
#     failed_details = []
#     consecutive_failures = 0
#     circuit_broken = False
#     retry_queue = []

#     # Process with ThreadPoolExecutor, feeding work incrementally so the
#     # circuit breaker can halt submission before all futures are in flight.
#     print(f"⏳ 4. Creating thread pool...")
#     with ThreadPoolExecutor(max_workers=settings.MAX_PARALLEL_REQUESTS) as pool:
#         pending_futures = {}
#         sid_iter = iter(shipment_ids)

#         def _submit_next():
#             """Submit the next shipment from the iterator, if available."""
#             try:
#                 sid = next(sid_iter)
#                 fut = pool.submit(process_shipment, sid, job_run_id, db, cw_client, settings)
#                 pending_futures[fut] = sid
#                 return True
#             except StopIteration:
#                 return False

#         # Seed the pool up to max_workers
#         print(f"⏳ 5. Seeding pool with first {min(settings.MAX_PARALLEL_REQUESTS, len(shipment_ids))} shipments...")
#         for _ in range(min(settings.MAX_PARALLEL_REQUESTS, len(shipment_ids))):
#             _submit_next()
#         print(f"✅ 5. Pool seeded. Waiting for results...")

#         while pending_futures:
#             # Wait for any single future to complete
#             done_set = set()
#             for fut in as_completed(pending_futures):
#                 done_set.add(fut)
#                 break  # process one at a time for circuit breaker accuracy

#             for fut in done_set:
#                 pending_futures.pop(fut)
#                 result = fut.result()

#                 if result["status"] == "completed":
#                     completed += 1
#                     consecutive_failures = 0
#                     if completed % 10 == 0 or completed <= 5:
#                         print(f"✅ {completed}/{total} completed ({failed} failed)")
#                 elif result["status"] == "retry":
#                     retry_queue.append(result)
#                     consecutive_failures += 1
#                 else:
#                     failed += 1
#                     failed_details.append(result)
#                     consecutive_failures += 1
#                     if failed <= 10:
#                         print(f"❌ Failed {result['shipment_id']}: {result.get('error', 'unknown')[:80]}")

#                 if consecutive_failures >= settings.CW_CIRCUIT_BREAKER_THRESHOLD:
#                     circuit_broken = True
#                     print(f"🔴 CIRCUIT BREAKER triggered after {consecutive_failures} consecutive failures!")
#                     logger.warning(
#                         f"[{job_type}] Circuit breaker triggered after "
#                         f"{consecutive_failures} consecutive failures"
#                     )

#             # Submit more work only if circuit is healthy
#             if not circuit_broken:
#                 _submit_next()
#             elif pending_futures:
#                 print(f"🔴 Circuit broken — draining {len(pending_futures)} remaining futures...")
#                 # Cancel remaining futures and drain them
#                 for remaining_fut in list(pending_futures):
#                     remaining_fut.cancel()
#                 # Drain any that were already running
#                 for remaining_fut in as_completed(pending_futures):
#                     res = remaining_fut.result()
#                     if res["status"] == "completed":
#                         completed += 1
#                     elif res["status"] == "retry":
#                         retry_queue.append(res)
#                     else:
#                         failed += 1
#                         failed_details.append(res)
#                 pending_futures.clear()

#     print(f"✅ 6. Thread pool finished. Completed: {completed}, Failed: {failed}, Retries: {len(retry_queue)}")

#     # Circuit breaker alert
#     if circuit_broken:
#         notifier.send_circuit_breaker_alert(
#             {"job_type": job_type, "id": job_run_id}, consecutive_failures
#         )

#     # Retry pass (if any retries collected)
#     if retry_queue and not circuit_broken:
#         import time

#         print(f"⏳ 7. Retrying {len(retry_queue)} shipments after {settings.SHIPMENT_RETRY_DELAY}s delay...")
#         if settings.SHIPMENT_RETRY_DELAY > 0:
#             time.sleep(settings.SHIPMENT_RETRY_DELAY)
#         for item in retry_queue:
#             result = process_shipment(
#                 item["shipment_id"],
#                 job_run_id,
#                 db,
#                 cw_client,
#                 settings,
#                 retry_count=item["retry_count"],
#             )
#             if result["status"] == "completed":
#                 completed += 1
#             else:
#                 failed += 1
#                 failed_details.append(result)
#         print(f"✅ 7. Retries done. Final: {completed} completed, {failed} failed")

#     # Complete job run
#     db.complete_job_run(job_run_id, completed, failed)

#     if failed > 0:
#         notifier.send_job_failure(
#             {
#                 "job_type": job_type,
#                 "id": job_run_id,
#                 "total_shipments": len(shipment_ids),
#                 "failed_count": failed,
#             },
#             [
#                 {"shipment_id": d["shipment_id"], "error_message": d.get("error", "unknown")}
#                 for d in failed_details
#             ],
#         )

#     logger.info(f"[{job_type}] Done: {completed} completed, {failed} failed")
#     print(f"🏁 run_job FINISHED — {completed} completed, {failed} failed")
#     return job_run_id



# working code for service levels above




# new code without service levels

# """
# Shared processing logic — the core engine for all pipeline jobs.
# """

# import json
# import logging
# import traceback
# from concurrent.futures import ThreadPoolExecutor, as_completed
# from requests.exceptions import Timeout, ConnectionError as ReqConnectionError

# from pipeline.parser import parse_shipment
# from pipeline.milestones import (
#     build_milestones,
#     build_milestones_reformed,
#     derive_status,
#     get_last_completed_event,
#     extract_milestones_from_customized_fields,
# )
# from pipeline.db import apply_eta_snapshot, apply_actual_snapshot

# logger = logging.getLogger("pipeline.jobs.processing")


# # ---------------------------------------------------------------------------
# # PROCESS SINGLE SHIPMENT
# # ---------------------------------------------------------------------------

# def process_shipment(shipment_id, job_run_id, db, cw_client, settings, retry_count=0):
#     try:
#         db.update_tracking(shipment_id, job_run_id, "in_progress")

#         shipment_dict = cw_client.fetch_shipment(shipment_id)
#         documents = cw_client.fetch_documents(shipment_id)

#         record = parse_shipment(shipment_id, shipment_dict, documents)

#         # ---------------- ETA / ETD ----------------
#         eta_custom = record.pop("eta_custom", None)
#         etd_custom = record.pop("etd_custom", None)
#         actual_arrival_raw = record.pop("actual_arrival_raw", None)
#         actual_departure_raw = record.pop("actual_departure_raw", None)

#         existing_eta = db.fetch_eta_etd(shipment_id)

#         if existing_eta:
#             eta_result = apply_eta_snapshot(
#                 {"currentETA": existing_eta.get("currentETA"), "updatedETA": existing_eta.get("updatedETA")},
#                 eta_custom,
#             )
#             etd_result = apply_eta_snapshot(
#                 {"currentETA": existing_eta.get("currentETD"), "updatedETA": existing_eta.get("updatedETD")},
#                 etd_custom,
#             )

#             record["currentETA"] = eta_result["currentETA"]
#             record["updatedETA"] = eta_result["updatedETA"]
#             record["currentETD"] = etd_result["currentETA"]
#             record["updatedETD"] = etd_result["updatedETA"]
#         else:
#             record["currentETA"] = eta_custom
#             record["updatedETA"] = eta_custom
#             record["currentETD"] = etd_custom
#             record["updatedETD"] = etd_custom

#         # ---------------- ACTUALS ----------------
#         existing_actuals = db.fetch_actuals(shipment_id)

#         if existing_actuals:
#             arr = apply_actual_snapshot(
#                 {
#                     "currentActualArrival": existing_actuals.get("currentActualArrival"),
#                     "updatedActualArrival": existing_actuals.get("updatedActualArrival"),
#                 },
#                 actual_arrival_raw,
#                 "Arrival",
#             )
#             dep = apply_actual_snapshot(
#                 {
#                     "currentActualDeparture": existing_actuals.get("currentActualDeparture"),
#                     "updatedActualDeparture": existing_actuals.get("updatedActualDeparture"),
#                 },
#                 actual_departure_raw,
#                 "Departure",
#             )
#             record.update(arr)
#             record.update(dep)
#         else:
#             record["currentActualArrival"] = actual_arrival_raw
#             record["updatedActualArrival"] = actual_arrival_raw
#             record["currentActualDeparture"] = actual_departure_raw
#             record["updatedActualDeparture"] = actual_departure_raw

#         # ---------------- MILESTONES ----------------
#         transport_mode = (record.get("JS_TransportMode") or "").upper()

#         # ✅ Service level removed safely
#         service_level = None

#         # Extract customized fields
#         sub = shipment_dict.get("SubShipmentCollection", {}).get("SubShipment", {})
#         if isinstance(sub, list):
#             sub = sub[0] if sub else {}

#         customized_fields = []
#         for level in [shipment_dict, sub]:
#             cf = (level or {}).get("CustomizedFieldCollection", {}).get("CustomizedField")
#             if cf:
#                 if isinstance(cf, list):
#                     customized_fields.extend(cf)
#                 elif isinstance(cf, dict):
#                     customized_fields.append(cf)

#         raw_milestones = extract_milestones_from_customized_fields(customized_fields, transport_mode)
#         record["milestones"] = json.dumps(raw_milestones)

#         actuals = {
#             m["customField"]: m["actualDate"]
#             for m in raw_milestones
#             if m.get("customField") and m.get("actualDate")
#         }

#         dates = {
#             "currentETA": record.get("currentETA"),
#             "updatedETA": record.get("updatedETA"),
#             "currentETD": record.get("currentETD"),
#             "updatedETD": record.get("updatedETD"),
#             "currentActualArrival": record.get("currentActualArrival"),
#             "updatedActualArrival": record.get("updatedActualArrival"),
#             "currentActualDeparture": record.get("currentActualDeparture"),
#             "updatedActualDeparture": record.get("updatedActualDeparture"),
#         }

#         milestones_new = build_milestones(transport_mode, service_level, actuals, dates)
#         milestones_reformed = build_milestones_reformed(transport_mode, service_level, customized_fields)

#         record["milestones_new"] = json.dumps(milestones_new, default=str)
#         record["milestones_reformed"] = json.dumps(milestones_reformed, default=str)

#         # ---------------- STATUS ----------------
#         primary_status, derived_statuses = derive_status(
#             milestones_reformed, transport_mode, service_level
#         )

#         record["primary_status"] = primary_status
#         record["derived_statuses"] = json.dumps(derived_statuses)

#         # ---------------- LAST COMPLETED ----------------
#         delay, actual_date, event = get_last_completed_event(
#             milestones_reformed, transport_mode, service_level
#         )

#         record["latest_completed_delay"] = delay
#         record["latest_completed_actualDate"] = actual_date
#         record["latest_completed_event"] = event

#         # ---------------- UPSERT ----------------
#         db.upsert_shipment(record)
#         db.update_tracking(shipment_id, job_run_id, "completed")

#         return {"status": "completed", "shipment_id": shipment_id}

#     except (Timeout, ReqConnectionError) as e:
#         if retry_count < settings.SHIPMENT_RETRY_MAX:
#             return {
#                 "status": "retry",
#                 "shipment_id": shipment_id,
#                 "retry_count": retry_count + 1,
#                 "error": str(e),
#             }

#         db.update_tracking(shipment_id, job_run_id, "failed", error=str(e))
#         return {"status": "failed", "shipment_id": shipment_id, "error": str(e)}

#     except Exception as e:
#         error_msg = f"{e}\n{traceback.format_exc()}"
#         db.update_tracking(shipment_id, job_run_id, "failed", error=error_msg)
#         return {"status": "failed", "shipment_id": shipment_id, "error": str(e)}


# # ---------------------------------------------------------------------------
# # RUN JOB (FULL ORIGINAL LOGIC — PRESERVED)
# # ---------------------------------------------------------------------------

# def run_job(job_type, shipment_ids, db, cw_client, notifier, settings, job_run_id=None, parent_job_run_id=None):
#     if job_run_id is None:
#         job_run_id = db.create_job_run(job_type)

#     if parent_job_run_id:
#         shipment_ids = [sid for sid in shipment_ids if not db.was_processed_in_cycle(sid, parent_job_run_id)]

#     if not shipment_ids:
#         db.complete_job_run(job_run_id, 0, 0)
#         return job_run_id

#     db.bulk_track_shipments(shipment_ids, job_run_id, job_type)

#     completed = 0
#     failed = 0
#     retry_queue = []

#     with ThreadPoolExecutor(max_workers=settings.MAX_PARALLEL_REQUESTS) as pool:
#         futures = {
#             pool.submit(process_shipment, sid, job_run_id, db, cw_client, settings): sid
#             for sid in shipment_ids
#         }

#         for fut in as_completed(futures):
#             result = fut.result()

#             if result["status"] == "completed":
#                 completed += 1
#             elif result["status"] == "retry":
#                 retry_queue.append(result)
#             else:
#                 failed += 1

#     # Retry pass
#     for item in retry_queue:
#         result = process_shipment(
#             item["shipment_id"],
#             job_run_id,
#             db,
#             cw_client,
#             settings,
#             retry_count=item["retry_count"],
#         )
#         if result["status"] == "completed":
#             completed += 1
#         else:
#             failed += 1

#     db.complete_job_run(job_run_id, completed, failed)

#     return job_run_id




# script with logs

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