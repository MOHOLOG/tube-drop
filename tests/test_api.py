from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session, sessionmaker

from app.database import Track
from app.services import media

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42fake-media-payload"
VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
TRACK_URL = "/api/tracks"


def make_cover_bytes(
    size: tuple[int, int] = (320, 240), image_format: str = "PNG"
) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, (40, 120, 200)).save(buffer, format=image_format)
    return buffer.getvalue()


@pytest.fixture
def fake_media(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_download(url: str, temp_dir: Path | str) -> media.DownloadedAudio:
        audio_path = Path(temp_dir) / "audio.webm"
        audio_path.write_bytes(b"fake-audio")
        return media.DownloadedAudio(
            path=audio_path,
            title="Fake Video Title",
            duration_sec=125,
        )

    def fake_assemble(
        cover_path: Path | str,
        audio_path: Path | str,
        output_path: Path | str,
    ) -> Path:
        output = Path(output_path)
        output.write_bytes(FAKE_MP4)
        return output

    monkeypatch.setattr(media, "download_audio", fake_download)
    monkeypatch.setattr(media, "assemble_mp4", fake_assemble)


def create_track(
    client: TestClient,
    *,
    url: str = VALID_URL,
    custom_title: str | None = None,
    cover: tuple[str, bytes, str] | None = None,
) -> dict:
    data = {"url": url}
    if custom_title is not None:
        data["custom_title"] = custom_title
    files = {"cover": cover} if cover is not None else None
    response = client.post(TRACK_URL, data=data, files=files)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_track_without_cover(
    client: TestClient,
    fake_media: None,
) -> None:
    body = create_track(client, custom_title="Мой трек")

    assert body["title"] == "Мой трек"
    assert body["youtube_url"] == VALID_URL
    assert body["duration_sec"] == 125
    assert Path(body["file_path"]).read_bytes() == FAKE_MP4
    assert Path(body["cover_path"]).is_file()
    assert body["file_size_bytes"] == len(FAKE_MP4)


def test_create_track_uses_yt_dlp_title_without_custom_title(
    client: TestClient,
    fake_media: None,
) -> None:
    body = create_track(client)

    assert body["title"] == "Fake Video Title"


def test_create_track_with_custom_cover(
    client: TestClient,
    fake_media: None,
) -> None:
    body = create_track(
        client,
        cover=("cover.png", make_cover_bytes(), "image/png"),
    )

    cover_path = Path(body["cover_path"])
    assert cover_path.is_file()
    with Image.open(cover_path) as image:
        assert image.format == "JPEG"
        assert image.size == (320, 240)


def test_create_track_deduplicates_file_on_disk(
    client: TestClient,
    fake_media: None,
    storage_dirs: SimpleNamespace,
) -> None:
    first = create_track(client, custom_title="First")
    second = create_track(client, custom_title="Second")

    assert first["file_hash"] == second["file_hash"]
    assert first["file_path"] == second["file_path"]
    assert len(list(storage_dirs.media.iterdir())) == 1


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url",
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "ftp://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_create_track_rejects_invalid_url(
    client: TestClient,
    fake_media: None,
    url: str,
) -> None:
    response = client.post(TRACK_URL, data={"url": url})

    assert response.status_code == 400


def test_create_track_rejects_non_image_cover(
    client: TestClient,
    fake_media: None,
) -> None:
    response = client.post(
        TRACK_URL,
        data={"url": VALID_URL},
        files={"cover": ("notes.txt", b"this is not an image", "text/plain")},
    )

    assert response.status_code == 400


def test_create_track_returns_502_on_ytdlp_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_download(url: str, temp_dir: Path | str) -> media.DownloadedAudio:
        raise media.YtDlpError("download failed")

    monkeypatch.setattr(media, "download_audio", broken_download)

    response = client.post(TRACK_URL, data={"url": VALID_URL})

    assert response.status_code == 502


def test_list_tracks_empty(client: TestClient) -> None:
    response = client.get(TRACK_URL)

    assert response.status_code == 200
    assert response.json() == {"tracks": [], "total_size_bytes": 0}


def test_list_tracks_after_creation(
    client: TestClient,
    fake_media: None,
) -> None:
    created = create_track(client, custom_title="Listed track")

    response = client.get(TRACK_URL)

    assert response.status_code == 200
    body = response.json()
    assert len(body["tracks"]) == 1
    assert body["tracks"][0]["id"] == created["id"]
    assert body["total_size_bytes"] == len(FAKE_MP4)


def test_list_tracks_does_not_double_count_deduplicated_files(
    client: TestClient,
    fake_media: None,
) -> None:
    create_track(client, custom_title="First")
    create_track(client, custom_title="Second")

    body = client.get(TRACK_URL).json()

    assert len(body["tracks"]) == 2
    assert body["total_size_bytes"] == len(FAKE_MP4)


