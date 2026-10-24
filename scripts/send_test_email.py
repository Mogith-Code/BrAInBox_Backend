"""Send a sample "Your BrAInBox code" email to check the email settings.

    python scripts/send_test_email.py --to your.name@gmail.com

Uses the same settings as the api (.env): EMAIL_BACKEND, SMTP_HOST, SMTP_PORT, SMTP_USER,
SMTP_PASSWORD, SMTP_USE_TLS / SMTP_USE_SSL, EMAIL_FROM. The code in the email is fake (123456).
"""

import argparse
import asyncio
import smtplib

import _bootstrap  # noqa: F401

from api.core.config import get_settings
from api.core.email import build_code_email, get_email_sender
from api.core.errors import AppError


async def run(to: str) -> int:
    settings = get_settings()
    print(f"EMAIL_BACKEND={settings.EMAIL_BACKEND}  SMTP_HOST={settings.SMTP_HOST or '(empty)'}")
    print(f"SMTP_PORT={settings.SMTP_PORT}  SMTP_USER={settings.SMTP_USER or '(empty)'}")
    print(f"EMAIL_FROM={settings.EMAIL_FROM}")
    if settings.EMAIL_BACKEND != "smtp":
        print("Note: EMAIL_BACKEND is not 'smtp', so the email is only printed in the log.")

    message = build_code_email(to, "123456", "verify_email")
    try:
        await get_email_sender().send(message)
    except AppError as exc:
        print(f"FAILED: {exc.code} - {exc.message}")
        return 1
    except smtplib.SMTPAuthenticationError:
        print(
            "FAILED: the SMTP server rejected the username/password.\n"
            "For Gmail use an App Password (16 letters), not your normal password, and\n"
            "2-Step Verification must be ON for that Google account."
        )
        return 1
    except (smtplib.SMTPException, OSError) as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")
        print("Check SMTP_HOST / SMTP_PORT, your internet connection and the firewall.")
        return 1
    print(f"OK: sent to {to}. Check the inbox (and the Spam folder).")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a test code email")
    parser.add_argument("--to", required=True, help="where to send the test email")
    raise SystemExit(asyncio.run(run(parser.parse_args().to)))


if __name__ == "__main__":
    main()
