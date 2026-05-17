"""
CargoWise eAdaptor XML API client.

Extracted from new_milestones5.py — XML builders and HTTP transport
with rate limiting and thread-safe token-bucket throttling.
"""

import logging
import threading
import time

import requests
import xmltodict
from requests.auth import HTTPBasicAuth

from pipeline.helpers import safe_dict

logger = logging.getLogger("pipeline.cargowise")


# ------------------------------------------------------------------ #
# XML template builders (verbatim from new_milestones5.py)
# ------------------------------------------------------------------ #

def build_shipment_xml(shipment_id: str, company_code: str, enterprise_id: str, server_id: str) -> str:
    """Build UniversalShipmentRequest XML."""
    return f"""<UniversalShipmentRequest xmlns="http://www.cargowise.com/Schemas/Universal/2011/11" version="1.1">
    <ShipmentRequest>
        <DataContext>
            <DataTargetCollection>
                <DataTarget>
                    <Type>ForwardingShipment</Type>
                    <Key>{shipment_id}</Key>
                </DataTarget>
            </DataTargetCollection>
            <Company>
                <Code>{company_code}</Code>
            </Company>
            <EnterpriseID>{enterprise_id}</EnterpriseID>
            <ServerID>{server_id}</ServerID>
        </DataContext>
    </ShipmentRequest>
</UniversalShipmentRequest>""".strip()


def build_documents_xml(shipment_id: str, company_code: str, data_provider: str, enterprise_id: str, server_id: str) -> str:
    """Build UniversalDocumentRequest XML."""
    return f"""<UniversalDocumentRequest xmlns="http://www.cargowise.com/Schemas/Universal/2011/11" version="1.1">
    <DocumentRequest>
        <DataContext>
            <DataTargetCollection>
                <DataTarget>
                    <Type>ForwardingShipment</Type>
                    <Key>{shipment_id}</Key>
                </DataTarget>
            </DataTargetCollection>
            <Company>
                <Code>{company_code}</Code>
            </Company>
            <DataProvider>{data_provider}</DataProvider>
            <EnterpriseID>{enterprise_id}</EnterpriseID>
            <ServerID>{server_id}</ServerID>
        </DataContext>
        <ReturnDocumentDescriptionsOnly>true</ReturnDocumentDescriptionsOnly>
    </DocumentRequest>
</UniversalDocumentRequest>""".strip()


# ------------------------------------------------------------------ #
# Rate limiter
# ------------------------------------------------------------------ #

class RateLimiter:
    """Token bucket rate limiter, thread-safe."""

    def __init__(self, max_per_second: int):
        self._max = max_per_second
        self._tokens = float(max_per_second)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._max, self._tokens + elapsed * self._max)
            self._last = now
            if self._tokens < 1:
                wait = (1 - self._tokens) / self._max
                time.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1


# ------------------------------------------------------------------ #
# API client
# ------------------------------------------------------------------ #

