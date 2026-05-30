# """
# Data-driven milestone builder.

# Replaces 8 separate builder functions (~1500 lines) with ONE data-driven
# function + sequence configuration tables.
# """

# from typing import Dict, List, Optional, Tuple

# from pipeline.helpers import (
#     calculate_delay_days,
#     _planned_from_eta,
#     safe_text,
#     safe_list,
# )


# # ---------------------------------------------------------------------------
# # Sequence definitions
# # Each entry: (cf_key, label, planned_source, calc_delay)
# #   cf_key         – customized-field key in CargoWise XML
# #   label          – user-facing eventStatus string
# #   planned_source – how to resolve the planned date:
# #                      None        -> no planned date
# #                      "etd"       -> dates["currentETD"]
# #                      "eta"       -> dates["currentETA"]
# #                      "arrived"   -> actuals["ATA Custom"]
# #                      "eta_buffer"-> ETA + buffer_days
# #   calc_delay     – whether to compute delay (needs both planned & actual)
# # ---------------------------------------------------------------------------

# SEQUENCES: Dict[Tuple[str, str], List[Tuple[str, str, Optional[str], bool]]] = {

#     # ========================== SEA ==========================

#     ("SEA", "DTD"): [
#         ("Opened",          "Opened",                      None,         False),
#         ("Carrier Booking", "Booked",                      None,         False),
#         ("Loaded",          "Loaded and delivered to port", None,         False),
#         ("ATD Custom",      "Sailed",                      "etd",        True),
#         ("ATA Custom",      "Arrived",                     "eta",        True),
#         # ("Gate Out",        "Discharged",                  "arrived",    True),
#         ("Discharged", "Discharged", "arrived", True),
#         ("Gate In Rail",    "Loaded on Rail",              None,         False),
#         ("ATA Rail",        "Arrived at Rail",             None,         False),
#         ("Delivered",       "Delivered",                   "eta_buffer", True),
#     ],

#     ("SEA", "DTP"): [
#         ("Opened",          "Opened",                      None,         False),
#         ("Carrier Booking", "Booked",                      None,         False),
#         ("Loaded",          "Loaded and delivered to port", None,         False),
#         ("ATD Custom",      "Sailed",                      "etd",        True),
#         ("ATA Custom",      "Arrived",                     "eta",        True),
#         # ("Gate Out",        "Discharged",                  "arrived",    True),
#         ("Discharged", "Discharged", "arrived", True),
#         ("Gate In Rail",    "Loaded on Rail",              None,         False),
#         ("ATA Rail",        "Arrived at Rail",             None,         False),
#     ],

#     ("SEA", "PTD"): [
#         ("Opened",          "Opened",                      None,         False),
#         ("Carrier Booking", "Booked",                      None,         False),
#         ("Loaded",          "Loaded and delivered to port", None,         False),
#         ("ATD Custom",      "Sailed",                      "etd",        True),
#         ("ATA Custom",      "Arrived",                     "eta",        True),
#         # ("Gate Out",        "Discharged",                  "arrived",    True),
#         ("Discharged", "Discharged", "arrived", True),
#         ("Gate In Rail",    "Loaded on Rail",              None,         False),
#         ("ATA Rail",        "Arrived at Rail",             None,         False),
#         ("Delivered",       "Delivered",                   "eta_buffer", True),
#     ],

#     ("SEA", "PTP"): [
#         ("Opened",          "Opened",                      None,         False),
#         ("Carrier Booking", "Booked",                      None,         False),
#         ("Loaded",          "Loaded and delivered to port", None,         False),
#         ("ATD Custom",      "Sailed",                      "etd",        True),
#         ("ATA Custom",      "Arrived",                     "eta",        True),
#         # ("Gate Out",        "Discharged",                  "arrived",    True),
#         ("Discharged", "Discharged", "arrived", True),
#         ("Gate In Rail",    "Loaded on Rail",              None,         False),
#         ("ATA Rail",        "Arrived at Rail",             None,         False),
#         ("Delivered",       "Delivered",                   "eta_buffer", True),
#     ],

#     # ========================== AIR ==========================

#     ("AIR", "DTD"): [
#         ("Opened",          "Opened",                         None,         False),
#         ("Carrier Booking", "Booked",                         None,         False),
#         ("Picked",          "Picked up",                      None,         False),
#         ("Gate In",         "Delivered to airline",            None,         False),
#         ("ATD Custom",      "Departed",                       "etd",        True),
#         ("ATA Transit",     "Arrival at transit point",       None,         False),
#         ("ATD Transit",     "Departure from transit point",   None,         False),
#         ("ATA Custom",      "Arrival at final destination",   "eta",        True),
#         ("Delivered",       "Delivered",                      "eta_buffer", True),
#     ],

#     ("AIR", "DTP"): [
#         ("Opened",          "Opened",                         None,         False),
#         ("Carrier Booking", "Booked",                         None,         False),
#         ("Picked",          "Picked up",                      None,         False),
#         ("Gate In",         "Delivered to airline",            None,         False),
#         ("ATD Custom",      "Departed",                       "etd",        True),
#         ("ATA Transit",     "Arrival at transit point",       None,         False),
#         ("ATD Transit",     "Departure from transit point",   None,         False),
#         ("ATA Custom",      "Arrival at final destination",   "eta",        True),
#     ],

#     ("AIR", "PTD"): [
#         ("Opened",          "Opened",                         None,         False),
#         ("Carrier Booking", "Booked",                         None,         False),
#         ("Gate In",         "Delivered to airline",            None,         False),
#         ("ATD Custom",      "Departed",                       "etd",        True),
#         ("ATA Transit",     "Arrival at transit point",       None,         False),
#         ("ATD Transit",     "Departure from transit point",   None,         False),
#         ("ATA Custom",      "Arrival at final destination",   "eta",        True),
#         ("Delivered",       "Delivered",                      "eta_buffer", True),
#     ],

#     ("AIR", "PTP"): [
#         ("Opened",          "Opened",                         None,         False),
#         ("Carrier Booking", "Booked",                         None,         False),
#         ("Gate In",         "Delivered to airline",            None,         False),
#         ("ATD Custom",      "Departed",                       "etd",        True),
#         ("ATA Transit",     "Arrival at transit point",       None,         False),
#         ("ATD Transit",     "Departure from transit point",   None,         False),
#         ("ATA Custom",      "Arrival at final destination",   "eta",        True),
#     ],
# }


# # ---------------------------------------------------------------------------
# # Planned-field map for build_milestones_reformed
# # ---------------------------------------------------------------------------

# PLANNED_FIELD_MAP: Dict[str, str] = {
#     "ATD Custom": "ETD Custom",
#     "ATA Custom": "ETA Custom",
#     "Picked":     "Pick Date",
#     "Gate In":    "Gate In",
#     "Delivered":  "Delivery",
#     "Loaded":     "Load Date",
#     "Discharged": "Discharge Date",
#     "Gate In Rail": "Gate In Rail",
#     "ATA Rail":   "ETA Rail",
# }


# # ---------------------------------------------------------------------------
# # Internal helpers
# # ---------------------------------------------------------------------------

