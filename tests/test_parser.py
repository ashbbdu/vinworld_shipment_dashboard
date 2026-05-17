"""Tests for pipeline.parser — XML field extraction from shipment dicts."""

import json
import pytest

from pipeline.parser import (
    parse_shipment,
    _extract_subshipment,
    _extract_ids,
    _extract_ports,
    _extract_parties,
    _extract_containers,
    _extract_carrier,
    _extract_transport,
    _extract_dates,
    _extract_order_refs,
    _extract_misc,
)

SAMPLE_SHIPMENT = {
    "TransportMode": {"Code": "SEA"},
    "WayBillNumber": "HBL12345",
    "WayBillType": {"Code": "HWB", "Description": "House Waybill"},
    "BookingConfirmationReference": "BK999",
    "PortOfOrigin": {"Name": "Dubai", "Code": "AEDXB"},
    "PortOfDestination": {"Name": "Houston", "Code": "USHOU"},
    "SubShipmentCollection": {
        "SubShipment": {
            "ServiceLevel": {"Code": "DTD"},
            "TransportMode": {"Code": "SEA"},
        }
    },
    "ContainerCollection": {
        "Container": [
            {
                "ContainerNumber": "ABCU1234567",
                "ContainerType": {"Code": "40HC"},
                "Seal": "SEAL1",
            }
        ]
    },
    "OrganizationAddressCollection": {
        "OrganizationAddress": [
            {
                "AddressType": "ConsigneeDocumentaryAddress",
                "CompanyName": "Test Consignee",
                "OrganizationCode": "CON01",
            },
            {
                "AddressType": "ConsignorDocumentaryAddress",
                "CompanyName": "Test Shipper",
                "OrganizationCode": "SHP01",
            },
        ]
    },
    "TransportLegCollection": {
        "TransportLeg": {
            "Carrier": {
                "CompanyName": "Maersk",
                "RegistrationNumberCollection": {
                    "RegistrationNumber": {
                        "Type": {"Code": "CCC"},
                        "Value": "MAEU",
                    }
                },
            },
        }
    },
    "VoyageFlightNo": "V123",
    "Vessel": {"Name": "Ever Given"},
    "IsRailMove": "false",
    "TotalWeight": "5000",
    "WeightUnit": {"Code": "KG"},
}


# ---- _extract_subshipment ----


def test_extract_subshipment():
    sub = _extract_subshipment(SAMPLE_SHIPMENT)
    assert sub.get("ServiceLevel", {}).get("Code") == "DTD"


def test_extract_subshipment_list():
    ship = {
        "SubShipmentCollection": {
            "SubShipment": [
                {"ServiceLevel": {"Code": "PTD"}},
                {"ServiceLevel": {"Code": "DTD"}},
            ]
        }
    }
    sub = _extract_subshipment(ship)
    assert sub["ServiceLevel"]["Code"] == "PTD"  # takes first


def test_extract_subshipment_missing():
    sub = _extract_subshipment({})
    assert sub == {}


def test_extract_subshipment_direct():
    """SubShipment directly on shipment (no Collection wrapper)."""
    ship = {"SubShipment": {"ServiceLevel": {"Code": "PTP"}}}
    sub = _extract_subshipment(ship)
    assert sub["ServiceLevel"]["Code"] == "PTP"


# ---- _extract_ids ----


def test_extract_ids_sea():
    sub = _extract_subshipment(SAMPLE_SHIPMENT)
    result = _extract_ids(SAMPLE_SHIPMENT, sub, "SEA")
    assert result["JS_HouseBill"] == "HBL12345"
    assert result["JS_BookingReference"] == "BK999"


def test_extract_ids_air():
    air_ship = dict(SAMPLE_SHIPMENT)
    air_ship["TransportMode"] = {"Code": "AIR"}
    sub = _extract_subshipment(air_ship)
    result = _extract_ids(air_ship, sub, "AIR")
    assert result["JS_BookingReference"] == "HBL12345"  # AIR uses WayBillNumber


def test_extract_ids_master_bill():
    ship = dict(SAMPLE_SHIPMENT)
    ship["WayBillType"] = {"Code": "MWB", "Description": "Master Waybill"}
    sub = _extract_subshipment(ship)
    result = _extract_ids(ship, sub, "SEA")
    assert result["masterBillNumber"] == "HBL12345"


# ---- _extract_ports ----


