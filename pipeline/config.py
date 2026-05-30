# """
# Centralised configuration — every module reads settings from here,
# never from os.getenv() directly.

# Supports multi-environment deployment via PIPELINE_ENV:
#     PIPELINE_ENV=prod  →  loads config/.env.prod
#     PIPELINE_ENV=uat   →  loads config/.env.uat
#     (unset)            →  loads .env (legacy fallback)
# """

# import os
# from pathlib import Path
# from dotenv import load_dotenv

# _env_name = os.getenv("PIPELINE_ENV", "").strip().lower()
# _project_root = Path(__file__).resolve().parent.parent

# if _env_name:
#     _env_file = _project_root / "config" / f".env.{_env_name}"
#     if not _env_file.exists():
#         raise FileNotFoundError(
#             f"Environment file not found: {_env_file}\n"
#             f"PIPELINE_ENV={_env_name} but config/.env.{_env_name} does not exist.\n"
#             f"Available: {', '.join(f.name for f in (_project_root / 'config').glob('.env.*'))}"
#         )
#     load_dotenv(_env_file, override=True)
#     print(f"[config] Loaded environment: {_env_name} ({_env_file})")
# else:
#     load_dotenv(_project_root / ".env")
#     print("[config] Loaded environment: default (.env)")


# class Settings:
#     """Reads all environment variables once and exposes them as attributes."""
    
   

#     def __init__(self):
#         # --- Database ---
#         self.ENV = os.getenv("ENV", "unknown")
#         self.DB_HOST = self._required("DB_HOST")
#         self.DB_USER = self._required("DB_USER")
#         self.DB_PASSWORD = self._required("DB_PASSWORD")
#         self.DB_NAME = self._required("DB_NAME")
#         self.DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))

#         # --- CargoWise API ---
#         self.CW_API_URL = self._required("CW_API_URL")
#         self.CW_CLIENT_ID = self._required("CW_CLIENT_ID")
#         self.CW_CLIENT_SECRET = self._required("CW_CLIENT_SECRET")
#         self.CW_USERNAME = self._required("CW_USERNAME")
#         self.CW_PASSWORD = self._required("CW_PASSWORD")
#         self.CW_ORIGIN = self._required("CW_ORIGIN")
#         self.CW_TIMEOUT = int(os.getenv("CW_TIMEOUT", "60"))
#         self.CW_RATE_LIMIT = int(os.getenv("CW_RATE_LIMIT", "10"))
#         self.CW_CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CW_CIRCUIT_BREAKER_THRESHOLD", "5"))
#         self.CW_AUTH_MODE = os.getenv("CW_AUTH_MODE", "header").lower()  # "header" or "basic"
#         self.CW_VERIFY_SSL = os.getenv("CW_VERIFY_SSL", "False").lower() in ("1", "true", "yes")
#         self.CW_SHIPMENT_COMPANY_CODE = os.getenv("CW_SHIPMENT_COMPANY_CODE", "INJ")
#         self.CW_DOCUMENT_COMPANY_CODE = os.getenv("CW_DOCUMENT_COMPANY_CODE", "VWT")
#         self.CW_DOCUMENT_DATA_PROVIDER = os.getenv("CW_DOCUMENT_DATA_PROVIDER", "GWSTRVWR")
#         self.CW_ENTERPRISE_ID = os.getenv("CW_ENTERPRISE_ID", "GWS")
#         self.CW_SERVER_ID = os.getenv("CW_SERVER_ID", "TR2")

#         # --- SFTP ---
#         self.SFTP_HOST = self._required("SFTP_HOST")
#         self.SFTP_PORT = int(os.getenv("SFTP_PORT", "22"))
#         self.SFTP_USERNAME = self._required("SFTP_USERNAME")
#         self.SFTP_PASSWORD = self._required("SFTP_PASSWORD")
#         self.SFTP_REMOTE_DIR = os.getenv("SFTP_REMOTE_DIR", "")
#         self.SFTP_FILE_PATTERN = os.getenv("SFTP_FILE_PATTERN", "Shipment Profile Report *.xlsx")
#         self.SFTP_SAFE_AGE_SECONDS = int(os.getenv("SFTP_SAFE_AGE_SECONDS", "60"))
#         self.SFTP_DELETE_AFTER_INGEST = os.getenv("SFTP_DELETE_AFTER_INGEST", "True").lower() in ("1", "true", "yes")

