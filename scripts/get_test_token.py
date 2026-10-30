"""Get a Firebase ID token for testing the API in /docs (dev only).

Signs in like the app does (Firebase Auth REST API, email + password) and prints the token.
Paste it in http://localhost:8000/docs -> "Authorize". Tokens expire after 1 hour.

    python scripts/get_test_token.py --email test.student@example.com            # sign in
    python scripts/get_test_token.py --email test.student@example.com --create   # make the account first

The password is asked for (not shown). Needs FIREBASE_WEB_API_KEY in .env.
Use test accounts only - never a real student's account.
"""

import argparse
import getpass
import sys

import _bootstrap  # noqa: F401
import httpx

from api.core.config import get_settings

AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts:{action}?key={key}"


def get_token(email: str, password: str, *, create: bool = False) -> str:
    """Sign up (create=True) or sign in, and return the Firebase ID token."""
    key = get_settings().FIREBASE_WEB_API_KEY
    if not key:
        raise SystemExit("FIREBASE_WEB_API_KEY is empty in .env")
    action = "signUp" if create else "signInWithPassword"
    response = httpx.post(
        AUTH_URL.format(action=action, key=key),
        json={"email": email, "password": password, "returnSecureToken": True},
        timeout=15,
    )
    if response.status_code != 200:
        message = response.json().get("error", {}).get("message", response.text)
        raise SystemExit(f"Firebase said: {message}")
    return str(response.json()["idToken"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Get a Firebase ID token for /docs")
    parser.add_argument("--email", required=True)
    parser.add_argument("--create", action="store_true", help="create the account first")
    args = parser.parse_args()
    password = getpass.getpass("Password (8+ chars, a letter and a number): ")
    token = get_token(args.email, password, create=args.create)
    print("\nYour ID token (valid 1 hour) - paste it in /docs -> Authorize:\n")
    print(token)
    print(file=sys.stderr)


if __name__ == "__main__":
    main()