# def _resolve_planned(
#     source: Optional[str],
#     dates: Dict[str, Optional[str]],
#     actuals: Dict[str, Optional[str]],
#     buffer_days: int,
# ) -> Optional[str]:
#     """Map a planned_source key to a concrete planned-date string."""
#     if source is None:
#         return None
#     if source == "etd":
#         return dates.get("currentETD")
#     if source == "eta":
#         return dates.get("currentETA")
#     if source == "arrived":
#         return actuals.get("ATA Custom")
#     if source == "eta_buffer":
#         eta = dates.get("currentETA")
#         return _planned_from_eta(eta, buffer_days)
#     return None


# # ---------------------------------------------------------------------------
# # Core builder
# # ---------------------------------------------------------------------------

# def build_milestones(
#     transport_mode: str,
#     service_level: str,
#     actuals: Dict[str, Optional[str]],
#     dates: Dict[str, Optional[str]],
#     buffer_days: int = 4,
# ) -> List[Dict]:
#     """
#     Single data-driven milestone builder.

#     Parameters
#     ----------
#     transport_mode : "SEA" or "AIR"
#     service_level  : "DTD", "DTP", "PTD", or "PTP"
#     actuals        : {cf_key: actual_date_str} for completed milestones
#     dates          : {"currentETA": ..., "currentETD": ...}
#     buffer_days    : days to add to ETA for Delivered planned date

#     Returns
#     -------
#     List of milestone dicts, each with keys:
#         eventStatus, customField, actualDate, plannedDate, status, delay
#     """
#     key = ((transport_mode or "").upper(), (service_level or "").upper())
#     sequence = SEQUENCES.get(key)
#     if not sequence:
#         return []

#     result: List[Dict] = []

#     for cf_key, label, planned_source, calc_delay in sequence:
#         actual = actuals.get(cf_key)
#         planned = _resolve_planned(planned_source, dates, actuals, buffer_days)

#         delay = None
#         if calc_delay and actual and planned:
#             delay = calculate_delay_days(planned, actual)

#         status = "Completed" if actual else "Pending"

#         result.append({
#             "eventStatus": label,
#             "customField": cf_key,
#             "actualDate": actual,
#             "plannedDate": planned,
#             "status": status,
#             "delay": delay,
#         })

#     return result


# # ---------------------------------------------------------------------------
# # extract_milestones_for_mode
# # ---------------------------------------------------------------------------

# def extract_milestones_for_mode(transport_mode: str) -> Dict[str, str]:
#     """
#     Return milestone mapping based on transport mode.
#     Keys = custom field names (XML), values = eventStatus (user-facing).
#     """
#     mode = (transport_mode or "").upper()

#     if mode == "SEA":
#         return {
#             "Opened": "Opened",
#             "Carrier Booking": "Booked",
#             "ETD Custom": "ETD",
#             "ETA Custom": "ETA",
#             "Loaded": "Loaded and delivered to port",
#             "ATD Custom": "Sailed",
#             "ATA Custom": "Arrived",
#             # "Gate Out": "Discharged",
#             "Discharged": "Discharged",
#             "Gate In Rail": "Loaded on Rail",
#             "ATA Rail": "Arrived at Rail",
#             "Delivered": "Delivered",
#         }

#     if mode == "AIR":
#         return {
#             "Opened": "Opened",
#             "Carrier Booking": "Booked",
#             "ETD Custom": "ETD",
#             "ETA Custom": "ETA",
#             "Picked": "Picked up",
#             "Gate In": "Delivered To Airline (Gate In)",
#             "ATD Custom": "Departed",
#             "ATA Transit": "Arrival at transit point",
#             "ATD Transit": "Departure from transit point",
#             "ATA Custom": "Arrival at final destination",
#             "Delivered": "Delivered",
#         }

#     return {}


# # ---------------------------------------------------------------------------
# # extract_milestones_from_customized_fields
# # ---------------------------------------------------------------------------

# def extract_milestones_from_customized_fields(
#     customized_fields: List[Dict],
#     transport_mode: str,
# ) -> List[Dict]:
#     """
#     Extract milestones for the given transport mode from raw customized fields.

#     Priority: (A) suffix = 2, (M) suffix = 1, no suffix = 0.
#     Higher priority overwrites lower.

#     Returns list of milestone dicts in canonical order.
#     """
#     milestone_map = extract_milestones_for_mode(transport_mode)
#     allowed_fields = list(milestone_map.keys())

#     # Allow 'Discharged' as an extra custom field
#     if "Discharged" not in allowed_fields:
#         allowed_fields.append("Discharged")

#     priority_map = {"A": 2, "M": 1, "": 0}
#     milestone_dict: Dict[str, Dict] = {}

#     for field in safe_list(customized_fields):
#         if not isinstance(field, dict):
#             continue
#         raw_key = safe_text(field.get("Key")) or ""
#         key = raw_key.split("(")[0].strip()
#         value = safe_text(field.get("Value")) or None

#         if key not in allowed_fields:
#             continue

#         # Extract suffix (A / M)
#         suffix = ""
#         if "(" in raw_key and ")" in raw_key:
#             suffix = raw_key.split("(")[-1].replace(")", "").strip().upper()

#         existing = milestone_dict.get(key)

#         # Replace only if higher or equal priority
#         if not existing or priority_map.get(suffix, 0) >= priority_map.get(existing.get("_suffix", ""), 0):
#             milestone_dict[key] = {
#                 "eventStatus": milestone_map.get(key, key),
#                 "customField": key,
#                 "actualDate": value,
#                 "plannedDate": None,
#                 "status": "Completed" if value else "Pending",
#                 "delay": None,
#                 "_suffix": suffix,
#             }

#     # Remove internal suffix key
#     for m in milestone_dict.values():
#         m.pop("_suffix", None)

#     # Build canonical order from milestone_map keys
#     milestones_list: List[Dict] = []
#     for cf in milestone_map.keys():
#         if cf in milestone_dict:
#             milestones_list.append(milestone_dict[cf])
#         else:
#             milestones_list.append({
#                 "eventStatus": milestone_map[cf],
#                 "customField": cf,
#                 "actualDate": None,
#                 "plannedDate": None,
#                 "status": "Pending",
#                 "delay": None,
#             })

#     # Append Discharged if present as an extra CF
#     if "Discharged" in milestone_dict:
#         milestones_list.append(milestone_dict["Discharged"])

#     return milestones_list


# # ---------------------------------------------------------------------------
# # derive_status
# # ---------------------------------------------------------------------------

# def derive_status(
#     milestones: List[Dict],
#     transport_mode: str,
#     service_level: str,
# ) -> Tuple[str, List[str]]:
#     """
#     Status rule:
#     If last milestone in defined sequence is completed -> "Delivered"
#     Else -> "Active"
#     """
#     key = ((transport_mode or "").upper(), (service_level or "").upper())
#     sequence = SEQUENCES.get(key, [])

#     if not sequence:
#         return "Active", ["Active"]

#     # Last milestone cf_key in the defined flow
#     last_cf_key = sequence[-1][0]

#     last_milestone = next(
#         (m for m in milestones if m.get("customField") == last_cf_key),
#         None,
#     )

#     if last_milestone and last_milestone.get("status") == "Completed":
#         return "Delivered", ["Delivered"]

#     return "Active", ["Active"]


# # ---------------------------------------------------------------------------
# # get_last_completed_event
# # ---------------------------------------------------------------------------

