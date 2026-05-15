# Local NAS Video Player (MVP)

Mini-YouTube style local web video player for Synology NAS.

- Backend: FastAPI + SQLite + ffprobe/ffmpeg
- Frontend: React + Vite + TypeScript
- Deployment: single Docker container via Docker Compose
- Network scope: local network only (no auth in MVP)

## Target NAS

- Synology DS923+
- DSM 7.2.2+ (tested target: 7.2.2-72806 Update 5)
- Synology Container Manager (Docker Compose)

## Required NAS folders

Create these folders on NAS:

- `/volume1/video_library`
- `/volume1/docker/video-player/data`
- `/volume1/docker/video-player/thumbnails`
- `/volume1/docker/video-player/cache`
- `/volume1/docker/video-player/logs`

## Project structure

```text
video-player/
  backend/
    app/
      main.py
      config.py
      database.py
      models.py
      schemas.py
      scanner.py
      media_probe.py
      thumbnails.py
      streaming.py
      routes/
        health.py
        videos.py
        scan.py
      utils/
        files.py
        logging_config.py
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
  .env.example
  .gitignore
```

## Environment variables

See `.env.example`:

- `VIDEO_LIBRARY_PATH=/media/videos`
- `DATABASE_PATH=/app/data/app.db`
- `THUMBNAILS_PATH=/app/thumbnails`
- `CACHE_PATH=/app/cache`
- `LOGS_PATH=/app/logs`
- `APP_HOST=0.0.0.0`
- `APP_PORT=8080`
- `CHUNK_SIZE=1048576`

## Build and run

From project root:

```bash
docker compose up -d --build
```

Open app:

- `http://NAS_IP:8080`

## Local development notes

- For local frontend build, use Node.js 18+ (recommended 20+).
- Docker image already uses Node 20 in build stage, so NAS deployment is unaffected by local Node version.

## How to scan library

1. Open homepage.
2. Click **Scan Library**.
3. Wait for completion message.
4. Videos appear as cards.
5. Click a card to open watch page.

## API endpoints

- `GET /api/health`
- `POST /api/scan`
- `GET /api/videos?q=&sort=&order=`
- `GET /api/videos/{video_id}`
- `GET /api/videos/{video_id}/thumbnail`
- `GET /api/videos/{video_id}/stream` (HTTP Range supported)

## Direct-play formats in MVP

- `.mp4`
- `.m4v`
- `.mov`
- `.mkv`
- `.avi`
- `.webm`

## Known MVP limitations

- No login/password
- Local network only
- No live transcoding
- Browser may not play some MKV/AVI/HEVC files
- No subtitles yet
- No users
- No playlists

## Troubleshooting

### Container cannot access video folder

- Check volume mapping: `/volume1/video_library:/media/videos:ro`
- Verify folder permissions for Container Manager
- Ensure videos are actually inside `/volume1/video_library`

### Port 8080 already in use

- Change host port in `docker-compose.yml`, e.g. `8081:8080`
- Restart compose stack

### ffprobe failed

- Check logs in `/volume1/docker/video-player/logs/app.log`
- Ensure source file is not corrupted
- Ensure container image includes `ffmpeg` package

### Video does not play in browser

- Check browser codec support
- Try MP4/H.264/AAC files first
- Confirm stream endpoint response headers include range headers

### Thumbnails missing

- Check write access to `/volume1/docker/video-player/thumbnails`
- Check `ffmpeg` errors in app logs
- Trigger scan again after fixing permissions

## Running backend tests locally

```bash
cd backend
PYTHONPATH=. pytest
```

## Future roadmap

### Phase 2: Better library

- Scheduled automatic scan
- Folder navigation
- Tags and favorites
- Continue watching / watch history
- Recently added and better sorting/filtering
- Duplicate detection and metadata editing

### Phase 3: HLS and compatibility

- HLS support for unsupported direct-play formats
- `hls.js` in frontend
- Background pre-transcoding profiles (1080p/720p/480p)
- Caching strategy to avoid live transcoding on weak NAS

### Phase 4: User features

- Authentication and multiple users
- Per-user watch history
- Parental control and private videos
- User preferences

### Phase 5: Advanced media

- Subtitles (`.srt`, `.vtt`, embedded extraction)
- Audio track selection
- Chapters and timeline previews
- Resume playback
- Playlists and smart collections

### Phase 6: Production hardening

- Background worker and queue
- Task status API
- Better error reporting
- Backup/restore for SQLite
- Reverse proxy and HTTPS support
- Optional secure external access

### Phase 7: Mobile/TV experience

- PWA support
- Better mobile UI
- TV browser controls and remote navigation