def test_extract_ports_import():
    sub = _extract_subshipment(SAMPLE_SHIPMENT)
    result = _extract_ports(SAMPLE_SHIPMENT, sub)
    assert "Dubai" in result["JS_RL_NKOrigin"]
    assert "Houston" in result["JS_RL_NKDestination"]
    assert result["tradeType"] == "Import"  # US destination


def test_extract_ports_export():
    ship = dict(SAMPLE_SHIPMENT)
    ship["PortOfOrigin"] = {"Name": "New York", "Code": "USNYC"}
    ship["PortOfDestination"] = {"Name": "Dubai", "Code": "AEDXB"}
    sub = _extract_subshipment(ship)
    result = _extract_ports(ship, sub)
    assert result["tradeType"] == "Export"  # US origin


def test_extract_ports_cross_trade():
    ship = dict(SAMPLE_SHIPMENT)
    ship["PortOfOrigin"] = {"Name": "Dubai", "Code": "AEDXB"}
    ship["PortOfDestination"] = {"Name": "Shanghai", "Code": "CNSHA"}
    sub = _extract_subshipment(ship)
    result = _extract_ports(ship, sub)
    assert result["tradeType"] == "CrossTrade"


def test_extract_ports_none():
    result = _extract_ports({}, {})
    assert result["tradeType"] is None


# ---- _extract_parties ----


def test_extract_parties():
    sub = _extract_subshipment(SAMPLE_SHIPMENT)
    result = _extract_parties(SAMPLE_SHIPMENT, sub)
    assert result["consignee"] == "Test Consignee"
    assert result["consignee_id"] == "CON01"
    assert result["shipper_id"] == "SHP01"


def test_extract_parties_fallback_consignee():
    ship = {"Consignee": "Fallback Consignee"}
    result = _extract_parties(ship, {})
    assert result["consignee"] == "Fallback Consignee"


def test_extract_parties_company_code():
    sub = _extract_subshipment(SAMPLE_SHIPMENT)
    result = _extract_parties(SAMPLE_SHIPMENT, sub)
    # company_code comes from first org address OrganizationCode
    assert result["company_code"] is not None


# ---- _extract_containers ----


def test_extract_containers():
    sub = _extract_subshipment(SAMPLE_SHIPMENT)
    result = _extract_containers(SAMPLE_SHIPMENT, sub, "S001")
    assert result["container_count"] == "1"
    assert "ABCU1234567" in result["container_numbers"]
    assert result["RC_Code"] == "40HC"
    assert result["JC_SealNum"] == "SEAL1"


def test_extract_containers_jc_always_none():
    sub = _extract_subshipment(SAMPLE_SHIPMENT)
    result = _extract_containers(SAMPLE_SHIPMENT, sub, "S001")
    assert result["JC_ContainerNum"] is None


def test_extract_containers_empty():
    result = _extract_containers({}, {}, "S001")
    assert result["container_count"] is None
    assert result["container_numbers"] is None
    assert result["JC_ContainerNum"] is None


def test_extract_containers_dimensions_sea_with_containers():
    sub = _extract_subshipment(SAMPLE_SHIPMENT)
    result = _extract_containers(SAMPLE_SHIPMENT, sub, "S001", transport_mode="SEA")
    assert result["unit_length"] == "FT"
    assert result["unit_width"] == "FT"
    assert result["unit_height"] == "FT"


def test_extract_containers_dimensions_sea_no_containers():
    result = _extract_containers({}, {}, "S001", transport_mode="SEA")
    assert result["unit_length"] == "CM"


def test_extract_containers_dimensions_air():
    result = _extract_containers({}, {}, "S001", transport_mode="AIR")
    assert result["unit_length"] is None


# ---- _extract_carrier ----


def test_extract_carrier():
    sub = _extract_subshipment(SAMPLE_SHIPMENT)
    result = _extract_carrier(SAMPLE_SHIPMENT, sub)
    assert result["carrier"] == "Maersk"
    assert result["scac_code"] == "MAEU"
    assert result["steamshipLine"] == "Maersk"


def test_extract_carrier_scac_fallback_org_address():
    """SCAC fallback: OrganizationAddress with shippingline type and CCC reg."""
    ship = {
        "TransportLegCollection": {"TransportLeg": {"Carrier": {"CompanyName": "TestCarrier"}}},
        "OrganizationAddressCollection": {
            "OrganizationAddress": [
                {
                    "AddressType": "ShippingLineAddress",
                    "RegistrationNumberCollection": {
                        "RegistrationNumber": {
                            "Type": {"Code": "CCC"},
                            "Value": "TSLA",
                        }
                    },
                }
            ]
        },
    }
    result = _extract_carrier(ship, {})
    assert result["scac_code"] == "TSLA"