# def get_last_completed_event(
#     milestones: List[Dict],
#     transport_mode: str,
#     service_level: str,
# ) -> Tuple[Optional[int], Optional[str], Optional[str]]:
#     """
#     Walk the sequence in order and return info about the last completed event.

#     Returns (delay, actualDate, eventStatus) or (None, None, None).
#     """
#     key = ((transport_mode or "").upper(), (service_level or "").upper())
#     sequence = SEQUENCES.get(key, [])

#     if not sequence:
#         return None, None, None

#     milestone_lookup = {m.get("customField"): m for m in milestones}

#     last_completed = None
#     for cf_key, _, _, _ in sequence:
#         m = milestone_lookup.get(cf_key)
#         if m and m.get("status") == "Completed":
#             last_completed = m

#     if not last_completed:
#         return None, None, None

#     return (
#         last_completed.get("delay"),
#         last_completed.get("actualDate"),
#         last_completed.get("eventStatus"),
#     )


# # ---------------------------------------------------------------------------
# # extract_service_level_code
# # ---------------------------------------------------------------------------

# def extract_service_level_code(
#     shipment: Dict,
#     subshipment: Dict,  # noqa: ARG001 - kept for API consistency with existing callers
# ) -> Optional[str]:
#     """Extract service level code (DTD/DTP/PTD/PTP) from shipment XML dict."""
#     sub_col = shipment.get("SubShipmentCollection", {})
#     sub = sub_col.get("SubShipment")

#     if isinstance(sub, list):
#         sub = sub[0] if sub else {}

#     if isinstance(sub, dict):
#         sl = sub.get("ServiceLevel")
#         if isinstance(sl, dict):
#             code = safe_text(sl.get("Code"))
#             if code:
#                 return code.strip().upper()

#     return None


# # ---------------------------------------------------------------------------
# # build_milestones_reformed
# # ---------------------------------------------------------------------------

# def build_milestones_reformed(
#     transport_mode: str,
#     service_level: str,
#     customized_fields: List[Dict],
# ) -> List[Dict]:
#     """
#     Build milestones using actual/planned maps extracted from customized fields,
#     with PLANNED_FIELD_MAP for resolving planned dates from (M) fields.
#     """
#     transport_mode = (transport_mode or "").upper()
#     service_level = (service_level or "").upper()

#     if not transport_mode or not service_level:
#         return []

#     # ---------------------------------
#     # Extract planned & actual maps
#     # ---------------------------------
#     actual_map: Dict[str, str] = {}
#     planned_map: Dict[str, str] = {}

#     for field in safe_list(customized_fields):
#         if not isinstance(field, dict):
#             continue
#         key = safe_text(field.get("Key"))
#         value = safe_text(field.get("Value"))

#         if not key or not value:
#             continue

#         key = key.replace("( A )", "(A)").replace("( M )", "(M)").strip()

#         # ETD / ETA planned anchors
#         if key.endswith("(A)") and key.startswith("ETD Custom"):
#             planned_map["ETD Custom"] = value
#             continue

#         if key.endswith("(A)") and key.startswith("ETA Custom"):
#             planned_map["ETA Custom"] = value
#             continue

#         # Actual milestones
#         if key.endswith("(A)"):
#             clean = key.replace("(A)", "").strip()
#             actual_map[clean] = value
#             continue

#         # Manual / planned fields
#         if key.endswith("(M)"):
#             clean = key.replace("(M)", "").strip()

#             # AIR Picked is actual, not planned
#             if clean == "Picked":
#                 actual_map[clean] = value
#             else:
#                 clean = clean.replace("Est.", "").strip()
#                 planned_map[clean] = value

#     # ---------------------------------
#     # Build milestones from sequence
#     # ---------------------------------
#     sequence = SEQUENCES.get((transport_mode, service_level), [])
#     milestones: List[Dict] = []

#     for cf_key, label, _, _ in sequence:
#         actual = actual_map.get(cf_key)

#         # Get correct planned key via PLANNED_FIELD_MAP
#         planned_key = PLANNED_FIELD_MAP.get(cf_key, cf_key)
#         planned = planned_map.get(planned_key)

#         delay = None
#         if actual and planned:
#             delay = calculate_delay_days(planned, actual)

#         status = "Completed" if actual else "Pending"

#         milestones.append({
#             "eventStatus": label,
#             "customField": cf_key,
#             "plannedDate": planned,
#             "actualDate": actual,
#             "status": status,
#             "delay": delay,
#         })

#     return milestones





# New milestones without Service Level

# """
# Final milestone builder (TransportMode-based, production-ready)
# """

# import re
# from typing import Dict, List, Optional, Tuple

# from pipeline.helpers import (
#     calculate_delay_days,
#     _planned_from_eta,
#     safe_text,
#     safe_list,
# )

# # ---------------------------------------------------------------------------
# # SEQUENCES (ONLY TRANSPORT MODE)
# # ---------------------------------------------------------------------------

# SEQUENCES: Dict[str, List[Tuple[str, str, Optional[str], bool]]] = {

#     "AIR": [
#         ("Opened",          "Opened", None, False),
#         ("Carrier Booking", "Booked", None, False),
#         ("Picked",          "Picked up", None, False),
#         ("Gate In",         "Delivered to airline", None, False),
#         ("ATD Custom",      "Departed", "etd", True),
#         ("ATA Transit",     "Arrival at transit point", None, False),
#         ("ATD Transit",     "Departure from transit point", None, False),
#         ("ATA Custom",      "Arrival at final destination", "eta", True),
#         ("Delivered",       "Delivered", "eta_buffer", True),
#     ],

#     "SEA": [
#         ("Opened",          "Opened", None, False),
#         ("Carrier Booking", "Booked", None, False),
#         ("Loaded",          "Loaded and delivered to port", None, False),
#         ("ATD Custom",      "Sailed", "etd", True),
#         ("ATA Custom",      "Arrived", "eta", True),
#         ("Discharged",      "Discharged", "arrived", True),
#         ("Gate In Rail",    "Loaded on Rail", None, False),
#         ("ATA Rail",        "Arrived at Rail", None, False),
#         ("Delivered",       "Delivered", "eta_buffer", True),
#     ],
# }

# # ---------------------------------------------------------------------------
# # PLANNED FIELD MAP
# # ---------------------------------------------------------------------------

# PLANNED_FIELD_MAP: Dict[str, str] = {
#     "ATD Custom": "ETD Custom",
#     "ATA Custom": "ETA Custom",
#     "Picked":     "Pick Date",
#     "Gate In":    "Gate In",
#     "Delivered":  "Delivery",
#     "Loaded":     "Loaded",
#     "Discharged": "Discharged",
#     "Gate In Rail": "Gate In Rail",
#     "ATA Rail":   "ETA Rail",
# }

# # ---------------------------------------------------------------------------
# # HELPER
# # ---------------------------------------------------------------------------

# def _resolve_planned(source, dates, actuals, buffer_days):
#     if source is None:
#         return None
#     if source == "etd":
#         return dates.get("currentETD")
#     if source == "eta":
#         return dates.get("currentETA")
#     if source == "arrived":
#         return actuals.get("ATA Custom")
#     if source == "eta_buffer":
#         eta = dates.get("currentETA")
#         return _planned_from_eta(eta, buffer_days)
#     return None

# # ---------------------------------------------------------------------------
# # CORE BUILDER
# # ---------------------------------------------------------------------------

