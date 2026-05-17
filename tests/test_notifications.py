from unittest.mock import patch, MagicMock, ANY
from pipeline.notifications import EmailNotifier


def _make_settings():
    s = MagicMock()
    s.SMTP_SERVER = "smtp.test.com"
    s.SMTP_PORT = 587
    s.SMTP_USERNAME = "user@test.com"
    s.SMTP_PASSWORD = "pass"
    s.SMTP_FROM = "from@test.com"
    s.SMTP_FROM_NAME = "Test Pipeline"
    s.ERROR_EMAIL_RECIPIENTS = ["admin1@test.com", "admin2@test.com"]
    s.JOB_REPORT_RECIPIENTS = []
    return s


def test_job_failure_email_subject():
    notifier = EmailNotifier(_make_settings())
    with patch.object(notifier, '_send') as mock_send:
        job_run = {"job_type": "air_sync", "id": "abc-123", "total_shipments": 45, "failed_count": 3}
        failed = [{"shipment_id": "S001", "error_message": "timeout"}]
        notifier.send_job_failure(job_run, failed)
        mock_send.assert_called_once()
        subject = mock_send.call_args[0][1]
        assert "air_sync" in subject
        assert "3" in subject


def test_job_failure_email_body():
    notifier = EmailNotifier(_make_settings())
    with patch.object(notifier, '_send') as mock_send:
        job_run = {"job_type": "air_sync", "id": "abc-123", "total_shipments": 45, "failed_count": 3}
        failed = [{"shipment_id": "S001", "error_message": "timeout"}]
        notifier.send_job_failure(job_run, failed)
        body = mock_send.call_args[0][2]
        assert "S001" in body
        assert "timeout" in body


def test_recovery_notice_includes_count():
    notifier = EmailNotifier(_make_settings())
    with patch.object(notifier, '_send') as mock_send:
        notifier.send_recovery_notice(12)
        body = mock_send.call_args[0][2]
        assert "12" in body


def test_circuit_breaker_alert():
    notifier = EmailNotifier(_make_settings())
    with patch.object(notifier, '_send') as mock_send:
        notifier.send_circuit_breaker_alert({"job_type": "sea_sync", "id": "xyz"}, 5)
        subject = mock_send.call_args[0][1]
        assert "Circuit" in subject or "down" in subject.lower()


def test_dead_letter_alert():
    notifier = EmailNotifier(_make_settings())
    with patch.object(notifier, '_send') as mock_send:
        notifier.send_dead_letter_alert("S999", 10)
        body = mock_send.call_args[0][2]
        assert "S999" in body


def test_send_catches_smtp_errors():
    settings = _make_settings()
    notifier = EmailNotifier(settings)
    # _send should not raise even if SMTP fails
    with patch("pipeline.notifications.smtplib.SMTP") as mock_smtp:
        mock_smtp.side_effect = Exception("connection refused")
        notifier._send(["to@test.com"], "Test", "Body")  # should not raise


def test_send_uses_tls():
    settings = _make_settings()
    notifier = EmailNotifier(settings)
    with patch("pipeline.notifications.smtplib.SMTP") as mock_smtp:
        mock_instance = MagicMock()
        mock_smtp.return_value = mock_instance
        notifier._send(["to@test.com"], "Test", "Body")
        mock_instance.starttls.assert_called_once()
        mock_instance.login.assert_called_once_with("user@test.com", "pass")
