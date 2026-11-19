# tube-drop

Local web service that turns a YouTube link into a compact media file, stores it in a local
library, and lets you transfer it to a phone over Wi-Fi via a QR code.

## Features

- Paste a YouTube URL and optionally upload a cover (JPG, PNG, WEBP) via drag-and-drop or a file picker.
- If no cover is provided, a default gray cover (`800x800`, `#2E2E32` with a `#71717A` music note) is generated with Pillow and cached.
- Uploaded covers are converted to RGB, downscaled to at most `1080px` on the longer side, cropped to even dimensions, and saved as JPEG (`quality=85`).
- The best audio track is downloaded with `yt-dlp` (`format="bestaudio/best"`) into a temporary directory.
- `ffmpeg` assembles a compact, iOS/Android-compatible `.mp4` (H.264 + AAC 128k, `+faststart`).
- An optional `.mp3` output is also available (audio only, embedded cover art).
- SHA-256 deduplication: identical media and covers are stored only once in `storage/media/` and `storage/covers/`.
- SQLite metadata store (`storage/app.db`) via SQLAlchemy 2.0.
- Library UI with storage usage, responsive card grid, track actions, and toasts.
- QR modal with an SVG code that links to `http://<LAN_IP>:<PORT>/api/tracks/{id}/download`.
- Safe deletion: files are removed only when no other track references the same hash.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- `ffmpeg` available in `PATH` (checked at server startup)

## Install dependencies

```powershell
uv sync
```

## Install ffmpeg

- **Windows:** `winget install Gyan.FFmpeg` (or `choco install ffmpeg`), then reopen the terminal.
- **macOS:** `brew install ffmpeg`
- **Linux (Debian/Ubuntu):** `sudo apt update && sudo apt install ffmpeg`

Verify the installation:

```powershell
ffmpeg -version
```

## Run the server

```powershell
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` in a browser.

## LAN IP for QR codes

The QR code encodes the address a phone must use to download a track. The IP is resolved in this order:

1. The `HOST_IP` environment variable, if set.
2. The local address discovered via a UDP socket to `8.8.8.8:80`.
3. The fallback `127.0.0.1`.

Set `HOST_IP` explicitly when the automatic detection picks the wrong interface:

```powershell
$env:HOST_IP = "<your-wi-fi-ip>"
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```bash
HOST_IP=<your-wi-fi-ip> uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The phone must be on the same Wi-Fi network as the machine running the server.

## Run tests

Tests use mocks and temporary directories and do not require internet access, YouTube, or `ffmpeg`.

```powershell
uv run pytest -v
```

## Lint and format

```powershell
uv run ruff check .
uv run ruff format --check .
```

To apply formatting automatically:

```powershell
uv run ruff format .
```

## API

| Method   | Path                          | Description                                        |
|----------|-------------------------------|----------------------------------------------------|
| `GET`    | `/`                           | Web interface                                      |
| `POST`   | `/api/tracks`                 | Create a track (`url`, optional `custom_title`, `cover`, `format`) |
| `GET`    | `/api/tracks`                 | List tracks (newest first) with total storage size |
| `GET`    | `/api/tracks/{id}/download`   | Download the media file                            |
| `GET`    | `/api/tracks/{id}/qr`         | SVG QR code for the download URL                   |
| `GET`    | `/api/tracks/{id}/cover`      | JPEG cover                                         |
| `DELETE` | `/api/tracks/{id}`            | Delete a track                                     |

## Project structure

```text
.
├── app/
│   ├── config.py            # Paths, port, HOST_IP settings (pydantic-settings)
│   ├── database.py          # Engine, SessionLocal, Base, Track model, init_db()
│   ├── schemas.py           # Pydantic v2 response schemas
│   ├── main.py              # FastAPI app, routes, lifespan
│   └── services/
│       ├── media.py         # Pillow, yt-dlp, ffmpeg, SHA-256, sanitization
│       └── network.py       # LAN IP detection, SVG QR generation
├── templates/index.html
├── static/app.js
├── tests/
├── pyproject.toml
└── README.md
```

Runtime data lives in `storage/` (`app.db`, `media/`, `covers/`) and is not committed to git.