# def build_milestones(transport_mode, service_level, actuals, dates, buffer_days=4):
#     mode = (transport_mode or "").upper()
#     sequence = SEQUENCES.get(mode)

#     if not sequence:
#         return []

#     result = []

#     for cf_key, label, planned_source, calc_delay in sequence:
#         actual = actuals.get(cf_key)
#         planned = _resolve_planned(planned_source, dates, actuals, buffer_days)

#         delay = calculate_delay_days(planned, actual) if calc_delay and actual and planned else None

#         result.append({
#             "eventStatus": label,
#             "customField": cf_key,
#             "actualDate": actual,
#             "plannedDate": planned,
#             "status": "Completed" if actual else "Pending",
#             "delay": delay,
#         })

#     return result

# # ---------------------------------------------------------------------------
# # STATUS
# # ---------------------------------------------------------------------------

# def derive_status(milestones, transport_mode, service_level):
#     mode = (transport_mode or "").upper()
#     sequence = SEQUENCES.get(mode, [])

#     if not sequence:
#         return "Active", ["Active"]

#     last_cf = sequence[-1][0]

#     last = next((m for m in milestones if m["customField"] == last_cf), None)

#     if last and last["status"] == "Completed":
#         return "Delivered", ["Delivered"]

#     return "Active", ["Active"]

# # ---------------------------------------------------------------------------
# # LAST COMPLETED
# # ---------------------------------------------------------------------------

# def get_last_completed_event(milestones, transport_mode, service_level):
#     mode = (transport_mode or "").upper()
#     sequence = SEQUENCES.get(mode, [])

#     if not sequence:
#         return None, None, None

#     lookup = {m["customField"]: m for m in milestones}

#     last = None
#     for cf_key, *_ in sequence:
#         if lookup.get(cf_key) and lookup[cf_key]["status"] == "Completed":
#             last = lookup[cf_key]

#     if not last:
#         return None, None, None

#     return last["delay"], last["actualDate"], last["eventStatus"]


# # ---------------- DELAY ARRIVAL / DEPARTURE ----------------

# # ---------------------------------------------------------------------------
# # MAIN REFORMED BUILDER
# # ---------------------------------------------------------------------------

# def build_milestones_reformed(transport_mode, service_level, customized_fields , job_opened_date=None):

#     transport_mode = (transport_mode or "").upper()

#     if not transport_mode:
#         return []

#     actual_map = {}
#     planned_map = {}

#     NORMALIZATION_MAP = {
#         "Load Date": "Loaded",
#         "Discharge Date": "Discharged",
#         "GateIn": "Gate In",
#     }

#     for field in safe_list(customized_fields):
#         key = safe_text(field.get("Key"))
#         value = safe_text(field.get("Value"))

#         if not key or not value:
#             continue

#         key = key.replace("( A )", "(A)").replace("( M )", "(M)").strip()

#         # -----------------------------
#         # PRIORITY FIELDS (A > M)
#         # -----------------------------
#         if key.startswith("ETD Custom"):
#             if key.endswith("(A)"):
#                 planned_map["ETD Custom"] = value
#             elif key.endswith("(M)") and "ETD Custom" not in planned_map:
#                 planned_map["ETD Custom"] = value
#             continue

#         if key.startswith("ETA Custom"):
#             if key.endswith("(A)"):
#                 planned_map["ETA Custom"] = value
#             elif key.endswith("(M)") and "ETA Custom" not in planned_map:
#                 planned_map["ETA Custom"] = value
#             continue

#         if key.startswith("Delivered"):
#             if key.endswith("(A)"):
#                 actual_map["Delivered"] = value
#             elif key.endswith("(M)") and "Delivered" not in planned_map:
#                 planned_map["Delivered"] = value
#             continue

#         # -----------------------------
#         # ACTUAL
#         # -----------------------------
#         # if key.endswith("(A)"):
#         #     clean = key.replace("(A)", "").strip()

#         #     NORMALIZATION_MAP = {
#         #         "GateIn": "Gate In",
#         #         "Load Date": "Loaded",
#         #         "Discharge Date": "Discharged",
#         #     }

#         #     clean = NORMALIZATION_MAP.get(clean, clean)

#         #     actual_map[clean] = value
#         #     continue
        
#             # -----------------------------
#             # ACTUAL
#             # -----------------------------
#         if key.endswith("(A)") or (key == "Opened" and "(" not in key):
#             clean = key.replace("(A)", "").strip()

#             clean = NORMALIZATION_MAP.get(clean, clean)

#             existing = actual_map.get(clean)

#             if clean == "Opened":
#                 # Priority: Opened(A) > Opened
#                 if key.endswith("(A)"):
#                     actual_map[clean] = value
#                 elif not existing:
#                     actual_map[clean] = value
#             else:
#                 actual_map[clean] = value

#             continue

#         # -----------------------------
#         # PLANNED
#         # -----------------------------
#         if key.endswith("(M)"):
#             clean = key.replace("(M)", "").strip()

#             if clean == "Picked":
#                 actual_map[clean] = value
#             else:
#                 clean = re.sub(r"Est\.?", "", clean).strip()
#                 clean = NORMALIZATION_MAP.get(clean, clean)

#                 planned_map[clean] = value

    
     
  
#     # -----------------------------
#     # BUILD FINAL MILESTONES
#     # -----------------------------
    
     
#                # -----------------------------
#         # FINAL FALLBACK FOR OPENED (Excel)
#         # -----------------------------
#     if not actual_map.get("Opened") and job_opened_date:
#      actual_map["Opened"] = job_opened_date   
    
#     sequence = SEQUENCES.get(transport_mode, [])
#     milestones = []

#     for cf_key, label, _, _ in sequence:
#         actual = actual_map.get(cf_key)

#         planned_key = PLANNED_FIELD_MAP.get(cf_key, cf_key)
#         planned = planned_map.get(planned_key)

#         delay = calculate_delay_days(planned, actual) if actual and planned else None

#         milestones.append({
#             "eventStatus": label,
#             "customField": cf_key,
#             "plannedDate": planned,
#             "actualDate": actual,
#             "status": "Completed" if actual else "Pending",
#             "delay": delay,
#         })

#     return milestones



# # ---------------------------------------------------------------------------
# # BACKWARD COMPATIBILITY (FIXES YOUR IMPORT ERROR)
# # ---------------------------------------------------------------------------

# def extract_milestones_from_customized_fields(customized_fields, transport_mode , job_opened_date=None):
#     """
#     Wrapper to keep old imports working.
#     """
#     return build_milestones_reformed(transport_mode, None, customized_fields , job_opened_date)




# Milestones with Sea Export 


# """
# Data-driven milestone builder.

# Replaces 8 separate builder functions (~1500 lines) with ONE data-driven
# function + sequence configuration tables.
# """

# from typing import Dict, List, Optional, Tuple

# from pipeline.helpers import (
#     calculate_delay_days,
#     _planned_from_eta,
#     safe_text,
#     safe_list,
# )


# # ---------------------------------------------------------------------------
# # Sequence definitions
# # Each entry: (cf_key, label, planned_source, calc_delay)
# #   cf_key         – customized-field key in CargoWise XML
# #   label          – user-facing eventStatus string
# #   planned_source – how to resolve the planned date:
# #                      None        -> no planned date
# #                      "etd"       -> dates["currentETD"]
# #                      "eta"       -> dates["currentETA"]
# #                      "arrived"   -> actuals["ATA Custom"]
# #                      "eta_buffer"-> ETA + buffer_days
# #   calc_delay     – whether to compute delay (needs both planned & actual)
# # ---------------------------------------------------------------------------

