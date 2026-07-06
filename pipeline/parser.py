"""
Parser — XML field extraction from CargoWise shipment dicts.

Splits the monolithic parse_shipment_obj() from new_milestones5.py (lines 2725-3835)
into focused extractor functions that each return a partial dict.  parse_shipment()
merges them into one flat record matching the existing DB schema exactly.

NOTE: This module does NOT handle milestones, ETA/ETD snapshots, status derivation,
or delay calculation — those belong in the job-processing layer.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from pipeline.helpers import (
    safe_dict,
    safe_list,
    safe_text,
    get_value,
    first_non_null,
    format_port,
    format_address,
    dump_json,
)


# ---------------------------------------------------------------------------
# Sub-shipment extraction (lines 2728-2734)
# ---------------------------------------------------------------------------

def _extract_subshipment(shipment: Dict) -> Dict:
    """Return the canonical sub-shipment dict (first element if list)."""
    raw = (
        safe_dict(shipment).get("SubShipmentCollection", {}).get("SubShipment")
        or shipment.get("SubShipment")
        or {}
    )
    sub = safe_dict(raw)
    if isinstance(raw, list):
        sub = safe_dict(raw[0]) if raw else {}
    return sub


# ---------------------------------------------------------------------------
# Waybill / Booking / Consignment IDs (lines 2877-2903)
# ---------------------------------------------------------------------------

def _extract_ids(shipment: Dict, sub: Dict, transport_mode: str) -> Dict:
    """Extract JS_HouseBill, JS_BookingReference, masterBillNumber."""
    waybill_number = first_non_null(
        safe_text(sub.get("WayBillNumber")),
        get_value(shipment, ["WayBillNumber"]),
        get_value(sub, ["BillNumber"]),
    )
    # JS_HouseBill is always the waybill_number regardless of type
    JS_HouseBill = waybill_number

    waybill_code = get_value(
        shipment.get("WayBillType") or sub.get("WayBillType") or {},
        ["Code"],
    )
    masterBillNumber = (
        get_value(shipment, ["WayBillNumber"]) if waybill_code == "MWB" else None
    )

    if transport_mode == "AIR":
        JS_BookingReference = first_non_null(
            safe_text(shipment.get("WayBillNumber")),
            get_value(sub, ["WayBillNumber"]),
            None,
        )
    else:
        JS_BookingReference = first_non_null(
            safe_text(shipment.get("BookingConfirmationReference")),
            get_value(sub, ["BookingConfirmationReference"]),
            safe_text(shipment.get("CarrierBookingReference")),
            get_value(sub, ["CarrierBookingReference"]),
            safe_text(shipment.get("BookingReference")),
            get_value(sub, ["BookingReference"]),
        )

    return {
        "JS_HouseBill": JS_HouseBill,
        "JS_BookingReference": JS_BookingReference,
        "masterBillNumber": masterBillNumber,
    }


# ---------------------------------------------------------------------------
# Organization addresses / parties (lines 2908-2933)
# ---------------------------------------------------------------------------

# def _extract_parties(shipment: Dict, sub: Dict) -> Dict:
#     """Extract consignee, consignee_id, deliver_to, shipper, shipper_id, pickup_from, company_code."""
#     company_code = consignee_id = consignee = deliverto = pickupfrom = shipper_id = shipper = None

#     addr_collection = safe_list(
#         sub.get("OrganizationAddressCollection", {}).get("OrganizationAddress")
#         or shipment.get("OrganizationAddressCollection", {}).get("OrganizationAddress")
#     )

#     for addr in addr_collection:
#         addr_type = safe_text(addr.get("AddressType"))
#         if addr_type == "ConsigneeDocumentaryAddress":
#             company_code = first_non_null(company_code, safe_text(addr.get("OrganizationCode")))
#             consignee_id = first_non_null(consignee_id, safe_text(addr.get("OrganizationCode")))
#             consignee = first_non_null(consignee, safe_text(addr.get("CompanyName")))
#             deliverto = first_non_null(deliverto, format_address(addr))
#         if addr_type in [
#             "ConsignorDocumentaryAddress",
#             "SendersLocalClient",
#             "SendersDocumentaryAddress",
#         ]:
#             shipper_id = first_non_null(shipper_id, safe_text(addr.get("OrganizationCode")))
#             pickupfrom = first_non_null(pickupfrom, format_address(addr))
#             shipper = shipper or json.dumps(
#                 {
#                     "shipperid": shipper_id,
#                     "shippername": safe_text(addr.get("CompanyName")),
#                     "address": format_address(addr),
#                 }
#             )

#     consignee = consignee or safe_text(shipment.get("Consignee") or sub.get("Consignee"))
#     deliverto = deliverto or format_address(sub.get("DeliveryAddress") or shipment.get("DeliveryAddress"))

#     # company_code: full fallback chain (lines 3530-3548)
#     company_code = first_non_null(
#         company_code,
#         *[
#             safe_text(a.get("OrganizationCode"))
#             for a in safe_list(sub.get("OrganizationAddressCollection", {}).get("OrganizationAddress"))
#             if safe_text(a.get("OrganizationCode"))
#         ],
#         *[
#             safe_text(a.get("OrganizationCode"))
#             for a in safe_list(shipment.get("OrganizationAddressCollection", {}).get("OrganizationAddress"))
#             if safe_text(a.get("OrganizationCode"))
#         ],
#         get_value(shipment, ["DataContext", "Company", "Code"]),
#         safe_text(sub.get("OrganizationCode")),
#         safe_text(shipment.get("OrganizationCode")),
#         None,
#     )

#     return {
#         "consignee": consignee,
#         "consignee_id": consignee_id,
#         "deliver_to": deliverto,
#         "shipper": shipper,
#         "shipper_id": shipper_id,
#         "pickup_from": pickupfrom,
#         "company_code": company_code,
#     }

def _extract_parties(shipment: Dict, sub: Dict) -> Dict:
    """Extract consignee, consignee_id, deliver_to, shipper, shipper_id, pickup_from, company_code."""

    company_code = None
    consignee_id = consignee = deliverto = pickupfrom = shipper_id = shipper = None

    addr_collection = safe_list(
        sub.get("OrganizationAddressCollection", {}).get("OrganizationAddress")
        or shipment.get("OrganizationAddressCollection", {}).get("OrganizationAddress")
    )

    for addr in addr_collection:
        addr_type = safe_text(addr.get("AddressType"))

        # ✅ 1. Controlling Customer (MAIN SOURCE for company_code)
        if addr_type == "ControllingCustomer":
            company_code = first_non_null(
                company_code,
                safe_text(addr.get("OrganizationCode"))
            )

        # ✅ 2. Consignee
        # elif addr_type == "ConsigneeDocumentaryAddress":
        #     consignee_id = first_non_null(consignee_id, safe_text(addr.get("OrganizationCode")))
        #     consignee = first_non_null(consignee, safe_text(addr.get("CompanyName")))
        #     deliverto = first_non_null(deliverto, format_address(addr))

        elif addr_type == "ConsigneePickupDeliveryAddress":
            consignee_id = first_non_null(consignee_id, safe_text(addr.get("OrganizationCode")))
            consignee = first_non_null(consignee, safe_text(addr.get("CompanyName")))
            deliverto = first_non_null(deliverto, format_address(addr))
            
        # ✅ 3. Shipper
        elif addr_type in [
            "ConsignorDocumentaryAddress",
            "SendersLocalClient",
            "SendersDocumentaryAddress",
        ]:
            shipper_id = first_non_null(shipper_id, safe_text(addr.get("OrganizationCode")))
            pickupfrom = first_non_null(pickupfrom, format_address(addr))
            shipper = shipper or json.dumps(
                {
                    "shipperid": shipper_id,
                    "shippername": safe_text(addr.get("CompanyName")),
                    "address": format_address(addr),
                }
            )

    # ✅ Fallbacks (ONLY if missing)

    consignee = consignee or safe_text(
        shipment.get("Consignee") or sub.get("Consignee")
    )

    deliverto = deliverto or format_address(
        sub.get("DeliveryAddress") or shipment.get("DeliveryAddress")
    )

    # ✅ SAFE fallback for company_code (no random override)
    if not company_code:
        company_code = first_non_null(
            get_value(shipment, ["DataContext", "Company", "Code"]),
            safe_text(sub.get("OrganizationCode")),
            safe_text(shipment.get("OrganizationCode")),
            None,
        )

    return {
        "consignee": consignee,
        "consignee_id": consignee_id,
        "deliver_to": deliverto,
        "shipper": shipper,
        "shipper_id": shipper_id,
        "pickup_from": pickupfrom,
        "company_code": company_code,
    }

# ---------------------------------------------------------------------------
# Ports & Trade Type (lines 2938-2958)
# ---------------------------------------------------------------------------

def _extract_ports(shipment: Dict, sub: Dict) -> Dict:
    """Extract JS_RL_NKOrigin, JS_RL_NKDestination, tradeType + port detail fields."""
    JS_RL_NKOrigin = format_port(sub.get("PortOfOrigin") or shipment.get("PortOfOrigin"))
    JS_RL_NKDestination = format_port(sub.get("PortOfDestination") or shipment.get("PortOfDestination"))

    trade_type = None
    if JS_RL_NKOrigin or JS_RL_NKDestination:
        def extract_code(port):
            if port and "(" in port:
                code = port.split("(")[-1].rstrip(")")
                return code[:2].upper() if len(code) >= 2 else None
            return None

        origin_country = extract_code(JS_RL_NKOrigin)
        destination_country = extract_code(JS_RL_NKDestination)

        if origin_country == "US":
            trade_type = "Export"
        elif destination_country == "US":
            trade_type = "Import"
        else:
            # trade_type = "CrossTrade"
            trade_type = "Foreign To Foreign"

    return {
        "JS_RL_NKOrigin": JS_RL_NKOrigin,
        "JS_RL_NKDestination": JS_RL_NKDestination,
        "tradeType": trade_type,
        "portOfLoading": first_non_null(
            get_value(shipment.get("PortOfLoading") or sub.get("PortOfLoading") or {}, ["Name"]),
            None,
        ),
        "originPort": dump_json(first_non_null(sub.get("PortOfOrigin"), shipment.get("PortOfOrigin"))),
        "portOfDischarge": first_non_null(
            get_value(shipment.get("PortOfDischarge") or sub.get("PortOfDischarge") or {}, ["Name"]),
            None,
        ),
        "destinationPort": dump_json(first_non_null(sub.get("PortOfDestination"), shipment.get("PortOfDestination"))),
        "terminalAtPortOfDischarge": dump_json(
            first_non_null(shipment.get("TerminalAtPortOfDischarge"), sub.get("TerminalAtPortOfDischarge"))
        ),
        "terminalAtDestinationPort": dump_json(
            first_non_null(shipment.get("TerminalAtDestinationPort"), sub.get("TerminalAtDestinationPort"))
        ),
    }


# ---------------------------------------------------------------------------
# Containers (lines 2963-3016, 3700-3805)
# ---------------------------------------------------------------------------

def _extract_containers(
    shipment: Dict,
    sub: Dict,
    shipment_id: str,
    transport_mode: str = "",
) -> Dict:
    """Extract container_count, container_numbers, containerDetails, dimensions, etc."""
    containers = safe_list(
        safe_dict(
            sub.get("ContainerCollection") or shipment.get("ContainerCollection") or {}
        ).get("Container")
    )
    if isinstance(containers, dict):
        containers = [containers]

    # Build container details list (lines 2988-3006)
    container_details = []
    shipment_total_weight = get_value(shipment, ["TotalWeight"])
    shipment_weight_unit = get_value(shipment, ["WeightUnit", "Code"]) or "KG"

    for c in containers:
        c = safe_dict(c)
        container_details.append({
            "containerNumber": safe_text(c.get("ContainerNumber")),
            "shipmentNumber": shipment_id,
            "sealNumber": first_non_null(
                get_value(c, ["Seal"]),
                get_value(c, ["SealNumber"]),
            ),
            "containerType": get_value(c, ["ContainerType", "Code"]),
            "weight": (
                f"{shipment_total_weight} {shipment_weight_unit}"
                if shipment_total_weight
                else None
            ),
        })

    # Shipment-level container aggregation (lines 3704-3729)
    container_numbers = []
    container_types = []
    seal_numbers = []
    first_container = None

    for c in containers:
        c = safe_dict(c)
        num = safe_text(c.get("ContainerNumber"))
        if num:
            num = num.replace(" ", "").upper()
            container_numbers.append(num)
            if not first_container:
                first_container = c

        ctype = get_value(c, ["ContainerType", "Code"])
        if ctype:
            container_types.append(ctype)

        seal = first_non_null(
            get_value(c, ["Seal"]),
            get_value(c, ["SealNumber"]),
        )
        if seal:
            seal_numbers.append(seal)

    # Container-derived fields (lines 3739-3777)
    result: Dict[str, Any] = {}

    if first_container:
        result.update({
            "JC_ContainerNum": None,  # shipment-level -> always NULL
            "JC_SealNum": ",".join(set(seal_numbers)) if seal_numbers else None,
            "RC_Code": ",".join(set(container_types)) if container_types else None,
            "JL_Length": first_non_null(
                get_value(first_container, ["TotalLength"]),
                get_value(sub, ["TotalLength"]),
                get_value(shipment, ["TotalLength"]),
            ),
            "JL_Height": first_non_null(
                get_value(first_container, ["TotalHeight"]),
                get_value(sub, ["TotalHeight"]),
                get_value(shipment, ["TotalHeight"]),
            ),
            "JL_Width": first_non_null(
                get_value(first_container, ["TotalWidth"]),
                get_value(sub, ["TotalWidth"]),
                get_value(shipment, ["TotalWidth"]),
            ),
            "container_weight": first_non_null(
                f"{get_value(first_container, ['WeightCapacity'])} {get_value(first_container, ['WeightUnit', 'Code'])}".strip(),
                f"{get_value(sub, ['WeightCapacity'])} {get_value(sub, ['WeightUnit', 'Code'])}".strip(),
                None,
            ),
        })
    else:
        result.update({
            "JC_ContainerNum": None,
            "JC_SealNum": None,
            "RC_Code": None,
            "JL_Length": None,
            "JL_Height": None,
            "JL_Width": None,
            "container_weight": None,
        })

    # Dimension unit assignment (lines 3783-3797)
    if transport_mode == "SEA":
        dim_unit = "FT" if first_container else "CM"
    elif transport_mode == "AIR":
        dim_unit = None
    else:
        dim_unit = None

    result.update({
        "unit_length": dim_unit,
        "unit_width": dim_unit,
        "unit_height": dim_unit,
    })

    # Aggregates (lines 3802-3805) — these override earlier container_count/numbers
    result.update({
        "container_numbers": ",".join(container_numbers) if container_numbers else None,
        "container_count": str(len(container_numbers)) if container_numbers else None,
        "containerDetails": json.dumps(container_details),
        "equipmentType": first_non_null(
            get_value(containers[0] if containers else {}, ["ContainerType", "Code"]),
            get_value(sub, ["ContainerType", "Code"]),
        ),
    })

    return result


# ---------------------------------------------------------------------------
# Carrier / SCAC (lines 3021-3097)
# ---------------------------------------------------------------------------

def _extract_carrier(shipment: Dict, sub: Dict) -> Dict:
    """Extract carrier, steamshipLine, scac_code, carrier_code with 3-level SCAC fallback."""
    transport_leg_data = shipment.get("TransportLegCollection", {}).get("TransportLeg")
    if isinstance(transport_leg_data, list):
        first_leg = safe_dict(transport_leg_data[0]) if transport_leg_data else {}
    else:
        first_leg = safe_dict(transport_leg_data)
    transport_leg = safe_dict(first_leg)

    carrier_info = safe_dict(
        transport_leg.get("Carrier") or shipment.get("Carrier") or {}
    )
    carrier_from_leg = get_value(first_leg, ["Carrier", "CompanyName"])

    carrier = first_non_null(
        safe_text(carrier_info.get("CompanyName")),
        safe_text(shipment.get("Carrier")),
        safe_text(shipment.get("CarrierName")),
        safe_text(shipment.get("TransportLegCarrier")),
        safe_text(carrier_from_leg),
    )

    # --- SCAC 3-level fallback ---

    def _extract_scac_from_reg_list(reg_list):
        for reg in safe_list(reg_list):
            reg = safe_dict(reg)
            code = safe_text(get_value(reg, ["Type", "Code"])) or safe_text(reg.get("Code"))
            val = safe_text(reg.get("Value"))
            if code and code.strip().upper() == "CCC" and val:
                return val
        return None

    # Level 1: carrier_info RegistrationNumber
    scac_code = None
    reg_block = (
        safe_dict(carrier_info.get("RegistrationNumberCollection", {})).get("RegistrationNumber")
        or carrier_info.get("RegistrationNumber")
    )
    scac_code = _extract_scac_from_reg_list(reg_block)

    # Level 2: OrganizationAddress with shippingline/carrier type
    org_addrs = []
    if not scac_code:
        org_addrs = safe_list(
            safe_dict(shipment.get("OrganizationAddressCollection", {})).get("OrganizationAddress")
            or safe_dict(sub.get("OrganizationAddressCollection", {})).get("OrganizationAddress")
        )
        for addr in org_addrs:
            addr = safe_dict(addr)
            addr_type = safe_text(addr.get("AddressType", "")).lower()
            if "shippingline" in addr_type or "carrier" in addr_type:
                reg_block = safe_dict(addr.get("RegistrationNumberCollection", {})).get("RegistrationNumber")
                scac_code = _extract_scac_from_reg_list(reg_block)
                if scac_code:
                    break

    # Level 3: OrganizationCode 3-5 chars from carrier/shippingline address
    if not scac_code:
        # org_addrs may already be populated from level 2; if not, populate now
        if not org_addrs:
            org_addrs = safe_list(
                safe_dict(shipment.get("OrganizationAddressCollection", {})).get("OrganizationAddress")
                or safe_dict(sub.get("OrganizationAddressCollection", {})).get("OrganizationAddress")
            )
        for addr in org_addrs:
            addr = safe_dict(addr)
            addr_type = safe_text(addr.get("AddressType", "")).lower()
            if "shippingline" in addr_type or "carrier" in addr_type:
                possible_code = safe_text(addr.get("OrganizationCode"))
                if possible_code and len(possible_code.strip()) in [3, 4, 5]:
                    scac_code = possible_code.strip()
                    break

    steamshipLine = first_non_null(
        safe_text(carrier_info.get("CompanyName")),
        safe_text(shipment.get("CarrierName")),
        safe_text(shipment.get("Carrier")),
    )

    return {
        "carrier": carrier,
        "steamshipLine": steamshipLine,
        "scac_code": scac_code,
    }


# ---------------------------------------------------------------------------
# Transport mode / voyage / vessel (lines 3552-3574)
# ---------------------------------------------------------------------------

def _extract_transport(shipment: Dict, sub: Dict) -> Dict:
    """Extract JS_TransportMode, JS_PackingMode, voyageNumber, vessel, flight_vessel, isRailMove, JS_ScreeningStatus."""
    return {
        "JS_TransportMode": first_non_null(
            get_value(shipment, ["TransportMode", "Code"]),
            get_value(sub, ["TransportMode", "Code"]),
        ),
        "JS_PackingMode": first_non_null(
            get_value(shipment, ["ContainerMode", "Code"]),
            get_value(sub, ["ContainerMode", "Code"]),
        ),
        "JS_ScreeningStatus": first_non_null(
            get_value(shipment, ["ScreeningStatus", "Code"]),
            get_value(sub, ["ScreeningStatus", "Code"]),
        ),
        "JS_SystemLastEditTimeUtc": first_non_null(
            get_value(shipment, ["SystemLastEditTimeUtc"]),
            get_value(sub, ["SystemLastEditTimeUtc"]),
        ),
        "voyageNumber": first_non_null(
            safe_text(shipment.get("VoyageFlightNo")),
            safe_text(sub.get("VoyageFlightNo")),
        ),
        "vessel": dump_json(first_non_null(shipment.get("Vessel"), sub.get("Vessel"))),
        "flight_vessel": first_non_null(
            get_value(shipment, ["VesselName"]),
            get_value(sub, ["VesselName"]),
        ),
        # "flight_vessel": first_non_null(
        #     get_value(shipment, ["VoyageFlightNo"]),
        #     get_value(sub, ["VoyageFlightNo"]),
        # ),
        "isRailMove": safe_text(shipment.get("IsRailMove") or sub.get("IsRailMove")),
    }


# ---------------------------------------------------------------------------
# Order references (lines 3102-3127)
# ---------------------------------------------------------------------------

def _extract_order_refs(shipment: Dict, sub: Dict) -> Dict:
    """Extract order_ref from LocalProcessing.OrderNumberCollection."""
    order_ref_values = []

    local_proc = safe_dict(sub.get("LocalProcessing", {}))
    order_collection = safe_dict(local_proc.get("OrderNumberCollection", {}))
    order_numbers = safe_list(order_collection.get("OrderNumber"))

    for order in order_numbers:
        ref = safe_text(safe_dict(order).get("OrderReference"))
        if ref:
            order_ref_values.append(ref)

    if not order_ref_values:
        shipment_local_proc = safe_dict(shipment.get("LocalProcessing", {}))
        shipment_order_collection = safe_dict(shipment_local_proc.get("OrderNumberCollection", {}))
        shipment_order_numbers = safe_list(shipment_order_collection.get("OrderNumber"))
        for order in shipment_order_numbers:
            ref = safe_text(safe_dict(order).get("OrderReference"))
            if ref:
                order_ref_values.append(ref)

    return {
        "order_ref": ", ".join(order_ref_values) if order_ref_values else None,
    }


# ---------------------------------------------------------------------------
# Dates: CustomizedFields + MilestoneCollection fallbacks (lines 2753-2864, 3132-3260)
# ---------------------------------------------------------------------------

def _extract_dates(shipment: Dict, sub: Dict) -> Dict:
    """Extract eta_custom, etd_custom, actual_arrival/departure_raw, and milestone fallback dates."""

    # Gather customized fields from both levels
    customized_fields: List[Dict] = []
    for level in [shipment, sub]:
        cf = level.get("CustomizedFieldCollection", {}).get("CustomizedField")
        if cf:
            if isinstance(cf, list):
                customized_fields.extend(cf)
            elif isinstance(cf, dict):
                customized_fields.append(cf)

    # Extract from CustomizedFields (only (A) suffix)
    actual_departure_raw = None
    actual_arrival_raw = None
    eta_custom = None
    etd_custom = None

    for field in customized_fields:
        key = safe_text(field.get("Key"))
        value = safe_text(field.get("Value"))

        if not key or not value:
            continue

        # Normalize spacing like "ETA Custom( A )" -> "ETA Custom(A)"
        key = key.replace("( A )", "(A)").strip()

        if key == "ETA Custom(A)":
            eta_custom = value
            continue
        if key == "ETD Custom(A)":
            etd_custom = value
            continue
        if key == "ATA Custom(A)":
            actual_arrival_raw = value
            continue
        if key == "ATD Custom(A)":
            actual_departure_raw = value
            continue

    # Ensure empty strings become None
    if eta_custom == "":
        eta_custom = None
    if etd_custom == "":
        etd_custom = None
    if actual_arrival_raw == "":
        actual_arrival_raw = None
    if actual_departure_raw == "":
        actual_departure_raw = None

    # Milestone fallback dates (lines 3132-3260)
    milestones = safe_list(
        shipment.get("MilestoneCollection", {}).get("Milestone")
        or shipment.get("Milestone")
        or sub.get("MilestoneCollection", {}).get("Milestone")
        or []
    )

    dep_date = None
    arrival_date = None
    etaAtDestination = None
    etaAtTerminal = None
    confirmedOnBoardDate = None
    vesselArrivedDate = None
    dischargedDate = None
    emptyReturnedDate = None

    for ms in milestones:
        desc = safe_text(ms.get("Description")) or safe_text(ms.get("Type"))
        # if desc == "Departure from First Load Port":
        #     dep_date = dep_date or get_value(ms, ["ActualDate"]) or get_value(ms, ["EstimatedDate"])
        # elif desc == "Arrival at Final Discharge Port":
        #     arrival_date = arrival_date or get_value(ms, ["EstimatedDate"]) or get_value(ms, ["ActualDate"])
            # etaAtDestination = etaAtDestination or arrival_date
        if desc == "Arrival at Load Port Terminal":
            etaAtTerminal = etaAtTerminal or get_value(ms, ["EstimatedDate"]) or get_value(ms, ["ActualDate"])
        elif desc == "Confirmed On Board":
            confirmedOnBoardDate = confirmedOnBoardDate or get_value(ms, ["ActualDate"])
        elif desc == "Discharged":
            dischargedDate = dischargedDate or get_value(ms, ["ActualDate"])
        elif desc == "Empty Returned":
            emptyReturnedDate = emptyReturnedDate or get_value(ms, ["ActualDate"])

    return {
        "eta_custom": eta_custom,
        "etd_custom": etd_custom,
        "actual_arrival_raw": actual_arrival_raw,
        "actual_departure_raw": actual_departure_raw,
        "dep_date": dep_date,
        "arrival_date": arrival_date,
        "etaAtDestination": etaAtDestination,
        "etaAtTerminal": etaAtTerminal,
        "confirmedOnBoardDate": confirmedOnBoardDate,
        "vesselArrivedDate": vesselArrivedDate,
        "dischargedDate": dischargedDate,
        "emptyReturnedDate": emptyReturnedDate,
        "planned_departure": None,   # will be populated by job processor
        "planned_arrival": None, 
    }


# ---------------------------------------------------------------------------
# Misc fields (lines 3262-3696) — everything not covered by other extractors
# ---------------------------------------------------------------------------

def _extract_misc(shipment: Dict, sub: Dict) -> Dict:
    """Extract status, latestStatus, console/JS_PK, goods desc, inco, size, quantity, etc."""

    # DataSources / console / JS_PK (lines 3262-3272)
    datasources = safe_list(
        shipment.get("DataContext", {}).get("DataSourceCollection", {}).get("DataSource")
        or shipment.get("DataSourceCollection", {}).get("DataSource")
        or []
    )
    JSPK = None
    for ds in datasources:
        ds_type = safe_text(ds.get("Type"))
        if ds_type == "ForwardingConsol":
            JSPK = first_non_null(safe_text(ds.get("Key")), safe_text(ds.get("Reference"))) or JSPK

    return {
        "JS_GoodsDescription": first_non_null(
            get_value(sub, ["GoodsDescription"]),
            get_value(shipment, ["GoodsDescription"]),
        ),
        "JS_INCO": first_non_null(
            get_value(sub, ["ShipmentIncoTerm", "Code"]),
            get_value(shipment, ["ShipmentIncoTerm", "Code"]),
        ),
        "JS_F3_NKPackType": first_non_null(
            get_value(
                (safe_list(sub.get("PackingLineCollection", {}).get("PackingLine")) or [{}])[0],
                ["PackType", "Code"],
            ),
            get_value(
                (safe_list(shipment.get("PackingLineCollection", {}).get("PackingLine")) or [{}])[0],
                ["PackType", "Code"],
            ),
        ),
        "status": safe_text(shipment.get("Status") or sub.get("Status")),
        "latestStatus": first_non_null(
            safe_text(shipment.get("LatestStatus")),
            safe_text(sub.get("LatestStatus")),
            None,
        ),
        "console": JSPK,
        "JS_PK": JSPK,
        "open_track": dump_json(first_non_null(shipment.get("OpenTrack"), sub.get("OpenTrack"))),
        "currentLocation": dump_json(first_non_null(shipment.get("CurrentLocation"), sub.get("CurrentLocation"))),
        "lastKnownPosition": dump_json(first_non_null(shipment.get("LastKnownPosition"), sub.get("LastKnownPosition"))),
        "holds": dump_json(first_non_null(shipment.get("Holds"), sub.get("Holds"))),
        "history": dump_json(first_non_null(shipment.get("History"), sub.get("History"))),
        "size": first_non_null(
            f"{safe_text(sub.get('TotalVolume'))} {safe_text(get_value(sub, ['TotalVolumeUnit', 'Code']))}"
            if sub.get("TotalVolume") else None,
            f"{safe_text(shipment.get('TotalVolume'))} {safe_text(get_value(shipment, ['TotalVolumeUnit', 'Code']))}"
            if shipment.get("TotalVolume") else None,
            None,
        ),
        "quantity": first_non_null(get_value(sub, ["OuterPacks"]), get_value(shipment, ["OuterPacks"])),
        "actual_volume": first_non_null(get_value(shipment, ["TotalVolume"]), get_value(sub, ["TotalVolume"])),
        "JL_PackageCount": first_non_null(get_value(sub, ["OuterPacks"]), get_value(shipment, ["OuterPacks"])),
        "JL_Description": first_non_null(get_value(sub, ["GoodsDescription"]), get_value(shipment, ["GoodsDescription"])),
        "JL_ActualWeight": first_non_null(get_value(sub, ["TotalWeight"]), get_value(shipment, ["TotalWeight"])),
        "JL_ActualWeightUQ": first_non_null(get_value(sub, ["WeightUnit", "Code"]), get_value(shipment, ["WeightUnit", "Code"])),
        "JL_ActualVolume": first_non_null(get_value(sub, ["TotalVolume"]), get_value(shipment, ["TotalVolume"])),
        "JL_UnitOfDimension": first_non_null(get_value(sub, ["VolumeUnit", "Code"]), get_value(shipment, ["VolumeUnit", "Code"])),
        "location": first_non_null(safe_text(shipment.get("Location")), None),
    }


# ---------------------------------------------------------------------------
# Top-level: parse_shipment
# ---------------------------------------------------------------------------

def parse_shipment(
    shipment_id: str,
    shipment_dict: Any,
    documents: List,
) -> Dict:
    """
    Parse a CargoWise shipment dict into a flat record matching the DB schema.

    This is a pure extraction — no DB calls, no milestone building, no delay
    calculation.  It calls every _extract_* helper and merges the results.
    """
    shipment = safe_dict(shipment_dict)
    sub = _extract_subshipment(shipment)

    transport_mode = (
        get_value(shipment, ["TransportMode", "Code"])
        or get_value(sub, ["TransportMode", "Code"])
        or ""
    ).upper()

    # Call all extractors
    ids = _extract_ids(shipment, sub, transport_mode)
    parties = _extract_parties(shipment, sub)
    ports = _extract_ports(shipment, sub)
    containers = _extract_containers(shipment, sub, shipment_id, transport_mode=transport_mode)
    carrier = _extract_carrier(shipment, sub)
    transport = _extract_transport(shipment, sub)
    order_refs = _extract_order_refs(shipment, sub)
    dates = _extract_dates(shipment, sub)
    misc = _extract_misc(shipment, sub)

    now = datetime.now(timezone.utc).isoformat()

    # Merge into flat dict — order matches the original base dict in new_milestones5.py
    record: Dict[str, Any] = {}
    record.update(ids)
    record.update(parties)
    record.update(ports)
    record.update(containers)
    record.update(carrier)
    record.update(transport)
    record.update(order_refs)
    record.update(dates)
    record.update(misc)

    # Top-level fields always set by parse_shipment
    record["JS_UniqueConsignRef"] = shipment_id
    record["documents"] = dump_json(documents)
    record["timestamp"] = now
    record["created_at"] = now
    record["updated_at"] = now
    record["cargowise_error"] = None

    return record
