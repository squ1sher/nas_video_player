# Local NAS Video Player

Mini-YouTube style local web video player for Synology NAS.

- Backend: FastAPI + SQLite + ffprobe/ffmpeg
- Frontend: React + Vite + TypeScript
- Deployment: single Docker container via Docker Compose
- Network scope: local network only (no auth yet)

## Target NAS

- Synology DS923+
- DSM 7.2.2+ (tested target: 7.2.2-72806 Update 5)
- Synology Container Manager (Docker Compose)

## Phase 1.5 Features (current)

### Watch progress / Resume playback
- Global (single-user) watch progress saved in SQLite
- Progress saved every 5 seconds, on pause, and on page close
- Resume from saved position or start from beginning
- Videos marked **completed** when ≥ 90 % watched
- **Continue Watching** section on library page

### Browser compatibility status
- Each video is analyzed for browser playback compatibility:
  - `direct_play` (green) — MP4/H.264/AAC or WebM/VP8/VP9/AV1/Opus
  - `may_not_play` (yellow) — MKV, MOV, unknown codecs
  - `needs_conversion` (red) — AVI, HEVC/H.265, DTS audio
- Badge shown on video cards and watch page
- Friendly error message if playback fails

### Folder navigation
- Videos organized by relative folder path
- Browse folders on the **Folders** tab
- Click a folder to filter the video grid
- Folder paths are relative (NAS paths never exposed to frontend)

### Scan status
- Scan runs in background (non-blocking)
- Real-time scan status: `idle | running | completed | failed`
- Animated indicator shows which file is being indexed
- Completion banner shows counts (scanned / added / updated / errors)

### Default sorting — Newest first
- Library defaults to newest videos first (`created_at desc`)
- Sort dropdown: Newest first, Oldest first, Title A-Z, Title Z-A, Duration, File size

### Open video in new tab
- All video cards open the watch page in a **new browser tab**
- Uses `<a target="_blank" rel="noopener noreferrer">`
- Right-click / copy link / open in new tab work as expected
- Library page stays open in original tab

## Required NAS folders

Create these folders on your NAS before first run:

```
/volume1/video_library              ← your video files (read-only)
/volume1/docker/video-player/data
/volume1/docker/video-player/thumbnails
/volume1/docker/video-player/cache
/volume1/docker/video-player/logs
```

## Project structure

```text
nas_video_player/
  backend/
    app/
      main.py
      config.py
      database.py
      models.py            # Video + WatchProgress models
      schemas.py
      scanner.py
      media_probe.py
      thumbnails.py
      streaming.py
      compatibility.py     # Browser compatibility detection
      scan_status.py       # In-process scan state tracker
      routes/
        health.py
        videos.py          # List, detail, thumbnail, stream
        scan.py            # POST scan, GET status, GET last-result
        progress.py        # Watch progress endpoints
        folders.py         # Folder listing
      utils/
        files.py
        logging_config.py
    tests/
      conftest.py
      test_compatibility.py
      test_files.py
      test_folders.py
      test_health.py
      test_progress.py
      test_scan_status.py
      test_scanner.py
      test_streaming.py
    requirements.txt
    Dockerfile
  frontend/
    src/
      main.tsx
      App.tsx
      api/
        client.ts
      pages/
        LibraryPage.tsx
        WatchPage.tsx
      components/
        VideoCard.tsx
        VideoPlayer.tsx
        SearchBar.tsx
        SortSelect.tsx
        CompatibilityBadge.tsx
        ScanStatusBar.tsx
      types/
        video.ts
      styles/
        global.css
    package.json
    vite.config.ts
    tsconfig.json
  docker/
    nginx.conf
    entrypoint.sh
  docker-compose.yml
  Dockerfile
  README.md
```

## Environment variables