def test_list_tracks_sorted_by_created_at_desc(
    client: TestClient,
    fake_media: None,
    session_factory: sessionmaker[Session],
) -> None:
    first = create_track(client, custom_title="Older")
    second = create_track(client, custom_title="Newer")

    with session_factory() as db:
        older = db.get(Track, first["id"])
        newer = db.get(Track, second["id"])
        assert older is not None
        assert newer is not None
        older.created_at = datetime(2024, 1, 1)
        newer.created_at = datetime(2024, 6, 1)
        db.commit()

    body = client.get(TRACK_URL).json()

    assert [track["id"] for track in body["tracks"]] == [
        second["id"],
        first["id"],
    ]


def test_download_track_with_cyrillic_title(
    client: TestClient,
    fake_media: None,
) -> None:
    title = "Тест/Трек"
    created = create_track(client, custom_title=title)

    response = client.get(f"{TRACK_URL}/{created['id']}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    safe_name = media.sanitize_filename(title)
    expected = f"attachment; filename*=UTF-8''{quote(f'{safe_name}.mp4', safe='')}"
    assert response.headers["content-disposition"] == expected
    assert response.content == FAKE_MP4


def test_download_missing_track_returns_404(client: TestClient) -> None:
    response = client.get(f"{TRACK_URL}/does-not-exist/download")

    assert response.status_code == 404


def test_qr_returns_svg(
    client: TestClient,
    fake_media: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOST_IP", "192.168.1.10")
    created = create_track(client)

    response = client.get(f"{TRACK_URL}/{created['id']}/qr")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert b"<svg" in response.content


def test_qr_missing_track_returns_404(client: TestClient) -> None:
    response = client.get(f"{TRACK_URL}/does-not-exist/qr")

    assert response.status_code == 404


def test_cover_returns_jpeg(client: TestClient, fake_media: None) -> None:
    created = create_track(client)

    response = client.get(f"{TRACK_URL}/{created['id']}/cover")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"


def test_cover_missing_track_returns_404(client: TestClient) -> None:
    response = client.get(f"{TRACK_URL}/does-not-exist/cover")

    assert response.status_code == 404


def test_delete_track_removes_record_and_file(
    client: TestClient,
    fake_media: None,
) -> None:
    created = create_track(client)
    file_path = Path(created["file_path"])
    assert file_path.is_file()

    response = client.delete(f"{TRACK_URL}/{created['id']}")

    assert response.status_code == 204
    assert not file_path.exists()
    assert client.get(TRACK_URL).json()["tracks"] == []


def test_delete_missing_track_returns_404(client: TestClient) -> None:
    response = client.delete(f"{TRACK_URL}/does-not-exist")

    assert response.status_code == 404


def test_delete_track_removes_custom_cover(
    client: TestClient,
    fake_media: None,
    storage_dirs: SimpleNamespace,
) -> None:
    created = create_track(
        client,
        cover=("cover.png", make_cover_bytes(), "image/png"),
    )
    cover_path = Path(created["cover_path"])
    assert cover_path.is_file()
    assert cover_path.parent == storage_dirs.covers

    response = client.delete(f"{TRACK_URL}/{created['id']}")

    assert response.status_code == 204
    assert not cover_path.exists()


def test_delete_track_keeps_default_cover(
    client: TestClient,
    fake_media: None,
    storage_dirs: SimpleNamespace,
) -> None:
    created = create_track(client)
    default_cover = storage_dirs.covers / media.DEFAULT_COVER_FILENAME
    assert default_cover.is_file()

    response = client.delete(f"{TRACK_URL}/{created['id']}")

    assert response.status_code == 204
    assert default_cover.is_file()


def test_total_size_bytes_resets_after_deleting_all_tracks(
    client: TestClient,
    fake_media: None,
) -> None:
    first = create_track(client, custom_title="First")
    second = create_track(client, custom_title="Second")
    assert client.get(TRACK_URL).json()["total_size_bytes"] == len(FAKE_MP4)

    assert client.delete(f"{TRACK_URL}/{first['id']}").status_code == 204
    assert client.get(TRACK_URL).json()["total_size_bytes"] == len(FAKE_MP4)

    assert client.delete(f"{TRACK_URL}/{second['id']}").status_code == 204
    assert client.get(TRACK_URL).json()["total_size_bytes"] == 0


def test_delete_keeps_shared_file_while_another_track_uses_it(
    client: TestClient,
    fake_media: None,
) -> None:
    first = create_track(client, custom_title="First")
    second = create_track(client, custom_title="Second")
    file_path = Path(first["file_path"])
    assert first["file_hash"] == second["file_hash"]

    first_delete = client.delete(f"{TRACK_URL}/{first['id']}")
    assert first_delete.status_code == 204
    assert file_path.is_file()

    second_delete = client.delete(f"{TRACK_URL}/{second['id']}")
    assert second_delete.status_code == 204
    assert not file_path.exists()
