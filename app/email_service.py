import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)


def send_email(subject: str, html_body: str, recipients: list[str]) -> bool:
    settings = get_settings()

    if not settings.smtp_enabled:
        logger.info("email_skipped", reason="smtp_enabled=false")
        return False

    if not recipients:
        logger.warning("email_skipped", reason="no_recipients")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.report_from or settings.smtp_user
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(msg["From"], recipients, msg.as_string())
        logger.info("email_sent", subject=subject, recipients=len(recipients))
        return True
    except Exception as e:
        logger.error("email_send_failed", error=str(e))
        return False
