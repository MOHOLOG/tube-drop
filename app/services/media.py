import hashlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import yt_dlp
from PIL import Image, ImageDraw, UnidentifiedImageError

from app.config import settings

ALLOWED_IMAGE_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
DEFAULT_COVER_FILENAME = "default.jpg"
DEFAULT_FILENAME = "track"
DEFAULT_COVER_SIZE = 800
DEFAULT_COVER_BACKGROUND = "#2E2E32"
DEFAULT_COVER_ICON_COLOR = "#71717A"
MAX_COVER_SIDE = 1080
JPEG_QUALITY = 85
HASH_CHUNK_SIZE = 1024 * 1024
FORBIDDEN_FILENAME_CHARS = frozenset('/\\:*?"<>|')


class MediaError(Exception):
    pass


class UnsupportedImageFormatError(MediaError):
    pass


class YtDlpError(MediaError):
    pass


class FfmpegError(MediaError):
    pass


@dataclass(frozen=True, slots=True)
class DownloadedAudio:
    path: Path
    title: str
    duration_sec: int


@dataclass(frozen=True, slots=True)
class SavedMedia:
    file_hash: str
    file_path: Path
    cover_hash: str
    cover_path: Path
    file_size_bytes: int


@dataclass(frozen=True, slots=True)
class BuiltMedia:
    title: str
    duration_sec: int
    file_hash: str
    file_path: Path
    cover_hash: str
    cover_path: Path
    file_size_bytes: int


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_filename(title: str) -> str:
    cleaned = "".join(
        char for char in title if char not in FORBIDDEN_FILENAME_CHARS
    ).strip()
    return cleaned or DEFAULT_FILENAME


def process_cover(data: bytes) -> bytes:
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in ALLOWED_IMAGE_FORMATS:
                raise UnsupportedImageFormatError(
                    f"Unsupported image format: {image.format}"
                )
            image.load()
            rgb_image = image.convert("RGB")
    except UnsupportedImageFormatError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise UnsupportedImageFormatError("Unsupported or corrupted image") from exc

    rgb_image.thumbnail((MAX_COVER_SIDE, MAX_COVER_SIDE), Image.Resampling.LANCZOS)

    width = max(2, rgb_image.width - rgb_image.width % 2)
    height = max(2, rgb_image.height - rgb_image.height % 2)
    rgb_image = rgb_image.crop((0, 0, width, height))

    buffer = BytesIO()
    rgb_image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


def _render_default_cover() -> bytes:
    image = Image.new(
        "RGB",
        (DEFAULT_COVER_SIZE, DEFAULT_COVER_SIZE),
        DEFAULT_COVER_BACKGROUND,
    )
    draw = ImageDraw.Draw(image)
    icon = DEFAULT_COVER_ICON_COLOR

    draw.ellipse((270, 490, 350, 540), fill=icon)
    draw.ellipse((450, 460, 530, 510), fill=icon)
    draw.rectangle((342, 280, 352, 520), fill=icon)
    draw.rectangle((522, 250, 532, 490), fill=icon)
    draw.polygon(
        [(342, 280), (532, 250), (532, 292), (342, 322)],
        fill=icon,
    )

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


def get_default_cover(covers_dir: Path | str | None = None) -> bytes:
    directory = Path(covers_dir) if covers_dir is not None else settings.covers_dir
    cover_path = directory / DEFAULT_COVER_FILENAME
    if cover_path.exists():
        return cover_path.read_bytes()

    directory.mkdir(parents=True, exist_ok=True)
    data = _render_default_cover()
    cover_path.write_bytes(data)
    return data


def download_audio(url: str, temp_dir: Path | str) -> DownloadedAudio:
    directory = Path(temp_dir)
    directory.mkdir(parents=True, exist_ok=True)
    options: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": str(directory / "audio.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    try:
        with yt_dlp.YoutubeDL(cast(Any, options)) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise YtDlpError("yt-dlp returned no metadata")
            audio_path = Path(ydl.prepare_filename(info))
    except YtDlpError:
        raise
    except Exception as exc:
        raise YtDlpError(str(exc)) from exc

    if not audio_path.exists():
        candidates = sorted(directory.glob("audio.*"))
        if not candidates:
            raise YtDlpError("Downloaded audio file was not found")
        audio_path = candidates[0]

    title = str(info.get("title") or DEFAULT_FILENAME)
    duration = info.get("duration")
    duration_sec = int(duration) if duration else 0

    return DownloadedAudio(
        path=audio_path,
        title=title,
        duration_sec=duration_sec,
    )


def assemble_mp4(
    cover_path: Path | str,
    audio_path: Path | str,
    output_path: Path | str,
) -> Path:
    output = Path(output_path)
    command = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-framerate",
        "1",
        "-i",
        str(cover_path),
        "-i",
        str(audio_path),
        "-c:v",
        "libx264",
        "-tune",
        "stillimage",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output),
    ]

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise FfmpegError(result.stderr.strip() or "ffmpeg failed")

    return output


def save_media(
    mp4_path: Path | str,
    cover_jpeg: bytes,
    media_dir: Path | str | None = None,
    covers_dir: Path | str | None = None,
) -> SavedMedia:
    media_directory = Path(media_dir) if media_dir is not None else settings.media_dir
    covers_directory = (
        Path(covers_dir) if covers_dir is not None else settings.covers_dir
    )
    media_directory.mkdir(parents=True, exist_ok=True)
    covers_directory.mkdir(parents=True, exist_ok=True)

    source = Path(mp4_path)
    file_hash = sha256_file(source)
    target_mp4 = media_directory / f"{file_hash}.mp4"
    if not target_mp4.exists():
        shutil.copyfile(source, target_mp4)

    cover_hash = hashlib.sha256(cover_jpeg).hexdigest()
    target_cover = covers_directory / f"{cover_hash}.jpg"
    if not target_cover.exists():
        target_cover.write_bytes(cover_jpeg)

    return SavedMedia(
        file_hash=file_hash,
        file_path=target_mp4,
        cover_hash=cover_hash,
        cover_path=target_cover,
        file_size_bytes=target_mp4.stat().st_size,
    )


def build_media(
    url: str,
    cover: bytes | None = None,
    media_dir: Path | str | None = None,
    covers_dir: Path | str | None = None,
) -> BuiltMedia:
    cover_jpeg = (
        process_cover(cover) if cover else get_default_cover(covers_dir=covers_dir)
    )

    with tempfile.TemporaryDirectory(prefix="tube-drop-") as temp_dir:
        temp_path = Path(temp_dir)
        temp_cover = temp_path / "cover.jpg"
        temp_cover.write_bytes(cover_jpeg)

        audio = download_audio(url, temp_path)
        output = assemble_mp4(temp_cover, audio.path, temp_path / "output.mp4")
        saved = save_media(
            output,
            cover_jpeg,
            media_dir=media_dir,
            covers_dir=covers_dir,
        )

    return BuiltMedia(
        title=audio.title,
        duration_sec=audio.duration_sec,
        file_hash=saved.file_hash,
        file_path=saved.file_path,
        cover_hash=saved.cover_hash,
        cover_path=saved.cover_path,
        file_size_bytes=saved.file_size_bytes,
    )