class CargoWiseClient:
    """Thin HTTP client for the CargoWise eAdaptor XML API.

    Supports two auth modes (CW_AUTH_MODE):
    - "header": clientId/clientSecret/Origin in headers, no Basic Auth
    - "basic": HTTP Basic Auth with CW_USERNAME/CW_PASSWORD, Content-Type only header

    verify=False by default (matching legacy behaviour).
    """

    def __init__(self, settings):
        self._url = settings.CW_API_URL
        self._timeout = settings.CW_TIMEOUT
        self._verify = settings.CW_VERIFY_SSL
        self._auth_mode = settings.CW_AUTH_MODE
        self._rate_limiter = RateLimiter(settings.CW_RATE_LIMIT)

        if self._auth_mode == "basic":
            self._auth = HTTPBasicAuth(settings.CW_USERNAME, settings.CW_PASSWORD)
            self._headers = {"Content-Type": "application/xml"}
        else:
            # Header auth — clientId/clientSecret/Origin in headers
            self._auth = None
            self._headers = {
                "clientId": settings.CW_CLIENT_ID,
                "clientSecret": settings.CW_CLIENT_SECRET,
                "Origin": settings.CW_ORIGIN,
                "Content-Type": "application/xml",
            }
        # XML context variables
        self._shipment_company = settings.CW_SHIPMENT_COMPANY_CODE
        self._doc_company = settings.CW_DOCUMENT_COMPANY_CODE
        self._doc_provider = settings.CW_DOCUMENT_DATA_PROVIDER
        self._enterprise_id = settings.CW_ENTERPRISE_ID
        self._server_id = settings.CW_SERVER_ID

    def fetch_shipment(self, shipment_id: str) -> dict:
        """Fetch shipment data.  Returns parsed Shipment dict or raises."""
        xml = build_shipment_xml(shipment_id, self._shipment_company, self._enterprise_id, self._server_id)
        data = self._post(xml)
        # Navigate: UniversalResponse -> Data -> UniversalShipment -> Shipment
        ur = data.get("UniversalResponse") or {}
        ds = ur.get("Data") or {}
        us = ds.get("UniversalShipment") or {}
        shipment = safe_dict(us.get("Shipment"))
        if not shipment:
            raise ValueError(f"No Shipment block in response for {shipment_id}")
        return shipment

    def fetch_documents(self, shipment_id: str) -> list:
        """Fetch document metadata.  Returns list of document dicts.

        Never raises — returns empty list on failure (matches legacy behaviour).
        """
        xml = build_documents_xml(shipment_id, self._doc_company, self._doc_provider, self._enterprise_id, self._server_id)
        try:
            data = self._post(xml)
        except Exception as e:
            logger.warning("Document fetch failed for %s: %s", shipment_id, e)
            return []
        # Navigate: UniversalResponse -> Data -> UniversalEvent -> Event -> AttachedDocumentCollection
        doc_col = (
            (data.get("UniversalResponse") or {})
            .get("Data") or {}
        )
        doc_col = (
            doc_col.get("UniversalEvent") or {}
        ).get("Event") or {}
        doc_col = doc_col.get("AttachedDocumentCollection") or {}
        if not doc_col:
            return []
        docs = doc_col.get("AttachedDocument", [])
        if isinstance(docs, dict):
            docs = [docs]
        return [
            {
                "FileName": d.get("FileName"),
                "Type": d.get("Type", {}),
                "DocumentID": d.get("DocumentID"),
                "FileSizeInBytes": d.get("FileSizeInBytes"),
                "IsPublished": d.get("IsPublished"),
                "SaveDateUTC": d.get("SaveDateUTC"),
                "SavedBy": d.get("SavedBy", {}),
            }
            for d in docs
        ]
        
    # def warmup(self):
    #     """Send a lightweight request to wake up the eAdaptor server."""
    #     try:
    #         print("🔥 Warming up CargoWise server...")
    #         response = requests.get(self._url, headers=self._headers, timeout=30, verify=self._verify)
    #         print(f"🔥 Warmup response: {response.status_code}")
    #     except Exception as e:
    #         print(f"🔥 Warmup failed (expected): {e}")
    #     time.sleep(5) 
    
    def warmup(self, retries=5):
        """Send real shipment requests to wake up the eAdaptor server."""
        xml = build_shipment_xml("SSIVW0028930", self._shipment_company, self._enterprise_id, self._server_id)
        for i in range(retries):
            try:
                print(f"🔥 Warmup attempt {i+1}/{retries}...")
                response = requests.post(
                    self._url,
                    headers=self._headers,
                    data=xml,
                    timeout=30,
                    verify=self._verify,
                    auth=self._auth,
                )
                print(f"🔥 Warmup response: {response.status_code}")
                if response.status_code == 200:
                    break
            except Exception as e:
                print(f"🔥 Warmup attempt {i+1} failed: {e}")
            time.sleep(3)
        time.sleep(5)

    def _post(self, xml_payload: str) -> dict:
        """POST XML payload and return parsed response dict."""
        self._rate_limiter.acquire()
        response = requests.post(
            self._url,
            headers=self._headers,
            data=xml_payload,
            timeout=self._timeout,
            verify=self._verify,
            auth=self._auth,
        )
        response.raise_for_status()
        return xmltodict.parse(response.text)
