from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TrackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    youtube_url: str
    title: str
    file_hash: str
    file_path: str
    cover_hash: str
    cover_path: str
    file_size_bytes: int
    duration_sec: int
    created_at: datetime


class TrackListResponse(BaseModel):
    tracks: list[TrackResponse]
    total_size_bytes: int
