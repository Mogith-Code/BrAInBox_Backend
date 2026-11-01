"""Firebase Storage helper (uploads from students, generated images...).

Files are never served by the api itself; the app downloads them with short-lived signed URLs.

Dev without a bucket (STORAGE_BUCKET empty, ENVIRONMENT != prod): `upload_bytes` writes to
LOCAL_STORAGE_DIR instead, the folder the ai_service reads (ai_service/providers/storage.py).

Image URLs for the app (`public_image_url`):
  * with a bucket: a signed URL (no login header needed, valid VISUAL_URL_EXPIRY_DAYS days)
  * dev without a bucket: GET /api/v1/files/visuals/... on this API (see visuals/router.py)
"""

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi.concurrency import run_in_threadpool

from api.core.config import get_settings
from api.core.errors import ServiceUnavailableError

logger = logging.getLogger(__name__)

# Only these folders may be served by the dev file route (never student uploads).
PUBLIC_DEV_FOLDERS = ("visuals/",)

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
    """Upload bytes and return the storage path. Blocking: call it with run_in_threadpool.

    Callers validate size and type first (e.g. api/modules/content/service.py for PDFs).
    """
    settings = get_settings()
    if not settings.STORAGE_BUCKET and settings.ENVIRONMENT != "prod":
        _write_local(settings.LOCAL_STORAGE_DIR, path, data)
        return path
    _get_bucket().blob(path).upload_from_string(data, content_type=content_type)
    return path


def _write_local(root: str, path: str, data: bytes) -> None:
    """Dev only: keep the file in the local storage folder."""
    folder = Path(root).resolve()
    file = (folder / path).resolve()
    if not file.is_relative_to(folder):  # e.g. "../../.env"
        raise ValueError(f"Storage path outside the storage folder: {path}")
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(data)


def uses_local_files() -> bool:
    """True in dev without a bucket: files live in LOCAL_STORAGE_DIR."""
    settings = get_settings()
    return not settings.STORAGE_BUCKET and settings.ENVIRONMENT != "prod"


def local_file(path: str) -> Path | None:
    """Dev only: the file for a public path (visuals/...), or None if it is not allowed/missing."""
    if not uses_local_files():
        return None
    root = Path(get_settings().LOCAL_STORAGE_DIR).resolve()
    file = (root / path).resolve()
    # Check the RESOLVED path, so "visuals/../uploads/x.pdf" cannot reach student uploads.
    allowed = [(root / folder).resolve() for folder in PUBLIC_DEV_FOLDERS]
    if not any(file.is_relative_to(folder) for folder in allowed) or not file.is_file():
        return None
    return file


async def public_image_url(path: str | None, base_url: str) -> str | None:
    """A URL the phone can load WITHOUT an Authorization header, or None.

    `base_url` is the address the app called (e.g. "http://10.0.2.2:8000/"). Never raises:
    without a URL the app still shows the Mermaid code or the alt text.
    """
    if not path:
        return None
    settings = get_settings()
    if settings.STORAGE_BUCKET:
        minutes = settings.VISUAL_URL_EXPIRY_DAYS * 24 * 60
        try:
            # Signing may call Google (e.g. on Cloud Run), so keep it off the event loop.
            return await run_in_threadpool(generate_signed_url, path, minutes)
        except Exception:
            logger.exception("Could not sign a URL for %s", path)
            return None
    if uses_local_files():
        root = (settings.PUBLIC_BASE_URL or base_url).rstrip("/")
        return f"{root}/api/v1/files/{path}"
    return None
