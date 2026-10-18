"""Sending emails (6-digit codes for now).

EMAIL_BACKEND=console  -> ConsoleEmailSender: writes the email to the log (dev only)
EMAIL_BACKEND=smtp     -> SmtpEmailSender: real email through an SMTP server (provider TBD)

Routers get the sender through the `EmailSenderDep` dependency, so tests can swap in a fake.
"""

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from typing import Annotated, Protocol

from fastapi import Depends

from api.core.config import get_settings
from shared.branding import APP_NAME, PRIMARY, TAGLINE

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
                "[console email] to=%s subject=%s (body hidden)", message.to, message.subject
            )


class SmtpEmailSender:
    """Sends real email with SMTP (STARTTLS). Settings: SMTP_HOST, SMTP_PORT, SMTP_USER,
    SMTP_PASSWORD, SMTP_USE_TLS, EMAIL_FROM."""

    async def send(self, message: EmailMessage) -> None:
        await asyncio.to_thread(self._send_blocking, message)

    def _send_blocking(self, message: EmailMessage) -> None:
        settings = get_settings()
        mime = MimeMessage()
        mime["From"] = settings.EMAIL_FROM
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.text)
        mime.add_alternative(message.html, subtype="html")
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls()
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(mime)


def get_email_sender() -> EmailSender:
    """FastAPI dependency (tests override it with a fake that keeps the messages)."""
    if get_settings().EMAIL_BACKEND == "smtp":
        return SmtpEmailSender()
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
    html = (
        f'<div style="font-family:Arial,sans-serif;color:#1E1B4B">'
        f'<h2 style="color:{PRIMARY};margin:0 0 12px">{APP_NAME}</h2>'
        f"<p>Enter this code in the app to {action}:</p>"
        f'<p style="font-size:28px;font-weight:bold;letter-spacing:6px">{code}</p>'
        f"<p>It expires in {minutes_valid} minutes. If you did not ask for this code, "
        f"you can ignore this email.</p>"
        f'<p style="color:#6B7280;font-size:12px">{APP_NAME} &middot; {TAGLINE}</p></div>'
    )
    return EmailMessage(to=to, subject=CODE_EMAIL_SUBJECT, text=text, html=html)
