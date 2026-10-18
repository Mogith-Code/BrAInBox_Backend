"""Firebase Storage helper (uploads from students, generated images...).

Files are never served by the api itself; the app downloads them with short-lived signed URLs.
"""

from datetime import timedelta
from typing import Any

from api.core.config import get_settings
from api.core.errors import ServiceUnavailableError

_bucket: Any = None


def _get_bucket() -> Any:
    """Return the Storage bucket (created lazily so the app starts without credentials)."""
    global _bucket
    if _bucket is None:
        import firebase_admin
        from firebase_admin import storage

        settings = get_settings()
        if not settings.STORAGE_BUCKET:
            raise ServiceUnavailableError(
                "Storage is not configured (STORAGE_BUCKET is empty)", code="STORAGE_NOT_CONFIGURED"
            )
        try:
            app = firebase_admin.get_app("brainbox-api")
        except ValueError:
            app = firebase_admin.initialize_app(
                options={"projectId": settings.FIREBASE_PROJECT_ID}, name="brainbox-api"
            )
        _bucket = storage.bucket(settings.STORAGE_BUCKET, app=app)
    return _bucket


def generate_signed_url(path: str, expires_minutes: int = 15, method: str = "GET") -> str:
    """Signed URL to download (GET) or upload (PUT) one file directly from/to Storage.

    Needs a service account with permission to sign (GOOGLE_APPLICATION_CREDENTIALS).
    """
    blob = _get_bucket().blob(path)
    url: str = blob.generate_signed_url(
        version="v4", expiration=timedelta(minutes=expires_minutes), method=method
    )
    return url


def upload_bytes(path: str, data: bytes, content_type: str) -> str:
    """Upload bytes and return the storage path."""
    # TODO(Samni): validate size / type before calling this (uploads module).
    _get_bucket().blob(path).upload_from_string(data, content_type=content_type)
    return path