# SEQUENCES: Dict[Tuple[str, str], List[Tuple[str, str, Optional[str], bool]]] = {

#     # ========================== SEA ==========================

#     ("SEA", "DTD"): [
#         ("Opened",          "Opened",                      None,         False),
#         ("Carrier Booking", "Booked",                      None,         False),
#         ("Loaded",          "Loaded and delivered to port", None,         False),
#         ("ATD Custom",      "Sailed",                      "etd",        True),
#         ("ATA Custom",      "Arrived",                     "eta",        True),
#         # ("Gate Out",        "Discharged",                  "arrived",    True),
#         ("Discharged", "Discharged", "arrived", True),
#         ("Gate In Rail",    "Loaded on Rail",              None,         False),
#         ("ATA Rail",        "Arrived at Rail",             None,         False),
#         ("Delivered",       "Delivered",                   "eta_buffer", True),
#     ],

#     ("SEA", "DTP"): [
#         ("Opened",          "Opened",                      None,         False),
#         ("Carrier Booking", "Booked",                      None,         False),
#         ("Loaded",          "Loaded and delivered to port", None,         False),
#         ("ATD Custom",      "Sailed",                      "etd",        True),
#         ("ATA Custom",      "Arrived",                     "eta",        True),
#         # ("Gate Out",        "Discharged",                  "arrived",    True),
#         ("Discharged", "Discharged", "arrived", True),
#         ("Gate In Rail",    "Loaded on Rail",              None,         False),
#         ("ATA Rail",        "Arrived at Rail",             None,         False),
#     ],

#     ("SEA", "PTD"): [
#         ("Opened",          "Opened",                      None,         False),
#         ("Carrier Booking", "Booked",                      None,         False),
#         ("Loaded",          "Loaded and delivered to port", None,         False),
#         ("ATD Custom",      "Sailed",                      "etd",        True),
#         ("ATA Custom",      "Arrived",                     "eta",        True),
#         # ("Gate Out",        "Discharged",                  "arrived",    True),
#         ("Discharged", "Discharged", "arrived", True),
#         ("Gate In Rail",    "Loaded on Rail",              None,         False),
#         ("ATA Rail",        "Arrived at Rail",             None,         False),
#         ("Delivered",       "Delivered",                   "eta_buffer", True),
#     ],

#     ("SEA", "PTP"): [
#         ("Opened",          "Opened",                      None,         False),
#         ("Carrier Booking", "Booked",                      None,         False),
#         ("Loaded",          "Loaded and delivered to port", None,         False),
#         ("ATD Custom",      "Sailed",                      "etd",        True),
#         ("ATA Custom",      "Arrived",                     "eta",        True),
#         # ("Gate Out",        "Discharged",                  "arrived",    True),
#         ("Discharged", "Discharged", "arrived", True),
#         ("Gate In Rail",    "Loaded on Rail",              None,         False),
#         ("ATA Rail",        "Arrived at Rail",             None,         False),
#         ("Delivered",       "Delivered",                   "eta_buffer", True),
#     ],

#     # ========================== AIR ==========================

#     ("AIR", "DTD"): [
#         ("Opened",          "Opened",                         None,         False),
#         ("Carrier Booking", "Booked",                         None,         False),
#         ("Picked",          "Picked up",                      None,         False),
#         ("Gate In",         "Delivered to airline",            None,         False),
#         ("ATD Custom",      "Departed",                       "etd",        True),
#         ("ATA Transit",     "Arrival at transit point",       None,         False),
#         ("ATD Transit",     "Departure from transit point",   None,         False),
#         ("ATA Custom",      "Arrival at final destination",   "eta",        True),
#         ("Delivered",       "Delivered",                      "eta_buffer", True),
#     ],

#     ("AIR", "DTP"): [
#         ("Opened",          "Opened",                         None,         False),
#         ("Carrier Booking", "Booked",                         None,         False),
#         ("Picked",          "Picked up",                      None,         False),
#         ("Gate In",         "Delivered to airline",            None,         False),
#         ("ATD Custom",      "Departed",                       "etd",        True),
#         ("ATA Transit",     "Arrival at transit point",       None,         False),
#         ("ATD Transit",     "Departure from transit point",   None,         False),
#         ("ATA Custom",      "Arrival at final destination",   "eta",        True),
#     ],

#     ("AIR", "PTD"): [
#         ("Opened",          "Opened",                         None,         False),
#         ("Carrier Booking", "Booked",                         None,         False),
#         ("Gate In",         "Delivered to airline",            None,         False),
#         ("ATD Custom",      "Departed",                       "etd",        True),
#         ("ATA Transit",     "Arrival at transit point",       None,         False),
#         ("ATD Transit",     "Departure from transit point",   None,         False),
#         ("ATA Custom",      "Arrival at final destination",   "eta",        True),
#         ("Delivered",       "Delivered",                      "eta_buffer", True),
#     ],

#     ("AIR", "PTP"): [
#         ("Opened",          "Opened",                         None,         False),
#         ("Carrier Booking", "Booked",                         None,         False),
#         ("Gate In",         "Delivered to airline",            None,         False),
#         ("ATD Custom",      "Departed",                       "etd",        True),
#         ("ATA Transit",     "Arrival at transit point",       None,         False),
#         ("ATD Transit",     "Departure from transit point",   None,         False),
#         ("ATA Custom",      "Arrival at final destination",   "eta",        True),
#     ],
# }


# # ---------------------------------------------------------------------------
# # Planned-field map for build_milestones_reformed
# # ---------------------------------------------------------------------------

# PLANNED_FIELD_MAP: Dict[str, str] = {
#     "ATD Custom": "ETD Custom",
#     "ATA Custom": "ETA Custom",
#     "Picked":     "Pick Date",
#     "Gate In":    "Gate In",
#     "Delivered":  "Delivery",
#     "Loaded":     "Load Date",
#     "Discharged": "Discharge Date",
#     "Gate In Rail": "Gate In Rail",
#     "ATA Rail":   "ETA Rail",
# }


# # ---------------------------------------------------------------------------
# # Internal helpers
# # ---------------------------------------------------------------------------

# def _resolve_planned(
#     source: Optional[str],
#     dates: Dict[str, Optional[str]],
#     actuals: Dict[str, Optional[str]],
#     buffer_days: int,
# ) -> Optional[str]:
#     """Map a planned_source key to a concrete planned-date string."""
#     if source is None:
#         return None
#     if source == "etd":
#         return dates.get("currentETD")
#     if source == "eta":
#         return dates.get("currentETA")
#     if source == "arrived":
#         return actuals.get("ATA Custom")
#     if source == "eta_buffer":
#         eta = dates.get("currentETA")
#         return _planned_from_eta(eta, buffer_days)
#     return None


# # ---------------------------------------------------------------------------
# # Core builder
# # ---------------------------------------------------------------------------

# def build_milestones(
#     transport_mode: str,
#     service_level: str,
#     actuals: Dict[str, Optional[str]],
#     dates: Dict[str, Optional[str]],
#     buffer_days: int = 4,
# ) -> List[Dict]:
#     """
#     Single data-driven milestone builder.