#         # --- Scheduler ---
#         self.EXCEL_INGEST_SCHEDULE = os.getenv("EXCEL_INGEST_SCHEDULE", "0 10 */3 * *")
#         self.SEA_REVERSE_SCHEDULE = os.getenv("SEA_REVERSE_SCHEDULE", "0 0 * * *")
#         self.NIGHTLY_RETRY_ENABLED = os.getenv("NIGHTLY_RETRY_ENABLED", "True").lower() in ("1", "true", "yes")
#         self.NIGHTLY_RETRY_SCHEDULE = os.getenv("NIGHTLY_RETRY_SCHEDULE", "30 0 * * *")
#         self.ARCHIVE_ENABLED = os.getenv("ARCHIVE_ENABLED", "True").lower() in ("1", "true", "yes")
#         self.ARCHIVE_SCHEDULE = os.getenv("ARCHIVE_SCHEDULE", "0 2 * * *")
#         self.JOB_MAX_INSTANCES = int(os.getenv("JOB_MAX_INSTANCES", "1"))

#         # --- Sync ---
#         self.SEA_ETA_WINDOW_DAYS = int(os.getenv("SEA_ETA_WINDOW_DAYS", "3"))
#         self.AIR_SYNC_TRANSPORT_MODE = os.getenv("AIR_SYNC_TRANSPORT_MODE", "AIR")
#         self.AIR_SYNC_STATUS = os.getenv("AIR_SYNC_STATUS", "Active")
#         self.SEA_SYNC_TRANSPORT_MODE = os.getenv("SEA_SYNC_TRANSPORT_MODE", "SEA")
#         self.SEA_SYNC_STATUS = os.getenv("SEA_SYNC_STATUS", "Active")

#         # --- Parallel Processing ---
#         self.MAX_PARALLEL_REQUESTS = int(os.getenv("MAX_PARALLEL_REQUESTS", "5"))
#         self.SHIPMENT_RETRY_MAX = int(os.getenv("SHIPMENT_RETRY_MAX", "3"))
#         self.SHIPMENT_RETRY_DELAY = int(os.getenv("SHIPMENT_RETRY_DELAY", "30"))
#         self.SHIPMENT_MAX_LIFETIME_RETRIES = int(os.getenv("SHIPMENT_MAX_LIFETIME_RETRIES", "10"))

#         # --- Email ---
#         self.SMTP_SERVER = self._required("SMTP_SERVER")
#         self.SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
#         self.SMTP_USERNAME = self._required("SMTP_USERNAME")
#         self.SMTP_PASSWORD = self._required("SMTP_PASSWORD")
#         self.SMTP_FROM = self._required("SMTP_FROM")
#         self.SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "VIN World Pipeline")
#         self.ERROR_EMAIL_RECIPIENTS = [e.strip() for e in self._required("ERROR_EMAIL_RECIPIENTS").split(",") if e.strip()]
#         self.JOB_REPORT_RECIPIENTS = [e.strip() for e in os.getenv("JOB_REPORT_RECIPIENTS", "").split(",") if e.strip()]

#         # --- S3 / Archive ---
#         self.AWS_S3_BUCKET = self._required("AWS_S3_BUCKET")
#         self.AWS_S3_ARCHIVE_PREFIX = os.getenv("AWS_S3_ARCHIVE_PREFIX", "archives/")
#         self.AWS_ACCESS_KEY_ID = self._required("AWS_ACCESS_KEY_ID")
#         self.AWS_SECRET_ACCESS_KEY = self._required("AWS_SECRET_ACCESS_KEY")
#         self.AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
#         self.ARCHIVE_AGE_DAYS = int(os.getenv("ARCHIVE_AGE_DAYS", "7"))

#         # --- General ---
#         self.DEBUG = os.getenv("DEBUG", "False").lower() in ("1", "true", "yes")
#         self.LOG_FILE = os.getenv("LOG_FILE", "pipeline.log")
#         self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
#         self.LOG_ROTATION = os.getenv("LOG_ROTATION", "daily")
#         self.DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/tmp/pipeline_downloads")
#         self.HEALTH_CHECK_FILE = os.getenv("HEALTH_CHECK_FILE", "/tmp/pipeline_health")
#         self.TRACKING_RETENTION_DAYS = int(os.getenv("TRACKING_RETENTION_DAYS", "30"))

#     # ------------------------------------------------------------------ #
#     @staticmethod
#     def _required(key: str) -> str:
#         """Return the env var value or raise ValueError."""
#         val = os.getenv(key)
#         if val is None or val.strip() == "":
#             raise ValueError(f"Missing required environment variable: {key}")
#         return val