def test_extract_carrier_scac_fallback_org_code():
    """SCAC fallback level 3: OrganizationCode 3-5 chars from carrier/shippingline address."""
    ship = {
        "TransportLegCollection": {"TransportLeg": {"Carrier": {"CompanyName": "TestCarrier"}}},
        "OrganizationAddressCollection": {
            "OrganizationAddress": [
                {
                    "AddressType": "CarrierAddress",
                    "OrganizationCode": "HAPG",
                }
            ]
        },
    }
    result = _extract_carrier(ship, {})
    assert result["scac_code"] == "HAPG"


# ---- _extract_transport ----


def test_extract_transport():
    sub = _extract_subshipment(SAMPLE_SHIPMENT)
    result = _extract_transport(SAMPLE_SHIPMENT, sub)
    assert result["JS_TransportMode"] == "SEA"
    assert result["voyageNumber"] == "V123"
    assert result["isRailMove"] == "false"


def test_extract_transport_vessel():
    sub = _extract_subshipment(SAMPLE_SHIPMENT)
    result = _extract_transport(SAMPLE_SHIPMENT, sub)
    assert result["vessel"] is not None
    # vessel is dump_json of the Vessel dict
    parsed = json.loads(result["vessel"])
    assert parsed["Name"] == "Ever Given"


def test_extract_transport_flight_vessel():
    sub = _extract_subshipment(SAMPLE_SHIPMENT)
    result = _extract_transport(SAMPLE_SHIPMENT, sub)
    assert result["flight_vessel"] == "V123"


# ---- _extract_order_refs ----


def test_extract_order_refs():
    ship = {
        "LocalProcessing": {
            "OrderNumberCollection": {
                "OrderNumber": [
                    {"OrderReference": "PO001"},
                    {"OrderReference": "PO002"},
                ]
            }
        }
    }
    result = _extract_order_refs(ship, {})
    assert result["order_ref"] == "PO001, PO002"


def test_extract_order_refs_fallback_to_shipment():
    sub = {"LocalProcessing": {"OrderNumberCollection": {"OrderNumber": []}}}
    ship = {
        "LocalProcessing": {
            "OrderNumberCollection": {
                "OrderNumber": {"OrderReference": "PO999"}
            }
        }
    }
    result = _extract_order_refs(ship, sub)
    assert result["order_ref"] == "PO999"


def test_extract_order_refs_none():
    result = _extract_order_refs({}, {})
    assert result["order_ref"] is None


# ---- _extract_dates ----


def test_extract_dates_from_customized_fields():
    ship = dict(SAMPLE_SHIPMENT)
    sub = {
        "CustomizedFieldCollection": {
            "CustomizedField": [
                {"Key": "ETA Custom(A)", "Value": "2024-03-20T00:00:00Z"},
                {"Key": "ETD Custom(A)", "Value": "2024-03-01T00:00:00Z"},
                {"Key": "ATA Custom(A)", "Value": "2024-03-22T00:00:00Z"},
            ]
        }
    }
    result = _extract_dates(ship, sub)
    assert result["eta_custom"] == "2024-03-20T00:00:00Z"
    assert result["etd_custom"] == "2024-03-01T00:00:00Z"
    assert result["actual_arrival_raw"] == "2024-03-22T00:00:00Z"


def test_extract_dates_atd_custom():
    sub = {
        "CustomizedFieldCollection": {
            "CustomizedField": [
                {"Key": "ATD Custom(A)", "Value": "2024-03-05T12:00:00Z"},
            ]
        }
    }
    result = _extract_dates({}, sub)
    assert result["actual_departure_raw"] == "2024-03-05T12:00:00Z"


def test_extract_dates_normalize_spacing():
    """Keys with spaces like 'ETA Custom( A )' should be normalized."""
    sub = {
        "CustomizedFieldCollection": {
            "CustomizedField": [
                {"Key": "ETA Custom( A )", "Value": "2024-06-01T00:00:00Z"},
            ]
        }
    }
    result = _extract_dates({}, sub)
    assert result["eta_custom"] == "2024-06-01T00:00:00Z"


