"""Check the Firebase setup in one command (never prints secrets).

    python scripts/check_firebase.py
    python scripts/check_firebase.py --token <Firebase ID token>   # also check a login token

Checks: FIREBASE_PROJECT_ID is set, the service-account file exists, belongs to the same
project, and works (it reads one user from Firebase Auth - nothing is changed).
"""

import argparse
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from api.core.config import get_settings


def ok(message: str) -> None:
    print(f"  OK    {message}")


def fail(message: str) -> int:
    print(f"  FAIL  {message}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the Firebase setup")
    parser.add_argument("--token", help="a Firebase ID token to verify (optional)")
    args = parser.parse_args()
    settings = get_settings()
    print("Firebase setup check")

    if not settings.FIREBASE_PROJECT_ID:
        return fail("FIREBASE_PROJECT_ID is empty in .env")
    ok(f"FIREBASE_PROJECT_ID = {settings.FIREBASE_PROJECT_ID}")

    key_path = Path(settings.GOOGLE_APPLICATION_CREDENTIALS)
    if not settings.GOOGLE_APPLICATION_CREDENTIALS or not key_path.is_file():
        return fail(
            f"service-account file not found: '{settings.GOOGLE_APPLICATION_CREDENTIALS}' "
            "(expected ./secrets/firebase-service-account.json)"
        )
    try:
        key = json.loads(key_path.read_text(encoding="utf-8"))
    except ValueError:
        return fail(f"{key_path} is not valid JSON")
    if key.get("type") != "service_account" or "private_key" not in key:
        return fail(f"{key_path} is not a service-account key file")
    if key.get("project_id") != settings.FIREBASE_PROJECT_ID:
        return fail(
            f"the key is for project '{key.get('project_id')}', "
            f"but FIREBASE_PROJECT_ID is '{settings.FIREBASE_PROJECT_ID}'"
        )
    ok(f"service-account file {key_path} (project {key['project_id']})")

    from firebase_admin import auth

    from api.core.security import _get_firebase_app

    try:
        page = auth.list_users(max_results=1, app=_get_firebase_app())
        ok(
            f"service account works (Firebase Auth reachable, users on first page: {len(page.users)})"
        )
    except Exception as exc:
        return fail(f"Firebase Auth call failed: {type(exc).__name__}: {exc}")

    if args.token:
        try:
            claims = auth.verify_id_token(args.token, app=_get_firebase_app())
            ok(f"token is valid for uid {claims['uid']} ({claims.get('email')})")
        except Exception as exc:
            return fail(f"token is not valid: {type(exc).__name__}")

    print("All good: the api can verify logins and update Firebase users.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
