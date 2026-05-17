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

## Phase 1.8 Features (current)

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
- Expand folders inline to see nested subfolders and direct video files
- Folder rows show nested folder count and recursive video count
- Videos in folder tree open watch page in a **new browser tab**
- Folder paths are relative (NAS paths never exposed to frontend)

### Scan status
- Scan runs in background (non-blocking)
- Real-time scan status: `idle | running | cancelling | cancelled | completed | failed | interrupted`
- Animated indicator shows which file is being indexed
- Completion banner shows counts (scanned / added / updated / errors)
- You can cancel an active scan from UI (`Cancel scan`); cancellation is graceful
- Cancelled scan does **not** perform missing-file cleanup
- If app/container restarts during scan, previous scan is marked `interrupted`; run scan again to complete state

### Probe-based media discovery
- Library scan now discovers media primarily via **ffprobe**, not only by extension allowlist
- Unknown extensions (for example `.360`) can be indexed when probing is enabled
- Uppercase extensions are normalized (for example `.MPG` -> `.mpg`)
- Files with probe failures can still appear as `probe_failed_possible_video`
- Non-browser-playable media is still shown in the library with compatibility badges

### Default sorting
- Library defaults to `Date` descending (`file_modified_at desc`)
- Sort controls in library UI: `Date`, `Duration`, `File size`
- Separate order toggle switches between ascending and descending

### Grouped All Videos UI
- **All Videos** now renders grouped sections based on the selected sort mode.
- Date sort: grouped by month and year (for example `May 2026`) using `file_modified_at` with fallbacks.
- Duration sort: `Under 3 minutes`, `3-20 minutes`, `Over 20 minutes`, `Unknown duration`.
- File size sort (GiB buckets): `Under 1 GB`, `1-20 GB`, `20-100 GB`, `Over 100 GB`, `Unknown size`.
- Grouping is applied after search and filters.
- Every group can be collapsed/expanded.

### Pre-generated HLS streaming (manual per-video)
- HLS variants are prepared **on demand** for a selected video.
- This phase does **not** use live transcoding during playback requests.
- Original video files are not modified, moved, or deleted by HLS preparation.
- HLS output is stored only under cache path:
  - Container: `/app/cache/hls`
  - NAS: `/volume1/docker/video-player/cache/hls`
- Quality targets:
  - `480p` (~1200k video, 96k audio)
  - `720p` (~2500k video, 128k audio)
  - `1080p` (~5000k video, 160k audio)
- Upscaling is disabled (qualities above source resolution are skipped).
- Default DS923+ recommendation: one HLS job at a time.

### Prepare HLS for the entire library (overnight)
- You can enqueue an overnight batch to prepare HLS for all indexed videos without completed HLS.
- Default behavior skips existing completed HLS (`skip_existing=true`).
- Original files are never modified; output is written only to HLS cache.
- Batch progress is stored in SQLite and survives page reload/browser close.
- Backend continues processing while browser is closed (as long as container is running).
- On process restart, previously running HLS jobs are marked interrupted/failed to avoid duplicate ffmpeg execution.
- Global queue and active batch progress are visible via `/api/hls/status` and batch detail endpoint.

### Open video in new tab
- All video cards open the watch page in a **new browser tab**
- Uses `<a target="_blank" rel="noopener noreferrer">`
- Right-click / copy link / open in new tab work as expected
- Library page stays open in original tab

### Duplicate candidate detection
- Separate **Scan Duplicates** action, independent from the normal library scan
- Finds **likely duplicate candidates** using a fast metadata fingerprint
- Does **not** read full files and does **not** calculate SHA256 in this phase
- Shows duplicate groups, confidence, reason, thumbnails, relative paths, and potential space saving
- Diagnostic only: duplicate scan does **not** delete, move, rename, or modify files

### Diagnostics tab and library summary
- New **Diagnostics** tab provides high-level library health cards:
  - Total indexed, Direct Play, May Play, May Not Play, Needs Conversion, Unknown
  - Probe Failed, Thumbnail Failed, Potential duplicate saving
- New backend summary endpoint: `GET /api/library/summary`
- Diagnostics sections list problematic files (probe failures, conversion-needed, unknown compatibility, thumbnail failures)
- Unsupported or unknown files remain visible for inspection; they are not hidden

