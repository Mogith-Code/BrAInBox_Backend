"""Edit profile: bio and photo (GET/PATCH /profile/details, POST/DELETE /profile/avatar)."""

from api.core import storage
from api.modules.profiles import service

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def test_image_type_comes_from_the_file_bytes() -> None:
    assert service._image_extension(b"\xff\xd8\xff\xe0data") == "jpg"
    assert service._image_extension(PNG) == "png"
    assert service._image_extension(b"RIFF0000WEBPdata") == "webp"
    assert service._image_extension(b"<script>alert(1)</script>") is None


async def test_details_need_login(anon_client) -> None:
    assert (await anon_client.get("/api/v1/profile/details")).status_code == 401


async def test_save_bio_and_photo(client, student_in_db, monkeypatch) -> None:
    saved: list[str] = []
    deleted: list[list[str]] = []
    monkeypatch.setattr(storage, "upload_bytes", lambda path, data, kind: saved.append(path))
    monkeypatch.setattr(storage, "delete_files", lambda paths: deleted.append(paths) or 0)

    response = await client.patch("/api/v1/profile/details", json={"bio": "  Future doctor "})
    assert response.status_code == 200
    assert response.json()["bio"] == "Future doctor"

    files = {"file": ("me.png", PNG, "image/png")}
    response = await client.post("/api/v1/profile/avatar", files=files)
    assert response.status_code == 200
    assert saved[0].startswith(f"visuals/avatars/{student_in_db}/")
    assert saved[0].endswith(".png")

    response = await client.delete("/api/v1/profile/avatar")
    assert response.status_code == 200
    assert response.json()["avatar_url"] is None
    assert deleted == [[saved[0]]]


async def test_photo_must_be_a_small_image(client, student_in_db) -> None:
    fake = {"file": ("me.png", b"not an image", "image/png")}
    response = await client.post("/api/v1/profile/avatar", files=fake)
    assert response.json()["error"]["code"] == "AVATAR_INVALID"

    huge = {"file": ("me.png", PNG + b"0" * service.MAX_AVATAR_BYTES, "image/png")}
    response = await client.post("/api/v1/profile/avatar", files=huge)
    assert response.json()["error"]["code"] == "AVATAR_TOO_LARGE"
