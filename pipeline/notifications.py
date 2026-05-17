import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger("pipeline.notifications")


class EmailNotifier:
    def __init__(self, settings):
        self._settings = settings

    def send_job_failure(self, job_run, failed_shipments):
        job_type = job_run.get("job_type", "unknown")
        run_id = job_run.get("id", "?")
        total = job_run.get("total_shipments", 0)
        failed_count = job_run.get("failed_count", len(failed_shipments))
        subject = f"[Pipeline Alert] {job_type} — {failed_count} of {total} shipments failed"
        lines = [
            f"Job: {job_type}",
            f"Run ID: {run_id}",
            f"Summary: {total - failed_count} completed, {failed_count} failed",
            "",
            "Failed Shipments:",
            "─" * 40,
        ]
        for i, fs in enumerate(failed_shipments, 1):
            lines.append(
                f"{i}. {fs.get('shipment_id', '?')} — {fs.get('error_message', 'unknown error')}"
            )
        self._send(self._settings.ERROR_EMAIL_RECIPIENTS, subject, "\n".join(lines))

    def send_job_report(self, job_run):
        if not self._settings.JOB_REPORT_RECIPIENTS:
            return
        job_type = job_run.get("job_type", "unknown")
        subject = f"[Pipeline Report] {job_type} completed"
        body = (
            f"Job: {job_type}\n"
            f"Run ID: {job_run.get('id')}\n"
            f"Processed: {job_run.get('processed_count', 0)}\n"
            f"Failed: {job_run.get('failed_count', 0)}"
        )
        self._send(self._settings.JOB_REPORT_RECIPIENTS, subject, body)

    def send_recovery_notice(self, recovered_count):
        subject = f"[Pipeline Alert] Service restarted — recovering {recovered_count} interrupted shipments"
        body = (
            f"The pipeline service was restarted.\n"
            f"{recovered_count} shipments were interrupted and have been re-queued for processing."
        )
        self._send(self._settings.ERROR_EMAIL_RECIPIENTS, subject, body)

    def send_circuit_breaker_alert(self, job_run, consecutive_failures):
        subject = f"[Pipeline Alert] CargoWise appears down — {job_run.get('job_type', '?')} halted"
        body = (
            f"Job: {job_run.get('job_type')}\n"
            f"Run ID: {job_run.get('id')}\n\n"
            f"{consecutive_failures} consecutive API failures detected.\n"
            f"Remaining shipments left as pending for next cycle."
        )
        self._send(self._settings.ERROR_EMAIL_RECIPIENTS, subject, body)

    def send_dead_letter_alert(self, shipment_id, total_retries):
        subject = f"[Pipeline Alert] Shipment {shipment_id} permanently failed"
        body = (
            f"Shipment {shipment_id} has failed {total_retries} times across all job runs.\n\n"
            f"It has been marked as do_not_query and will not be retried.\n"
            f"Manual intervention required."
        )
        self._send(self._settings.ERROR_EMAIL_RECIPIENTS, subject, body)

    def _send(self, recipients, subject, body, attachments=None):
        try:
            msg = MIMEMultipart()
            msg["From"] = f"{self._settings.SMTP_FROM_NAME} <{self._settings.SMTP_FROM}>"
            msg["To"] = ", ".join(recipients)
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))
            server = smtplib.SMTP(self._settings.SMTP_SERVER, self._settings.SMTP_PORT)
            try:
                server.starttls()
                server.login(self._settings.SMTP_USERNAME, self._settings.SMTP_PASSWORD)
                server.sendmail(self._settings.SMTP_FROM, recipients, msg.as_string())
            finally:
                server.quit()
            logger.info(f"Email sent: {subject}")
        except Exception as e:
            logger.error(f"Failed to send email '{subject}': {e}")