#     Parameters
#     ----------
#     transport_mode : "SEA" or "AIR"
#     service_level  : "DTD", "DTP", "PTD", or "PTP"
#     actuals        : {cf_key: actual_date_str} for completed milestones
#     dates          : {"currentETA": ..., "currentETD": ...}
#     buffer_days    : days to add to ETA for Delivered planned date

#     Returns
#     -------
#     List of milestone dicts, each with keys:
#         eventStatus, customField, actualDate, plannedDate, status, delay
#     """
#     key = ((transport_mode or "").upper(), (service_level or "").upper())
#     sequence = SEQUENCES.get(key)
#     if not sequence:
#         return []

#     result: List[Dict] = []

#     for cf_key, label, planned_source, calc_delay in sequence:
#         actual = actuals.get(cf_key)
#         planned = _resolve_planned(planned_source, dates, actuals, buffer_days)

#         delay = None
#         if calc_delay and actual and planned:
#             delay = calculate_delay_days(planned, actual)

#         status = "Completed" if actual else "Pending"

#         result.append({
#             "eventStatus": label,
#             "customField": cf_key,
#             "actualDate": actual,
#             "plannedDate": planned,
#             "status": status,
#             "delay": delay,
#         })

#     return result


# # ---------------------------------------------------------------------------
# # extract_milestones_for_mode
# # ---------------------------------------------------------------------------

# def extract_milestones_for_mode(transport_mode: str) -> Dict[str, str]:
#     """
#     Return milestone mapping based on transport mode.
#     Keys = custom field names (XML), values = eventStatus (user-facing).
#     """
#     mode = (transport_mode or "").upper()

#     if mode == "SEA":
#         return {
#             "Opened": "Opened",
#             "Carrier Booking": "Booked",
#             "ETD Custom": "ETD",
#             "ETA Custom": "ETA",
#             "Loaded": "Loaded and delivered to port",
#             "ATD Custom": "Sailed",
#             "ATA Custom": "Arrived",
#             # "Gate Out": "Discharged",
#             "Discharged": "Discharged",
#             "Gate In Rail": "Loaded on Rail",
#             "ATA Rail": "Arrived at Rail",
#             "Delivered": "Delivered",
#         }

#     if mode == "AIR":
#         return {
#             "Opened": "Opened",
#             "Carrier Booking": "Booked",
#             "ETD Custom": "ETD",
#             "ETA Custom": "ETA",
#             "Picked": "Picked up",
#             "Gate In": "Delivered To Airline (Gate In)",
#             "ATD Custom": "Departed",
#             "ATA Transit": "Arrival at transit point",
#             "ATD Transit": "Departure from transit point",
#             "ATA Custom": "Arrival at final destination",
#             "Delivered": "Delivered",
#         }

#     return {}


# # ---------------------------------------------------------------------------
# # extract_milestones_from_customized_fields
# # ---------------------------------------------------------------------------

# def extract_milestones_from_customized_fields(
#     customized_fields: List[Dict],
#     transport_mode: str,
# ) -> List[Dict]:
#     """
#     Extract milestones for the given transport mode from raw customized fields.

#     Priority: (A) suffix = 2, (M) suffix = 1, no suffix = 0.
#     Higher priority overwrites lower.

#     Returns list of milestone dicts in canonical order.
#     """
#     milestone_map = extract_milestones_for_mode(transport_mode)
#     allowed_fields = list(milestone_map.keys())

#     # Allow 'Discharged' as an extra custom field
#     if "Discharged" not in allowed_fields:
#         allowed_fields.append("Discharged")

#     priority_map = {"A": 2, "M": 1, "": 0}
#     milestone_dict: Dict[str, Dict] = {}

#     for field in safe_list(customized_fields):
#         if not isinstance(field, dict):
#             continue
#         raw_key = safe_text(field.get("Key")) or ""
#         key = raw_key.split("(")[0].strip()
#         value = safe_text(field.get("Value")) or None

#         if key not in allowed_fields:
#             continue

#         # Extract suffix (A / M)
#         suffix = ""
#         if "(" in raw_key and ")" in raw_key:
#             suffix = raw_key.split("(")[-1].replace(")", "").strip().upper()

#         existing = milestone_dict.get(key)

#         # Replace only if higher or equal priority
#         if not existing or priority_map.get(suffix, 0) >= priority_map.get(existing.get("_suffix", ""), 0):
#             milestone_dict[key] = {
#                 "eventStatus": milestone_map.get(key, key),
#                 "customField": key,
#                 "actualDate": value,
#                 "plannedDate": None,
#                 "status": "Completed" if value else "Pending",
#                 "delay": None,
#                 "_suffix": suffix,
#             }

#     # Remove internal suffix key
#     for m in milestone_dict.values():
#         m.pop("_suffix", None)

#     # Build canonical order from milestone_map keys
#     milestones_list: List[Dict] = []
#     for cf in milestone_map.keys():
#         if cf in milestone_dict:
#             milestones_list.append(milestone_dict[cf])
#         else:
#             milestones_list.append({
#                 "eventStatus": milestone_map[cf],
#                 "customField": cf,
#                 "actualDate": None,
#                 "plannedDate": None,
#                 "status": "Pending",
#                 "delay": None,
#             })

#     # Append Discharged if present as an extra CF
#     if "Discharged" in milestone_dict:
#         milestones_list.append(milestone_dict["Discharged"])

#     return milestones_list


# # ---------------------------------------------------------------------------
# # derive_status
# # ---------------------------------------------------------------------------

# def derive_status(
#     milestones: List[Dict],
#     transport_mode: str,
#     service_level: str,
# ) -> Tuple[str, List[str]]:
#     """
#     Status rule:
#     If last milestone in defined sequence is completed -> "Delivered"
#     Else -> "Active"
#     """
#     key = ((transport_mode or "").upper(), (service_level or "").upper())
#     sequence = SEQUENCES.get(key, [])

#     if not sequence:
#         return "Active", ["Active"]

#     # Last milestone cf_key in the defined flow
#     last_cf_key = sequence[-1][0]

#     last_milestone = next(
#         (m for m in milestones if m.get("customField") == last_cf_key),
#         None,
#     )

#     if last_milestone and last_milestone.get("status") == "Completed":
#         return "Delivered", ["Delivered"]

#     return "Active", ["Active"]


# # ---------------------------------------------------------------------------
# # get_last_completed_event
# # ---------------------------------------------------------------------------

# def get_last_completed_event(
#     milestones: List[Dict],
#     transport_mode: str,
#     service_level: str,
# ) -> Tuple[Optional[int], Optional[str], Optional[str]]:
#     """
#     Walk the sequence in order and return info about the last completed event.

#     Returns (delay, actualDate, eventStatus) or (None, None, None).
#     """
#     key = ((transport_mode or "").upper(), (service_level or "").upper())
#     sequence = SEQUENCES.get(key, [])

#     if not sequence:
#         return None, None, None

#     milestone_lookup = {m.get("customField"): m for m in milestones}

#     last_completed = None
#     for cf_key, _, _, _ in sequence:
#         m = milestone_lookup.get(cf_key)
#         if m and m.get("status") == "Completed":
#             last_completed = m

#     if not last_completed:
#         return None, None, None

