from unittest.mock import MagicMock, patch

def _make_settings():
    s = MagicMock()
    s.SFTP_DELETE_AFTER_INGEST = False
    s.SHIPMENT_MAX_LIFETIME_RETRIES = 10
    s.MAX_PARALLEL_REQUESTS = 2
    s.SHIPMENT_RETRY_MAX = 3
    s.SHIPMENT_RETRY_DELAY = 0
    s.CW_CIRCUIT_BREAKER_THRESHOLD = 5
    return s

def test_excel_ingest_syncs_new_shipments():
    from pipeline.jobs.excel_ingest import run
    db = MagicMock()
    db.create_job_run.return_value = "run-1"
    db.get_existing_shipment_ids.return_value = {"S001"}
    cw = MagicMock()
    notifier = MagicMock()
    settings = _make_settings()
    with patch("pipeline.jobs.excel_ingest.SFTPClient") as mock_sftp_cls, \
         patch("pipeline.jobs.excel_ingest.parse_excel") as mock_excel, \
         patch("pipeline.jobs.excel_ingest.run_job") as mock_run, \
         patch("pipeline.jobs.excel_ingest.os.path.getsize", return_value=1024):
        sftp_instance = MagicMock()
        sftp_instance.download_latest.return_value = ("/tmp/test.xlsx", "test.xlsx")
        mock_sftp_cls.return_value.__enter__ = MagicMock(return_value=sftp_instance)
        mock_sftp_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_excel.return_value = (["S001", "S002", "S003"], [{"Shipment ID": "S001"}, {"Shipment ID": "S002"}, {"Shipment ID": "S003"}])
        result = run(db, cw, notifier, settings)
        # Only S002, S003 are new
        mock_run.assert_called_once()
        new_ids = mock_run.call_args[0][1]
        assert "S001" not in new_ids
        assert "S002" in new_ids
        assert "S003" in new_ids
        db.save_excel_metadata.assert_called_once()
        db.save_excel_rows.assert_called_once()

def test_excel_ingest_deletes_sftp_if_enabled():
    from pipeline.jobs.excel_ingest import run
    db = MagicMock()
    db.create_job_run.return_value = "run-1"
    db.get_existing_shipment_ids.return_value = set()
    settings = _make_settings()
    settings.SFTP_DELETE_AFTER_INGEST = True
    with patch("pipeline.jobs.excel_ingest.SFTPClient") as mock_sftp_cls, \
         patch("pipeline.jobs.excel_ingest.parse_excel") as mock_excel, \
         patch("pipeline.jobs.excel_ingest.run_job"), \
         patch("pipeline.jobs.excel_ingest.os.path.getsize", return_value=1024):
        sftp_instance = MagicMock()
        sftp_instance.download_latest.return_value = ("/tmp/test.xlsx", "test.xlsx")
        mock_sftp_cls.return_value.__enter__ = MagicMock(return_value=sftp_instance)
        mock_sftp_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_excel.return_value = (["S001"], [{"Shipment ID": "S001"}])
        run(db, MagicMock(), MagicMock(), settings)
        sftp_instance.delete_file.assert_called_once_with("test.xlsx")

def test_sync_air_queries_active_air():
    from pipeline.jobs.sync_air import run
    db = MagicMock()
    db.get_active_shipments.return_value = ["S001", "S002"]
    with patch("pipeline.jobs.sync_air.run_job") as mock_run:
        run(db, MagicMock(), MagicMock(), _make_settings())
        mock_run.assert_called_once()
        assert "air_sync" in mock_run.call_args[0][0]

def test_sync_sea_queries_critical_sea():
    from pipeline.jobs.sync_sea import run_sync
    db = MagicMock()
    db.get_active_shipments.return_value = ["S010"]
    with patch("pipeline.jobs.sync_sea.run_job") as mock_run:
        run_sync(db, MagicMock(), MagicMock(), _make_settings())
        mock_run.assert_called_once()

def test_sync_sea_reverse():
    from pipeline.jobs.sync_sea import run_reverse
    db = MagicMock()
    db.get_active_shipments.return_value = ["S020"]
    with patch("pipeline.jobs.sync_sea.run_job") as mock_run:
        run_reverse(db, MagicMock(), MagicMock(), _make_settings())
        mock_run.assert_called_once()

def test_nightly_retry_filters_dead_letters():
    from pipeline.jobs.nightly_retry import run
    db = MagicMock()
    db.get_failed_shipments.return_value = [
        {"shipment_id": "S001", "lifetime_retry_count": 5},
        {"shipment_id": "S002", "lifetime_retry_count": 15},
    ]
    notifier = MagicMock()
    settings = _make_settings()
    with patch("pipeline.jobs.nightly_retry.run_job") as mock_run:
        run(db, MagicMock(), notifier, settings)
        if mock_run.called:
            ids = mock_run.call_args[0][1]
            assert "S001" in ids
            assert "S002" not in ids
        # S002 should trigger dead letter
        db.mark_do_not_query.assert_called_with("S002")
        notifier.send_dead_letter_alert.assert_called_once()
