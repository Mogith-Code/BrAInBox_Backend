"""Storage adapters: Firebase Storage (for generated images, downloaded uploads...), and a local
folder for development without a Firebase bucket."""

import asyncio
from pathlib import Path
from typing import Any


class FirebaseStorage:
    name = "firebase-storage"

    def __init__(self, bucket_name: str, project_id: str):
        import firebase_admin
        from firebase_admin import storage

        try:
            app = firebase_admin.get_app("brainbox-ai")
        except ValueError:
            app = firebase_admin.initialize_app(
                options={"projectId": project_id}, name="brainbox-ai"
            )
        self._bucket: Any = storage.bucket(bucket_name, app=app)

    async def save(self, path: str, data: bytes, content_type: str) -> str:
        blob = self._bucket.blob(path)
        # The SDK is blocking, so run it in a worker thread.
        await asyncio.to_thread(blob.upload_from_string, data, content_type=content_type)
        return path

    async def load(self, path: str) -> bytes:
        blob = self._bucket.blob(path)
        data: bytes = await asyncio.to_thread(blob.download_as_bytes)
        return data


class LocalStorage:
    """Files in a local folder. Dev only (STORAGE_BUCKET empty); api/core/storage.py writes to
    the same folder."""

    name = "local-storage"

    def __init__(self, root: str):
        self._root = Path(root).resolve()

    def _file(self, path: str) -> Path:
        file = (self._root / path).resolve()
        if not file.is_relative_to(self._root):  # e.g. "../../.env"
            raise ValueError(f"Storage path outside the storage folder: {path}")
        return file

    async def save(self, path: str, data: bytes, content_type: str) -> str:
        file = self._file(path)
        file.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(file.write_bytes, data)
        return path

    async def load(self, path: str) -> bytes:
        return await asyncio.to_thread(self._file(path).read_bytes)