#     return (
#         last_completed.get("delay"),
#         last_completed.get("actualDate"),
#         last_completed.get("eventStatus"),
#     )


# # ---------------------------------------------------------------------------
# # extract_service_level_code
# # ---------------------------------------------------------------------------

# def extract_service_level_code(
#     shipment: Dict,
#     subshipment: Dict,  # noqa: ARG001 - kept for API consistency with existing callers
# ) -> Optional[str]:
#     """Extract service level code (DTD/DTP/PTD/PTP) from shipment XML dict."""
#     sub_col = shipment.get("SubShipmentCollection", {})
#     sub = sub_col.get("SubShipment")

#     if isinstance(sub, list):
#         sub = sub[0] if sub else {}

#     if isinstance(sub, dict):
#         sl = sub.get("ServiceLevel")
#         if isinstance(sl, dict):
#             code = safe_text(sl.get("Code"))
#             if code:
#                 return code.strip().upper()

#     return None


# # ---------------------------------------------------------------------------
# # build_milestones_reformed
# # ---------------------------------------------------------------------------

# def build_milestones_reformed(
#     transport_mode: str,
#     service_level: str,
#     customized_fields: List[Dict],
# ) -> List[Dict]:
#     """
#     Build milestones using actual/planned maps extracted from customized fields,
#     with PLANNED_FIELD_MAP for resolving planned dates from (M) fields.
#     """
#     transport_mode = (transport_mode or "").upper()
#     service_level = (service_level or "").upper()

#     if not transport_mode or not service_level:
#         return []

#     # ---------------------------------
#     # Extract planned & actual maps
#     # ---------------------------------
#     actual_map: Dict[str, str] = {}
#     planned_map: Dict[str, str] = {}

#     for field in safe_list(customized_fields):
#         if not isinstance(field, dict):
#             continue
#         key = safe_text(field.get("Key"))
#         value = safe_text(field.get("Value"))

#         if not key or not value:
#             continue

#         key = key.replace("( A )", "(A)").replace("( M )", "(M)").strip()

#         # ETD / ETA planned anchors
#         if key.endswith("(A)") and key.startswith("ETD Custom"):
#             planned_map["ETD Custom"] = value
#             continue

#         if key.endswith("(A)") and key.startswith("ETA Custom"):
#             planned_map["ETA Custom"] = value
#             continue

#         # Actual milestones
#         if key.endswith("(A)"):
#             clean = key.replace("(A)", "").strip()
#             actual_map[clean] = value
#             continue

#         # Manual / planned fields
#         if key.endswith("(M)"):
#             clean = key.replace("(M)", "").strip()

#             # AIR Picked is actual, not planned
#             if clean == "Picked":
#                 actual_map[clean] = value
#             else:
#                 clean = clean.replace("Est.", "").strip()
#                 planned_map[clean] = value

#     # ---------------------------------
#     # Build milestones from sequence
#     # ---------------------------------
#     sequence = SEQUENCES.get((transport_mode, service_level), [])
#     milestones: List[Dict] = []

#     for cf_key, label, _, _ in sequence:
#         actual = actual_map.get(cf_key)

#         # Get correct planned key via PLANNED_FIELD_MAP
#         planned_key = PLANNED_FIELD_MAP.get(cf_key, cf_key)
#         planned = planned_map.get(planned_key)

#         delay = None
#         if actual and planned:
#             delay = calculate_delay_days(planned, actual)

#         status = "Completed" if actual else "Pending"

#         milestones.append({
#             "eventStatus": label,
#             "customField": cf_key,
#             "plannedDate": planned,
#             "actualDate": actual,
#             "status": status,
#             "delay": delay,
#         })

#     return milestones



# New milestones without Service Level

"""
Final milestone builder (TransportMode-based, production-ready)
"""

import re
from typing import Dict, List, Optional, Tuple

from pipeline.helpers import (
    calculate_delay_days,
    _planned_from_eta,
    safe_text,
    safe_list,
)

# ---------------------------------------------------------------------------
# SEQUENCES (ONLY TRANSPORT MODE)
# ---------------------------------------------------------------------------

SEQUENCES: Dict[str, List[Tuple[str, str, Optional[str], bool]]] = {

    "AIR": [
        ("Opened",          "Opened", None, False),
        ("Carrier Booking", "Booked", None, False),
        ("Picked",          "Picked up", None, False),
        ("Gate In",         "Delivered to airline", None, False),
        ("ATD Custom",      "Departed", "etd", True),
        ("ATA Transit",     "Arrival at transit point", None, False),
        ("ATD Transit",     "Departure from transit point", None, False),
        ("ATA Custom",      "Arrival at final destination", "eta", True),
        ("Delivered",       "Delivered", "eta_buffer", True),
    ],

    "SEA": [
        ("Opened",          "Opened", None, False),
        ("Carrier Booking", "Booked", None, False),
        ("Loaded",          "Loaded and delivered to port", None, False),
        ("ATD Custom",      "Sailed", "etd", True),
        ("ATA Custom",      "Arrived", "eta", True),
        ("Discharged",      "Discharged", "arrived", True),
        ("Gate In Rail",    "Loaded on Rail", None, False),
        ("ATA Rail",        "Arrived at Rail", None, False),
        ("Delivered",       "Delivered", "eta_buffer", True),
    ],

    # SEA Export only. Selected when transport_mode == "SEA" and
    # tradeType == "Export" (see _resolve_sequence). SEA Import and
    # SEA Foreign To Foreign continue to use the "SEA" sequence above.
    "SEA_EXPORT": [
        ("Opened",       "Opened",         None,         False),
        ("Pick up Date", "Picked up",      None,         False),
        ("Gate In Rail", "Loaded on Rail", None,         False),
        ("Gate In Port", "Gate In Port",   None,         False),
        ("ATD Custom",   "Sailed",         "etd",        True),
        ("ATA Custom",   "Arrived",        "eta",        True),
        ("Delivered",    "Delivered",      "eta_buffer", True),
    ],
}

# ---------------------------------------------------------------------------
# PLANNED FIELD MAP
# ---------------------------------------------------------------------------

PLANNED_FIELD_MAP: Dict[str, str] = {
    "ATD Custom": "ETD Custom",
    "ATA Custom": "ETA Custom",
    "Picked":     "Pick Date",
    "Gate In":    "Gate In",
    "Delivered":  "Delivery",
    "Loaded":     "Loaded",
    "Discharged": "Discharged",
    "Gate In Rail": "Gate In Rail",
    "ATA Rail":   "ETA Rail",
}

# ---------------------------------------------------------------------------
# SEQUENCE RESOLVER (direction-aware)
# ---------------------------------------------------------------------------

def _resolve_sequence(transport_mode, trade_type):
    """
    Pick the milestone sequence for a shipment.

    SEA + tradeType "Export" -> the dedicated SEA_EXPORT sequence.
    Everything else (SEA Import, SEA Foreign To Foreign, AIR) keeps using
    the existing per-transport-mode sequence, unchanged.
    """
    mode = (transport_mode or "").upper()
    tt = (trade_type or "").strip().lower()

    if mode == "SEA" and tt == "export":
        return SEQUENCES.get("SEA_EXPORT", [])

    return SEQUENCES.get(mode, [])


def _is_sea_export(transport_mode, trade_type):
    return (transport_mode or "").upper() == "SEA" and \
        (trade_type or "").strip().lower() == "export"


