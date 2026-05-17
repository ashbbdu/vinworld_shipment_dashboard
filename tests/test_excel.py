import pandas as pd
from pipeline.excel import parse_excel

def test_parse_excel_extracts_shipment_ids(tmp_path):
    df = pd.DataFrame({"Shipment ID": ["S001", "S002", None, "S003", ""]})
    path = tmp_path / "test.xlsx"
    df.to_excel(path, index=False)
    ids, rows = parse_excel(str(path))
    assert ids == ["S001", "S002", "S003"]
    assert len(rows) == 3

def test_parse_excel_normalizes_ids(tmp_path):
    df = pd.DataFrame({"Shipment ID": [" s001 ", "S002"]})
    path = tmp_path / "test.xlsx"
    df.to_excel(path, index=False)
    ids, rows = parse_excel(str(path))
    assert ids == ["S001", "S002"]  # stripped and uppercased

def test_parse_excel_stores_raw_row_data(tmp_path):
    df = pd.DataFrame({"Shipment ID": ["S001"], "Extra Col": ["val1"]})
    path = tmp_path / "test.xlsx"
    df.to_excel(path, index=False)
    ids, rows = parse_excel(str(path))
    assert rows[0]["Shipment ID"] == "S001"
    assert rows[0]["Extra Col"] == "val1"

def test_parse_excel_missing_column(tmp_path):
    df = pd.DataFrame({"Other": ["val"]})
    path = tmp_path / "test.xlsx"
    df.to_excel(path, index=False)
    try:
        parse_excel(str(path))
        assert False, "Should have raised"
    except Exception as e:
        assert "Shipment ID" in str(e)
