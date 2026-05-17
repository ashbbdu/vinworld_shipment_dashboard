import re
import time
from unittest.mock import MagicMock
from pipeline.sftp import SFTPClient, find_latest_matching_file

def test_find_latest_file_selects_newest():
    pattern = re.compile(r"Shipment Profile Report .*\.xlsx$", re.IGNORECASE)
    now = time.time()
    file1 = MagicMock()
    file1.filename = "Shipment Profile Report 2024-03-18.xlsx"
    file1.st_mtime = now - 300
    file2 = MagicMock()
    file2.filename = "Shipment Profile Report 2024-03-19.xlsx"
    file2.st_mtime = now - 120
    file3 = MagicMock()
    file3.filename = "other_file.xlsx"
    file3.st_mtime = now - 60
    result = find_latest_matching_file([file1, file2, file3], pattern, safe_age=60)
    assert result.filename == "Shipment Profile Report 2024-03-19.xlsx"

def test_find_latest_file_skips_too_recent():
    pattern = re.compile(r"Shipment Profile Report .*\.xlsx$", re.IGNORECASE)
    now = time.time()
    file1 = MagicMock()
    file1.filename = "Shipment Profile Report 2024-03-18.xlsx"
    file1.st_mtime = now - 10
    result = find_latest_matching_file([file1], pattern, safe_age=60)
    assert result is None

def test_find_latest_file_no_matches():
    pattern = re.compile(r"Shipment Profile Report .*\.xlsx$", re.IGNORECASE)
    file1 = MagicMock()
    file1.filename = "random.csv"
    file1.st_mtime = time.time() - 300
    result = find_latest_matching_file([file1], pattern, safe_age=60)
    assert result is None