### Single-file maintenance actions (safe)
- `POST /api/videos/{id}/reprobe` re-runs metadata probe for one file and updates diagnostic fields
- `POST /api/videos/{id}/thumbnail/regenerate` regenerates one thumbnail and records any ffmpeg error
- These actions are non-destructive: they do not modify original media content

### Media profile diagnostics and manual compatibility calibration
- Automatic compatibility is treated as an **auto guess**, not final truth.
- Scanner builds a stable media profile key using normalized metadata (extension, container, codecs, profile/level, pixel format, audio params, resolution bucket).
- Diagnostics now includes **Unique Media Profiles**:
  - one sample video per profile (open in new tab)
  - files count per profile
  - auto guess, manual profile status, effective status, source
- Manual profile status can be set to:
  - `playable`
  - `not_playable`
  - `partially_playable`
  - `unknown`
- Manual profile result overrides auto guess for all files linked to that media profile.
- This creates a practical compatibility matrix for your actual browser/device setup (for example `.360` profiles can be marked playable if they really work).

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
        folders/
          FolderTree.tsx
          FolderNode.tsx
          FolderVideoItem.tsx
      types/
        video.ts
      utils/
        groupVideos.ts
        buildFolderTree.ts
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
| `HLS_OUTPUT_PATH`    | `/app/cache/hls`     | HLS output directory            |
| `LOGS_PATH`          | `/app/logs`          | Log file directory              |
| `APP_HOST`           | `0.0.0.0`            | Bind address                    |
| `APP_PORT`           | `8080`               | Bind port                       |
| `CHUNK_SIZE`         | `1048576`            | Streaming chunk size (bytes)    |
| `MEDIA_DISCOVERY_MODE` | `probe`           | `extension_allowlist` \/ `probe` \/ `hybrid` |
| `EXCLUDED_EXTENSIONS` | `.txt,.nfo,...`    | Comma-separated excluded extensions |
| `MIN_MEDIA_FILE_SIZE_BYTES` | `1048576`   | Skip very small unknown files before probing |
| `PROBE_UNKNOWN_EXTENSIONS` | `true`      | Probe unknown extensions in `probe`/`hybrid` |
| `MAX_CONCURRENT_HLS_JOBS` | `1`        | Maximum simultaneous HLS preparation jobs |
| `HLS_SEGMENT_SECONDS` | `4`           | HLS segment length (seconds) |
| `HLS_FFMPEG_PRESET` | `veryfast`      | FFmpeg x264 preset for HLS preparation |
| `HLS_CRF` | `23`                    | FFmpeg CRF for HLS preparation |

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
6. Use **Duplicates** tab to review likely duplicate candidates
7. Click **Scan Duplicates** to run a separate duplicate scan
8. Use **Diagnostics** tab to inspect problematic files and quick-filter the library
 9. In **Folders**, expand folders inline to browse nested folders and play files without switching tabs
10. Click any video card or folder video item -> opens watch page in a **new tab**
11. Video resumes from last position automatically
12. Close the tab - progress is saved

## API endpoints

### Videos
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/videos` | List videos (`q`, `folder`, `sort`, `order`, diagnostics filters) |
| `GET` | `/api/videos/{id}` | Video detail |
| `GET` | `/api/videos/{id}/thumbnail` | Video thumbnail |
| `GET` | `/api/videos/{id}/stream` | HTTP Range streaming |
| `GET` | `/api/videos/{id}/playback-source` | Preferred playback source (`hls` or `original`) |
| `POST` | `/api/videos/{id}/reprobe` | Re-run ffprobe for one indexed file |
| `POST` | `/api/videos/{id}/thumbnail/regenerate` | Re-generate thumbnail for one file |
| `POST` | `/api/videos/{id}/hls/prepare` | Start HLS preparation for one video |
| `GET` | `/api/videos/{id}/hls/status` | HLS status for one video |
| `GET` | `/api/videos/{id}/hls/master.m3u8` | HLS master playlist |
| `GET` | `/api/videos/{id}/hls/{quality}/index.m3u8` | HLS quality playlist |
| `GET` | `/api/videos/{id}/hls/{quality}/{segment_name}` | HLS segment |

`GET /api/videos` additionally supports optional filters:
- `compatibility_status`
- `media_status`
- `probe_status`
- `thumbnail_status`
- `extension`
- `has_probe_error=true|false`
- `has_thumbnail=true|false`
- `media_profile_id`
- `compatibility_source`
- `effective_compatibility_status`

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
| `POST` | `/api/scan/cancel` | Request graceful cancellation of active scan |
| `GET` | `/api/scan/status` | Current scan status with discovery counters |
| `GET` | `/api/scan/last-result` | Last scan result |

### Library diagnostics
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/library/summary` | Aggregated library diagnostics + last scan snapshots |

