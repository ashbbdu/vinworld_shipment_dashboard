from pipeline.cargowise import build_shipment_xml, build_documents_xml, RateLimiter
import time

def test_build_shipment_xml_contains_id():
    xml = build_shipment_xml("S00012345", "INJ", "GWS", "TR2")
    assert "S00012345" in xml
    assert "<Code>INJ</Code>" in xml
    assert "<EnterpriseID>GWS</EnterpriseID>" in xml
    assert "<ServerID>TR2</ServerID>" in xml
    assert "GWSTRVWR" not in xml

def test_build_shipment_xml_custom_company():
    xml = build_shipment_xml("S001", "CUSTOM", "ENT1", "SRV1")
    assert "<Code>CUSTOM</Code>" in xml
    assert "<EnterpriseID>ENT1</EnterpriseID>" in xml
    assert "<ServerID>SRV1</ServerID>" in xml

def test_build_documents_xml_contains_id():
    xml = build_documents_xml("S00012345", "VWT", "GWSTRVWR", "GWS", "TR2")
    assert "S00012345" in xml
    assert "<Code>VWT</Code>" in xml
    assert "<DataProvider>GWSTRVWR</DataProvider>" in xml

def test_build_documents_xml_custom_provider():
    xml = build_documents_xml("S001", "MYCORP", "MYPROV", "ENT2", "SRV2")
    assert "<Code>MYCORP</Code>" in xml
    assert "<DataProvider>MYPROV</DataProvider>" in xml
    assert "<EnterpriseID>ENT2</EnterpriseID>" in xml

def test_build_shipment_xml_type():
    xml = build_shipment_xml("TEST", "INJ", "GWS", "TR2")
    assert "<Type>ForwardingShipment</Type>" in xml

def test_rate_limiter_allows_within_limit():
    rl = RateLimiter(max_per_second=100)
    start = time.time()
    for _ in range(5):
        rl.acquire()
    elapsed = time.time() - start
    assert elapsed < 1.0  # Should be near-instant

def test_rate_limiter_throttles():
    rl = RateLimiter(max_per_second=10)
    start = time.time()
    for _ in range(12):
        rl.acquire()
    elapsed = time.time() - start
    assert elapsed >= 0.1  # Should have waited