| Variable             | Default              | Description                     |
|----------------------|----------------------|---------------------------------|
| `VIDEO_LIBRARY_PATH` | `/media/videos`      | Path to video library (mounted) |
| `DATABASE_PATH`      | `/app/data/app.db`   | SQLite database file path       |
| `THUMBNAILS_PATH`    | `/app/thumbnails`    | Thumbnails output directory     |
| `CACHE_PATH`         | `/app/cache`         | Cache directory                 |
| `LOGS_PATH`          | `/app/logs`          | Log file directory              |
| `APP_HOST`           | `0.0.0.0`            | Bind address                    |
| `APP_PORT`           | `8080`               | Bind port                       |
| `CHUNK_SIZE`         | `1048576`            | Streaming chunk size (bytes)    |

## Build and run

```bash
docker compose up -d --build
```

Open the app: `http://NAS_IP:8080`

> **Note:** If you are upgrading from Phase 1 (MVP), delete or clear the existing
> SQLite database (`/volume1/docker/video-player/data/app.db`) before starting.
> Phase 1.5 adds new columns and a new table which are not auto-migrated.

## How to use

1. Open `http://NAS_IP:8080`
2. Click **Scan Library** — scan runs in background; watch the status bar
3. Browse **All Videos** (newest first by default)
4. Use **Folders** tab to navigate by directory
5. Use **Continue Watching** tab to resume in-progress videos
6. Click any video card → opens watch page in a **new tab**
7. Video resumes from last position automatically
8. Close the tab — progress is saved

## API endpoints

### Videos
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/videos` | List videos (`q`, `folder`, `sort`, `order`) |
| `GET` | `/api/videos/{id}` | Video detail |
| `GET` | `/api/videos/{id}/thumbnail` | Video thumbnail |
| `GET` | `/api/videos/{id}/stream` | HTTP Range streaming |

### Watch progress
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/videos/{id}/progress` | Get watch progress |
| `PUT` | `/api/videos/{id}/progress` | Save watch progress |
| `GET` | `/api/videos/continue-watching` | In-progress videos |

### Folders
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/folders` | List folders with video counts |

### Scan
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/scan` | Start background scan |
| `GET` | `/api/scan/status` | Current scan status |
| `GET` | `/api/scan/last-result` | Last scan result |

### Misc
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |

## Sort options

The `sort` query param for `GET /api/videos`:

| Value | Description |
|-------|-------------|
| `created_at` (default) | When video was first indexed |
| `file_modified_at` | File system modification time |
| `indexed_at` | When video was last scanned |
| `title` | Alphabetical |
| `duration` | Video duration |
| `size` | File size |

Default: `sort=created_at&order=desc` (newest first).

## Browser compatibility rules

| Format | Status |
|--------|--------|
| MP4 + H.264 + AAC | ✓ direct_play |
| WebM + VP8/VP9/AV1 + Opus/Vorbis | ✓ direct_play |
| MOV, MKV | ⚠ may_not_play |
| HEVC/H.265, DTS audio | ✗ needs_conversion |
| AVI | ✗ needs_conversion |

## Running backend tests locally

```bash
cd backend
PYTHONPATH=. pytest
```

## Troubleshooting

### No videos shown after scan

- Check scan status for errors (scan bar shows error count)
- Verify `VIDEO_LIBRARY_PATH` is correctly mounted in `docker-compose.yml`
- Check logs: `/volume1/docker/video-player/logs/app.log`

### Video does not play

- Check the compatibility badge (yellow or red = may not play directly)
- Try an MP4/H.264/AAC file first
- Check browser console for errors

### Port 8080 already in use

- Change the host port in `docker-compose.yml`: e.g. `"8081:8080"`

### Thumbnails missing

- Check write permissions on `/volume1/docker/video-player/thumbnails`
- Check logs for `ffmpeg` errors
- Re-scan after fixing permissions

### Progress not saved

- Check browser console for network errors on `/api/videos/{id}/progress`
- Ensure the container is running (`docker compose ps`)

## Future roadmap

### Phase 2: HLS and transcoding
- HLS support for unsupported formats
- Background pre-transcoding
- `hls.js` in frontend

### Phase 3: User features
- Authentication and multiple users
- Per-user watch history

### Phase 4: Advanced media
- Subtitles (`.srt`, `.vtt`, embedded)
- Audio track selection
- Playlists

### Phase 5: Production hardening
- Scheduled automatic scan
- Reverse proxy and HTTPS support
- Backup/restore for SQLite