# ---------------------------------------------------------------------------
# HELPER
# ---------------------------------------------------------------------------

def _resolve_planned(source, dates, actuals, buffer_days):
    if source is None:
        return None
    if source == "etd":
        return dates.get("currentETD")
    if source == "eta":
        return dates.get("currentETA")
    if source == "arrived":
        return actuals.get("ATA Custom")
    if source == "eta_buffer":
        eta = dates.get("currentETA")
        return _planned_from_eta(eta, buffer_days)
    return None

# ---------------------------------------------------------------------------
# CORE BUILDER
# ---------------------------------------------------------------------------

def build_milestones(transport_mode, service_level, actuals, dates, buffer_days=4, trade_type=None):
    mode = (transport_mode or "").upper()
    sequence = _resolve_sequence(mode, trade_type)

    if not sequence:
        return []

    result = []

    for cf_key, label, planned_source, calc_delay in sequence:
        actual = actuals.get(cf_key)
        planned = _resolve_planned(planned_source, dates, actuals, buffer_days)

        delay = calculate_delay_days(planned, actual) if calc_delay and actual and planned else None

        result.append({
            "eventStatus": label,
            "customField": cf_key,
            "actualDate": actual,
            "plannedDate": planned,
            "status": "Completed" if actual else "Pending",
            "delay": delay,
        })

    return result

# ---------------------------------------------------------------------------
# STATUS
# ---------------------------------------------------------------------------

def derive_status(milestones, transport_mode, service_level, trade_type=None):
    mode = (transport_mode or "").upper()
    sequence = _resolve_sequence(mode, trade_type)

    if not sequence:
        return "Active", ["Active"]

    last_cf = sequence[-1][0]

    last = next((m for m in milestones if m["customField"] == last_cf), None)

    if last and last["status"] == "Completed":
        return "Delivered", ["Delivered"]

    return "Active", ["Active"]

# ---------------------------------------------------------------------------
# LAST COMPLETED
# ---------------------------------------------------------------------------

def get_last_completed_event(milestones, transport_mode, service_level, trade_type=None):
    mode = (transport_mode or "").upper()
    sequence = _resolve_sequence(mode, trade_type)

    if not sequence:
        return None, None, None

    lookup = {m["customField"]: m for m in milestones}

    last = None
    for cf_key, *_ in sequence:
        if lookup.get(cf_key) and lookup[cf_key]["status"] == "Completed":
            last = lookup[cf_key]

    if not last:
        return None, None, None

    return last["delay"], last["actualDate"], last["eventStatus"]


# ---------------- DELAY ARRIVAL / DEPARTURE ----------------

# ---------------------------------------------------------------------------
# MAIN REFORMED BUILDER
# ---------------------------------------------------------------------------

def build_milestones_reformed(transport_mode, service_level, customized_fields , job_opened_date=None, trade_type=None):

    transport_mode = (transport_mode or "").upper()

    if not transport_mode:
        return []

    is_export = _is_sea_export(transport_mode, trade_type)

    actual_map = {}
    planned_map = {}

    NORMALIZATION_MAP = {
        "Load Date": "Loaded",
        "Discharge Date": "Discharged",
        "GateIn": "Gate In",
    }

    for field in safe_list(customized_fields):
        key = safe_text(field.get("Key"))
        value = safe_text(field.get("Value"))

        if not key or not value:
            continue

        key = key.replace("( A )", "(A)").replace("( M )", "(M)").strip()

        # -----------------------------
        # PRIORITY FIELDS (A > M)
        # -----------------------------
        if key.startswith("ETD Custom"):
            if key.endswith("(A)"):
                planned_map["ETD Custom"] = value
            elif key.endswith("(M)") and "ETD Custom" not in planned_map:
                planned_map["ETD Custom"] = value
            continue

        if key.startswith("ETA Custom"):
            if key.endswith("(A)"):
                planned_map["ETA Custom"] = value
            elif key.endswith("(M)") and "ETA Custom" not in planned_map:
                planned_map["ETA Custom"] = value
            continue

        if key.startswith("Delivered"):
            if key.endswith("(A)"):
                actual_map["Delivered"] = value
            elif key.endswith("(M)") and "Delivered" not in planned_map:
                planned_map["Delivered"] = value
            continue

        # -----------------------------
        # ACTUAL
        # -----------------------------
        # if key.endswith("(A)"):
        #     clean = key.replace("(A)", "").strip()

        #     NORMALIZATION_MAP = {
        #         "GateIn": "Gate In",
        #         "Load Date": "Loaded",
        #         "Discharge Date": "Discharged",
        #     }

        #     clean = NORMALIZATION_MAP.get(clean, clean)

        #     actual_map[clean] = value
        #     continue
        
            # -----------------------------
            # ACTUAL
            # -----------------------------
        if key.endswith("(A)") or (key == "Opened" and "(" not in key):
            clean = key.replace("(A)", "").strip()

            clean = NORMALIZATION_MAP.get(clean, clean)

            existing = actual_map.get(clean)

            if clean == "Opened":
                # Priority: Opened(A) > Opened
                if key.endswith("(A)"):
                    actual_map[clean] = value
                elif not existing:
                    actual_map[clean] = value
            else:
                actual_map[clean] = value

            continue

        # -----------------------------
        # PLANNED
        # -----------------------------
        if key.endswith("(M)"):
            clean = key.replace("(M)", "").strip()

            if clean == "Picked":
                actual_map[clean] = value
            elif is_export and not clean.startswith("Est"):
                # SEA Export: (M) milestones WITHOUT an "Est." prefix are the
                # ACTUAL events (e.g. "Pick up Date(M)", "Gate In Rail(M)").
                # Their "Est. ..." counterparts fall through to PLANNED below.
                clean = NORMALIZATION_MAP.get(clean, clean)
                actual_map[clean] = value
            else:
                clean = re.sub(r"Est\.?", "", clean).strip()
                clean = NORMALIZATION_MAP.get(clean, clean)

                planned_map[clean] = value

    
     
  
    # -----------------------------
    # BUILD FINAL MILESTONES
    # -----------------------------
    
     
               # -----------------------------
        # FINAL FALLBACK FOR OPENED (Excel)
        # -----------------------------
    if not actual_map.get("Opened") and job_opened_date:
     actual_map["Opened"] = job_opened_date   
    
    sequence = _resolve_sequence(transport_mode, trade_type)
    milestones = []

    for cf_key, label, _, _ in sequence:
        actual = actual_map.get(cf_key)

        planned_key = PLANNED_FIELD_MAP.get(cf_key, cf_key)
        planned = planned_map.get(planned_key)

        delay = calculate_delay_days(planned, actual) if actual and planned else None

        milestones.append({
            "eventStatus": label,
            "customField": cf_key,
            "plannedDate": planned,
            "actualDate": actual,
            "status": "Completed" if actual else "Pending",
            "delay": delay,
        })

    return milestones



# ---------------------------------------------------------------------------
# BACKWARD COMPATIBILITY (FIXES YOUR IMPORT ERROR)
# ---------------------------------------------------------------------------

def extract_milestones_from_customized_fields(customized_fields, transport_mode , job_opened_date=None, trade_type=None):
    """
    Wrapper to keep old imports working.
    """
    return build_milestones_reformed(transport_mode, None, customized_fields , job_opened_date, trade_type)