def test_extract_dates_milestone_fallbacks():
    ship = {
        "MilestoneCollection": {
            "Milestone": [
                {
                    "Description": "Departure from First Load Port",
                    "ActualDate": "2024-01-10T00:00:00Z",
                },
                {
                    "Description": "Arrival at Final Discharge Port",
                    "EstimatedDate": "2024-01-20T00:00:00Z",
                },
                {
                    "Description": "Confirmed On Board",
                    "ActualDate": "2024-01-11T00:00:00Z",
                },
                {
                    "Description": "Discharged",
                    "ActualDate": "2024-01-21T00:00:00Z",
                },
                {
                    "Description": "Empty Returned",
                    "ActualDate": "2024-01-25T00:00:00Z",
                },
            ]
        }
    }
    result = _extract_dates(ship, {})
    assert result["dep_date"] == "2024-01-10T00:00:00Z"
    assert result["arrival_date"] == "2024-01-20T00:00:00Z"
    assert result["confirmedOnBoardDate"] == "2024-01-11T00:00:00Z"
    assert result["dischargedDate"] == "2024-01-21T00:00:00Z"
    assert result["emptyReturnedDate"] == "2024-01-25T00:00:00Z"


def test_extract_dates_empty_string_becomes_none():
    sub = {
        "CustomizedFieldCollection": {
            "CustomizedField": [
                {"Key": "ETA Custom(A)", "Value": ""},
            ]
        }
    }
    result = _extract_dates({}, sub)
    assert result["eta_custom"] is None


# ---- _extract_misc ----


def test_extract_misc_goods_description():
    ship = {"GoodsDescription": "Electronics"}
    result = _extract_misc(ship, {})
    assert result["JS_GoodsDescription"] == "Electronics"


def test_extract_misc_inco():
    ship = {"ShipmentIncoTerm": {"Code": "FOB"}}
    result = _extract_misc(ship, {})
    assert result["JS_INCO"] == "FOB"


def test_extract_misc_status():
    ship = {"Status": "Active", "LatestStatus": "In Transit"}
    result = _extract_misc(ship, {})
    assert result["status"] == "Active"
    assert result["latestStatus"] == "In Transit"


def test_extract_misc_console_jspk():
    ship = {
        "DataContext": {
            "DataSourceCollection": {
                "DataSource": {
                    "Type": "ForwardingConsol",
                    "Key": "CONSOL123",
                }
            }
        }
    }
    result = _extract_misc(ship, {})
    assert result["console"] == "CONSOL123"
    assert result["JS_PK"] == "CONSOL123"


def test_extract_misc_volume_size():
    ship = {
        "TotalVolume": "12.5",
        "TotalVolumeUnit": {"Code": "CBM"},
    }
    result = _extract_misc(ship, {})
    assert result["actual_volume"] == "12.5"
    assert "12.5" in result["size"]
    assert "CBM" in result["size"]


# ---- parse_shipment (integration) ----


def test_parse_shipment_returns_flat_dict():
    result = parse_shipment("S001", SAMPLE_SHIPMENT, [])
    assert result["JS_UniqueConsignRef"] == "S001"
    assert result["JS_TransportMode"] == "SEA"
    assert result["carrier"] == "Maersk"
    assert result["tradeType"] == "Import"
    assert "documents" in result


def test_parse_shipment_has_timestamps():
    result = parse_shipment("S002", SAMPLE_SHIPMENT, [])
    assert result["timestamp"] is not None
    assert result["created_at"] is not None
    assert result["updated_at"] is not None


def test_parse_shipment_documents_json():
    docs = [{"name": "invoice.pdf", "url": "http://example.com/invoice.pdf"}]
    result = parse_shipment("S003", SAMPLE_SHIPMENT, docs)
    parsed_docs = json.loads(result["documents"])
    assert len(parsed_docs) == 1
    assert parsed_docs[0]["name"] == "invoice.pdf"


def test_parse_shipment_container_fields():
    result = parse_shipment("S004", SAMPLE_SHIPMENT, [])
    assert result["container_count"] == "1"
    assert "ABCU1234567" in result["container_numbers"]
    assert result["JC_ContainerNum"] is None
    assert result["scac_code"] == "MAEU"


def test_parse_shipment_ports():
    result = parse_shipment("S005", SAMPLE_SHIPMENT, [])
    assert "Dubai" in result["JS_RL_NKOrigin"]
    assert "Houston" in result["JS_RL_NKDestination"]


def test_parse_shipment_none_shipment():
    """Passing None as shipment should not crash."""
    result = parse_shipment("S006", None, [])
    assert result["JS_UniqueConsignRef"] == "S006"


def test_parse_shipment_empty_shipment():
    result = parse_shipment("S007", {}, [])
    assert result["JS_UniqueConsignRef"] == "S007"
    assert result["tradeType"] is None