### Media profiles
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/media-profiles` | List unique media profiles with sample video and file counts |
| `GET` | `/api/media-profiles/{id}` | Profile detail + paginated profile videos |
| `PUT` | `/api/media-profiles/{id}/playback-status` | Set manual profile playback status |
| `DELETE` | `/api/media-profiles/{id}/playback-status` | Clear manual profile playback status |

### Duplicates
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/duplicates/scan` | Start duplicate candidate scan (strict mode) |
| `GET` | `/api/duplicates/status` | Current duplicate scan status |
| `GET` | `/api/duplicates/groups` | Latest duplicate candidate groups |
| `GET` | `/api/duplicates/summary` | Latest duplicate summary |

### Misc
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/hls/jobs` | Recent HLS jobs |
| `GET` | `/api/hls/status` | Global HLS queue status |
| `GET` | `/api/hls/diagnostics` | HLS consistency diagnostics (DB state vs HLS files on disk) |
| `POST` | `/api/hls/repair` | Reconcile/repair HLS DB state against files on disk |
| `POST` | `/api/hls/batches/library` | Enqueue overnight HLS for library videos (skip existing by default) |
| `GET` | `/api/hls/batches/{batch_id}` | HLS batch status and optional filtered items |
| `POST` | `/api/hls/batches/{batch_id}/cancel` | Cancel queued part of an active HLS batch |

### Library-wide HLS request example

```json
{
  "qualities": ["480p", "720p", "1080p"],
  "skip_existing": true,
  "force": false,
  "only_missing_hls": true
}
```

- `skip_existing=true` by default.
- `MAX_CONCURRENT_HLS_JOBS=1` by default (recommended for DS923+).

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

## Duplicate detection mode

Duplicate detection in Phase 1.5 is a **fast preliminary fingerprint**, not byte-level proof.

It uses already indexed metadata such as:
- file size
- duration
- width / height
- video codec
- audio codec
- extension / container

### Strict mode
- Same file size
- Same rounded duration
- Same width
- Same height

Use this mode first when you want the safest candidate groups.


### Important limitation
- Duplicate detection is **candidate-based only** in this phase
- It does **not** guarantee files are byte-identical
- A future phase may add optional SHA256 hashing for exact confirmation

## Status fields in diagnostics

- `media_status` tells scanner/media-detection outcome:
  - `detected_video`
  - `probe_failed_possible_video`
- `probe_status` describes metadata probe execution:
  - `success`
  - `failed`
  - `skipped`
- `compatibility_status` tells browser playback expectation separately:
  - `direct_play`
  - `may_play`
  - `may_not_play`
  - `needs_conversion`
  - `unknown`
- `thumbnail_status` describes thumbnail generation:
  - `generated`
  - `failed`
  - `pending`
  - `skipped`

`compatibility_source` explains which status is currently effective:
- `manual_profile_override`
- `auto_heuristic`
- `unknown`

This separation means the library can include files like `.mpg` / `.mpeg` / `.360` even when browser playback is uncertain.

## Why unsupported files are still shown

- Visibility is intentional: unknown/unsupported files are retained so you can inspect probe errors and compatibility reasons.
- Diagnostics helps decide what to re-probe, what needs conversion, and what can be ignored safely.
- Phase 1.6 does not add transcoding, HLS, move/rename, or delete workflows for these diagnostics actions.

Phase 1.7 keeps the same safety model:
- no file deletion in diagnostics calibration workflow
- no move/rename
- no file content modification
- no HLS/transcoding in this phase

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
- Batch HLS preparation
- Scheduled overnight HLS preparation
- HLS cache cleanup policies
- Favorites / watch later / playlists / tags / manual metadata

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
