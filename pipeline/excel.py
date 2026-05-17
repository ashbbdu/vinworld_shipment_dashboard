import logging
import pandas as pd

logger = logging.getLogger("pipeline.excel")

def parse_excel(file_path):
    """Parse Excel file, return (shipment_ids, rows_as_dicts)."""
    df = pd.read_excel(file_path, dtype=str)
    if "Shipment ID" not in df.columns:
        raise ValueError("Missing 'Shipment ID' column in Excel file")
    # Normalize: drop nulls, strip, uppercase
    df = df.dropna(subset=["Shipment ID"])
    df["Shipment ID"] = df["Shipment ID"].str.strip().str.upper()
    df = df[df["Shipment ID"] != ""]
    shipment_ids = df["Shipment ID"].tolist()
    rows = df.to_dict(orient="records")
    logger.info(f"Parsed {len(shipment_ids)} shipment IDs from Excel")
    return shipment_ids, rows
