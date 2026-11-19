import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.services import media


def make_image(size: tuple[int, int], image_format: str = "PNG") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, (120, 40, 200)).save(buffer, format=image_format)
    return buffer.getvalue()


def test_process_cover_downscales_large_image() -> None:
    processed = media.process_cover(make_image((2000, 1000)))

    with Image.open(BytesIO(processed)) as image:
        assert image.size == (1080, 540)


def test_process_cover_rounds_odd_dimensions_to_even() -> None:
    processed = media.process_cover(make_image((501, 303)))

    with Image.open(BytesIO(processed)) as image:
        assert image.size == (500, 302)
        assert image.width % 2 == 0
        assert image.height % 2 == 0


def test_process_cover_rejects_text_data() -> None:
    try:
        media.process_cover(b"this is not an image")
    except media.UnsupportedImageFormatError:
        pass
    else:
        raise AssertionError("UnsupportedImageFormatError was not raised")


def test_default_cover_is_valid_jpeg_800x800(tmp_path: Path) -> None:
    data = media.get_default_cover(covers_dir=tmp_path)

    with Image.open(BytesIO(data)) as image:
        assert image.format == "JPEG"
        assert image.size == (800, 800)

    assert (tmp_path / media.DEFAULT_COVER_FILENAME).is_file()


def test_default_cover_is_cached(tmp_path: Path) -> None:
    first = media.get_default_cover(covers_dir=tmp_path)
    second = media.get_default_cover(covers_dir=tmp_path)

    assert first == second


def test_sha256_file(tmp_path: Path) -> None:
    path = tmp_path / "sample.bin"
    path.write_bytes(b"hello tube-drop")

    assert media.sha256_file(path) == hashlib.sha256(b"hello tube-drop").hexdigest()


def test_sanitize_filename_removes_forbidden_chars() -> None:
    result = media.sanitize_filename('a/b\\c:d*e?f"g<h>i|j Мир')

    assert result == "abcdefghij Мир"


def test_sanitize_filename_preserves_cyrillic() -> None:
    assert media.sanitize_filename("Тестовый трек") == "Тестовый трек"


def test_sanitize_filename_falls_back_for_empty_result() -> None:
    assert media.sanitize_filename('/*?:"<>|\\') == media.DEFAULT_FILENAME
