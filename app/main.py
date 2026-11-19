import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, urlparse

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Track, get_db, init_db
from app.schemas import TrackListResponse, TrackResponse
from app.services import media, network

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

DbSession = Annotated[Session, Depends(get_db)]

YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "www.youtu.be",
    }
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings.ensure_directories()
    init_db()
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg was not found in PATH. Install ffmpeg before starting tube-drop."
        )
    yield


STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="tube-drop", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _is_valid_youtube_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        return False
    return bool(parsed.path.strip("/"))


def _get_track_or_404(db: Session, track_id: str) -> Track:
    track = db.get(Track, track_id)
    if track is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Track not found"
        )
    return track


def _hash_referenced(db: Session, hash_value: str, *, cover: bool) -> bool:
    column = Track.cover_hash if cover else Track.file_hash
    count = db.scalar(
        select(func.count()).select_from(Track).where(column == hash_value)
    )
    return bool(count)


def _remove_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _total_size_bytes(db: Session) -> int:
    paths = db.scalars(select(Track.file_path).distinct()).all()
    total = 0
    for path in paths:
        file_path = Path(path)
        if file_path.is_file():
            total += file_path.stat().st_size
    return total


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@app.post(
    "/api/tracks",
    status_code=status.HTTP_201_CREATED,
    response_model=TrackResponse,
)
def create_track(
    url: Annotated[str, Form()],
    db: DbSession,
    custom_title: Annotated[str | None, Form()] = None,
    media_format: Annotated[str, Form(alias="format")] = media.FORMAT_MP4,
    cover: Annotated[UploadFile | None, File()] = None,
) -> Track:
    if not _is_valid_youtube_url(url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid YouTube URL"
        )

    media_format = media_format.strip().lower()
    if media_format not in media.ALLOWED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported format"
        )

    cover_bytes = cover.file.read() if cover is not None else None
    if cover is not None and not cover_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported image format",
        )

    try:
        built = media.build_media(url.strip(), cover_bytes, media_format=media_format)
    except media.UnsupportedImageFormatError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except media.YtDlpError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    except media.FfmpegError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    title = (custom_title or "").strip() or built.title
    track = Track(
        youtube_url=url.strip(),
        title=title,
        file_hash=built.file_hash,
        file_path=str(built.file_path),
        cover_hash=built.cover_hash,
        cover_path=str(built.cover_path),
        file_size_bytes=built.file_size_bytes,
        duration_sec=built.duration_sec,
    )
    db.add(track)
    db.commit()
    db.refresh(track)
    return track


@app.get("/api/tracks", response_model=TrackListResponse)
def list_tracks(db: DbSession) -> TrackListResponse:
    tracks = db.scalars(select(Track).order_by(Track.created_at.desc())).all()
    return TrackListResponse(
        tracks=[TrackResponse.model_validate(track) for track in tracks],
        total_size_bytes=_total_size_bytes(db),
    )


@app.get("/api/tracks/{track_id}/download")
def download_track(track_id: str, db: DbSession) -> FileResponse:
    track = _get_track_or_404(db, track_id)
    path = Path(track.file_path)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Track file not found"
        )

    extension = path.suffix.lower() or ".mp4"
    media_type = media.MEDIA_TYPES.get(extension, "application/octet-stream")
    filename = f"{media.sanitize_filename(track.title)}{extension}"
    encoded = quote(filename, safe="")
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


@app.get("/api/tracks/{track_id}/qr")
def track_qr(track_id: str, db: DbSession) -> Response:
    track = _get_track_or_404(db, track_id)
    url = network.build_download_url(network.detect_lan_ip(), settings.port, track.id)
    return Response(content=network.generate_qr_svg(url), media_type="image/svg+xml")


@app.get("/api/tracks/{track_id}/cover")
def track_cover(track_id: str, db: DbSession) -> FileResponse:
    track = _get_track_or_404(db, track_id)
    path = Path(track.cover_path)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Cover file not found"
        )
    return FileResponse(path, media_type="image/jpeg")


@app.delete("/api/tracks/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_track(track_id: str, db: DbSession) -> Response:
    track = _get_track_or_404(db, track_id)
    file_hash = track.file_hash
    cover_hash = track.cover_hash
    file_path = Path(track.file_path)
    cover_path = Path(track.cover_path)

    db.delete(track)
    db.commit()

    if not _hash_referenced(db, file_hash, cover=False):
        _remove_file(file_path)
    if (
        not _hash_referenced(db, cover_hash, cover=True)
        and cover_path.name != media.DEFAULT_COVER_FILENAME
    ):
        _remove_file(cover_path)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