"""
Centralised configuration — every module reads settings from here,
never from os.getenv() directly.

Supports multi-environment deployment via PIPELINE_ENV:
    PIPELINE_ENV=prod  →  loads config/.env.prod
    PIPELINE_ENV=uat   →  loads config/.env.uat
    (unset)            →  loads .env (legacy fallback)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

_env_name = os.getenv("PIPELINE_ENV", "").strip().lower()
_project_root = Path(__file__).resolve().parent.parent

if _env_name:
    _env_file = _project_root / "config" / f".env.{_env_name}"
    if not _env_file.exists():
        raise FileNotFoundError(
            f"Environment file not found: {_env_file}\n"
            f"PIPELINE_ENV={_env_name} but config/.env.{_env_name} does not exist.\n"
            f"Available: {', '.join(f.name for f in (_project_root / 'config').glob('.env.*'))}"
        )
    load_dotenv(_env_file, override=True)
    print(f"[config] Loaded environment: {_env_name} ({_env_file})")
else:
    load_dotenv(_project_root / ".env")
    print("[config] Loaded environment: default (.env)")


class Settings:
    """Reads all environment variables once and exposes them as attributes."""
    
   

    def __init__(self):
        # --- Database ---
        self.ENV = os.getenv("ENV", "unknown")
        self.DB_HOST = self._required("DB_HOST")
        self.DB_USER = self._required("DB_USER")
        self.DB_PASSWORD = self._required("DB_PASSWORD")
        self.DB_NAME = self._required("DB_NAME")
        self.DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))

        # --- CargoWise API ---
        # ⚠️ TEMPORARY TEST HARDCODE — remove before production.
        # Pinned to the svctr2 TEST instance, using HTTP Basic Auth
        # (username/password) as the test API supports.
        self.CW_API_URL = "https://svctr2-cw.glweststardubai.com/Services/eAdaptor"
        self.CW_AUTH_MODE = "basic"         # "basic" (username/password) or "header"
        # Basic-auth credentials (sent as Authorization: Basic ...):
        self.CW_USERNAME = "GWSEadaptor"
        self.CW_PASSWORD = "32pXP6+bDHJMQyd/9r1XekOw"
        # Header-auth credentials (only used if CW_AUTH_MODE is switched to "header"):
        self.CW_CLIENT_ID = "vin-web-01"
        self.CW_CLIENT_SECRET = "wwLAlK8yAZTnMdLI7g0BNIS40atQISyqws5FMDnSXtQ"
        self.CW_ORIGIN = "prod.origin.custom"
        self.CW_TIMEOUT = int(os.getenv("CW_TIMEOUT", "60"))
        self.CW_RATE_LIMIT = int(os.getenv("CW_RATE_LIMIT", "10"))
        self.CW_CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CW_CIRCUIT_BREAKER_THRESHOLD", "5"))
        self.CW_VERIFY_SSL = os.getenv("CW_VERIFY_SSL", "False").lower() in ("1", "true", "yes")
        # XML DataContext values — hardcoded to the TEST (TR2) instance.
        # Confirmed from the test response: Company/Code = INJ, EnterpriseID = GWS,
        # ServerID = TR2, DataProvider = GWSTR2INJ.
        self.CW_SHIPMENT_COMPANY_CODE = "INJ"
        self.CW_DOCUMENT_COMPANY_CODE = "INJ"        # best guess for TR2 instance; only affects document fetch (non-fatal)
        self.CW_DOCUMENT_DATA_PROVIDER = "GWSTR2INJ"  # from the test response's DataProvider
        self.CW_ENTERPRISE_ID = "GWS"
        self.CW_SERVER_ID = "TR2"

        # --- SFTP ---
        self.SFTP_HOST = self._required("SFTP_HOST")
        self.SFTP_PORT = int(os.getenv("SFTP_PORT", "22"))
        self.SFTP_USERNAME = self._required("SFTP_USERNAME")
        self.SFTP_PASSWORD = self._required("SFTP_PASSWORD")
        self.SFTP_REMOTE_DIR = os.getenv("SFTP_REMOTE_DIR", "")
        self.SFTP_FILE_PATTERN = os.getenv("SFTP_FILE_PATTERN", "Shipment Profile Report *.xlsx")
        self.SFTP_SAFE_AGE_SECONDS = int(os.getenv("SFTP_SAFE_AGE_SECONDS", "60"))
        self.SFTP_DELETE_AFTER_INGEST = os.getenv("SFTP_DELETE_AFTER_INGEST", "True").lower() in ("1", "true", "yes")

        # --- Scheduler ---
        self.EXCEL_INGEST_SCHEDULE = os.getenv("EXCEL_INGEST_SCHEDULE", "0 10 */3 * *")
        self.SEA_REVERSE_SCHEDULE = os.getenv("SEA_REVERSE_SCHEDULE", "0 0 * * *")
        self.NIGHTLY_RETRY_ENABLED = os.getenv("NIGHTLY_RETRY_ENABLED", "True").lower() in ("1", "true", "yes")
        self.NIGHTLY_RETRY_SCHEDULE = os.getenv("NIGHTLY_RETRY_SCHEDULE", "30 0 * * *")
        self.ARCHIVE_ENABLED = os.getenv("ARCHIVE_ENABLED", "True").lower() in ("1", "true", "yes")
        self.ARCHIVE_SCHEDULE = os.getenv("ARCHIVE_SCHEDULE", "0 2 * * *")
        self.JOB_MAX_INSTANCES = int(os.getenv("JOB_MAX_INSTANCES", "1"))

        # --- Sync ---
        self.SEA_ETA_WINDOW_DAYS = int(os.getenv("SEA_ETA_WINDOW_DAYS", "3"))
        self.AIR_SYNC_TRANSPORT_MODE = os.getenv("AIR_SYNC_TRANSPORT_MODE", "AIR")
        self.AIR_SYNC_STATUS = os.getenv("AIR_SYNC_STATUS", "Active")
        self.SEA_SYNC_TRANSPORT_MODE = os.getenv("SEA_SYNC_TRANSPORT_MODE", "SEA")
        self.SEA_SYNC_STATUS = os.getenv("SEA_SYNC_STATUS", "Active")

        # --- Parallel Processing ---
        self.MAX_PARALLEL_REQUESTS = int(os.getenv("MAX_PARALLEL_REQUESTS", "5"))
        self.SHIPMENT_RETRY_MAX = int(os.getenv("SHIPMENT_RETRY_MAX", "3"))
        self.SHIPMENT_RETRY_DELAY = int(os.getenv("SHIPMENT_RETRY_DELAY", "30"))
        self.SHIPMENT_MAX_LIFETIME_RETRIES = int(os.getenv("SHIPMENT_MAX_LIFETIME_RETRIES", "10"))

        # --- Email ---
        self.SMTP_SERVER = self._required("SMTP_SERVER")
        self.SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
        self.SMTP_USERNAME = self._required("SMTP_USERNAME")
        self.SMTP_PASSWORD = self._required("SMTP_PASSWORD")
        self.SMTP_FROM = self._required("SMTP_FROM")
        self.SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "VIN World Pipeline")
        self.ERROR_EMAIL_RECIPIENTS = [e.strip() for e in self._required("ERROR_EMAIL_RECIPIENTS").split(",") if e.strip()]
        self.JOB_REPORT_RECIPIENTS = [e.strip() for e in os.getenv("JOB_REPORT_RECIPIENTS", "").split(",") if e.strip()]

        # --- S3 / Archive ---
        self.AWS_S3_BUCKET = self._required("AWS_S3_BUCKET")
        self.AWS_S3_ARCHIVE_PREFIX = os.getenv("AWS_S3_ARCHIVE_PREFIX", "archives/")
        self.AWS_ACCESS_KEY_ID = self._required("AWS_ACCESS_KEY_ID")
        self.AWS_SECRET_ACCESS_KEY = self._required("AWS_SECRET_ACCESS_KEY")
        self.AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
        self.ARCHIVE_AGE_DAYS = int(os.getenv("ARCHIVE_AGE_DAYS", "7"))

        # --- General ---
        self.DEBUG = os.getenv("DEBUG", "False").lower() in ("1", "true", "yes")
        self.LOG_FILE = os.getenv("LOG_FILE", "pipeline.log")
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
        self.LOG_ROTATION = os.getenv("LOG_ROTATION", "daily")
        self.DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/tmp/pipeline_downloads")
        self.HEALTH_CHECK_FILE = os.getenv("HEALTH_CHECK_FILE", "/tmp/pipeline_health")
        self.TRACKING_RETENTION_DAYS = int(os.getenv("TRACKING_RETENTION_DAYS", "30"))

    # ------------------------------------------------------------------ #
    @staticmethod
    def _required(key: str) -> str:
        """Return the env var value or raise ValueError."""
        val = os.getenv(key)
        if val is None or val.strip() == "":
            raise ValueError(f"Missing required environment variable: {key}")
        return val