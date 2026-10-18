"""Storage adapter: Firebase Storage (for generated images, downloaded uploads...)."""

import asyncio
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
