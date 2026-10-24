"""Sending emails (the 6-digit OTP codes for now).

EMAIL_BACKEND=console  -> ConsoleEmailSender: writes the email to the log (dev only)
EMAIL_BACKEND=smtp     -> SmtpEmailSender: real email through an SMTP server
                          (e.g. Gmail with an App Password - see api/modules/auth/README.md)

Routers get the sender through the `EmailSenderDep` dependency, so tests can swap in a fake.
Firebase Auth can't send 6-digit codes by email (only links), so we send them ourselves.
"""

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Annotated, Protocol

from fastapi import Depends

from api.core.config import get_settings
from api.core.errors import ServiceUnavailableError
from shared.branding import APP_NAME, INK, LOGO_URL, PRIMARY, TAGLINE

logger = logging.getLogger(__name__)

CODE_EMAIL_SUBJECT = f"Your {APP_NAME} code"


@dataclass
class EmailMessage:
    to: str
    subject: str
    text: str  # plain-text body
    html: str  # simple HTML body


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailSender:
    """Prints emails to the log instead of sending them.

    The body (which contains the code) is printed ONLY when ENVIRONMENT=dev.
    """

    async def send(self, message: EmailMessage) -> None:
        if get_settings().ENVIRONMENT == "dev":
            logger.warning(
                "[console email] to=%s subject=%s\n%s", message.to, message.subject, message.text
            )
        else:
            logger.warning(
                "[console email] to=%s subject=%s (body hidden - set EMAIL_BACKEND=smtp "
                "to really send emails)",
                message.to,
                message.subject,
            )


class SmtpEmailSender:
    """Sends real email with SMTP.

    Port 587 + SMTP_USE_TLS=true  -> STARTTLS (Gmail, Brevo, SendGrid, ...)
    Port 465 or SMTP_USE_SSL=true -> SSL from the start
    """

    async def send(self, message: EmailMessage) -> None:
        settings = get_settings()
        if not settings.SMTP_HOST:
            raise ServiceUnavailableError(
                "Email is not set up on the server (SMTP_HOST is empty)",
                code="EMAIL_NOT_CONFIGURED",
            )
        await asyncio.to_thread(self._send_blocking, message)

    def _send_blocking(self, message: EmailMessage) -> None:
        settings = get_settings()
        mime = MimeMessage()
        mime["From"] = settings.EMAIL_FROM
        mime["To"] = message.to
        mime["Subject"] = message.subject
        # Date + Message-ID make the email look normal to spam filters.
        mime["Date"] = formatdate(localtime=True)
        sender_domain = parseaddr(settings.EMAIL_FROM)[1].rpartition("@")[2] or None
        mime["Message-ID"] = make_msgid(domain=sender_domain)
        mime.set_content(message.text)
        mime.add_alternative(message.html, subtype="html")

        use_ssl = settings.SMTP_USE_SSL or settings.SMTP_PORT == 465
        smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        timeout = settings.SMTP_TIMEOUT_SECONDS
        with smtp_class(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout) as smtp:
            if settings.SMTP_USE_TLS and not use_ssl:
                smtp.starttls()
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(mime)
        logger.info("Email sent to %s (%s)", message.to, message.subject)


def get_email_sender() -> EmailSender:
    """FastAPI dependency (tests override it with a fake that keeps the messages)."""
    settings = get_settings()
    if settings.EMAIL_BACKEND == "smtp":
        return SmtpEmailSender()
    if settings.ENVIRONMENT == "prod":
        logger.error("EMAIL_BACKEND is not 'smtp' in prod: students will not get their codes")
    return ConsoleEmailSender()


EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]


def build_code_email(to: str, code: str, purpose: str, minutes_valid: int = 10) -> EmailMessage:
    """The "Your BrAInBox code" email for verify_email / reset_password."""
    action = "verify your email" if purpose == "verify_email" else "reset your password"
    text = (
        f"Your {APP_NAME} code is {code}\n\n"
        f"Enter it in the app to {action}. It expires in {minutes_valid} minutes.\n"
        "If you did not ask for this code, you can ignore this email.\n\n"
        f"{APP_NAME} - {TAGLINE}\n"
    )
    # Email clients need a full https:// address for images, so the logo is only shown
    # when LOGO_URL is public (the default "/static/..." path is not).
    logo = (
        f'<img src="{LOGO_URL}" alt="{APP_NAME}" width="180" style="display:block;margin:0 0 16px">'
        if LOGO_URL.startswith(("http://", "https://"))
        else f'<h2 style="color:{PRIMARY};margin:0 0 16px">{APP_NAME}</h2>'
    )
    html = (
        f'<div style="font-family:Arial,sans-serif;color:{INK};max-width:480px">'
        f"{logo}"
        f"<p>Enter this code in the app to {action}:</p>"
        f'<p style="font-size:30px;font-weight:bold;letter-spacing:8px;color:{PRIMARY};'
        f'margin:16px 0">{code}</p>'
        f"<p>It expires in {minutes_valid} minutes. If you did not ask for this code, "
        f"you can ignore this email.</p>"
        f'<p style="color:#6B7280;font-size:12px;margin-top:24px">{APP_NAME} &middot; '
        f"{TAGLINE}</p></div>"
    )
    return EmailMessage(to=to, subject=CODE_EMAIL_SUBJECT, text=text, html=html)
