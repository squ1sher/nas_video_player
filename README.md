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

## Phase 2.6 Features (current)

### Maintenance Cleanup — Settings → Maintenance

A **Maintenance** page under Settings that analyzes and safely cleans stale generated data.

#### What it detects

| Category | Detail |
|---|---|
| Orphan HLS folders | `HLS_OUTPUT_PATH/{id}/` exists but no video record |
| HLS DB / file mismatch | DB says completed but `master.m3u8` / segments are missing |
| Orphan thumbnails | Thumbnail file exists but no video references it |
| Stale HLS jobs | Jobs stuck in `pending`/`running` for > 2 h |
| Stale duplicate records | Duplicate items pointing to deleted videos |
| Video availability breakdown | available / missing / source_disabled / source_removed |

#### Repair vs. Cleanup

| Action | Deletes files? | Changes DB? |
|---|---|---|
| **Repair HLS State** | Never | Yes – reconciles DB ↔ filesystem |
| **Cleanup** | Yes (only generated files) | Yes – removes stale records |

#### Cleanup safety rules

- **Original media files are NEVER deleted by generic cleanup**.
- By default, HLS cache for `source_removed` / `missing` videos is **not** selected.
- All cleanup goes through a dry-run plan → confirm → apply workflow.
- Optional/risky categories are labelled ⚠ and left unchecked by default.

### Video Deletion Cascade (fixed)

When a user deletes a video from the Watch page:

1. Original source file is deleted first.
2. If source file deletion fails (read-only mount / permissions):
   - Clear error is shown: "Failed to delete source file. Check Docker volume mode and Synology permissions."
   - Nothing else is removed (no HLS, no DB record).
3. If source file deletion succeeds:
   - HLS cache folder (`HLS_OUTPUT_PATH/{video_id}/`) is deleted.
   - Thumbnail file is deleted.
   - Active HLS jobs for the video are marked failed.
   - `VideoVariant`, `WatchProgress`, `DuplicateCandidateItem` DB rows are removed.
   - Video row is hard-deleted.

### Media Source Deletion Policy

When a media source is removed from Settings:

- **Original media files are NOT deleted.**
- **HLS cache is NOT deleted** — use Maintenance to clean up later if needed.
- Videos from that source are marked `availability_status = source_removed`.
- Marked videos are hidden from the normal library but remain in the DB.
- The Maintenance page shows source_removed video counts and allows optional HLS cleanup.

### Video Availability Status

New `availability_status` field on `Video`:

| Status | Meaning | Shown in library? |
|---|---|---|
| `NULL` / `available` | Source file exists, source enabled | ✅ Yes |
| `missing` | Source enabled but file not found on disk | ✅ Yes |
| `source_disabled` | Library root is disabled | ❌ Hidden |
| `source_removed` | Library root was deleted | ❌ Hidden |
| `deleted` | User deleted via app (for future use) | ❌ Hidden |

### Maintenance API

| Endpoint | Method | Description |
|---|---|---|
| `/api/maintenance/cleanup/summary` | GET | Summary of orphan/stale data |
| `/api/maintenance/cleanup/plan` | POST | Generate dry-run cleanup plan |
| `/api/maintenance/cleanup/apply` | POST | Apply selected plan items |



### Application Settings and configurable Media Sources
- New **Settings** page for managing media sources / library roots
- Mount one broad host folder once (for example `/volume1 -> /media`) and manage subfolders from the web UI
- Each media source stores:
  - name, path, enabled flag, recursive flag, scan priority
  - last scan time, last scan status, last error
- Media source paths are validated against optional `ALLOWED_MEDIA_ROOT_BASES`
- Backward compatibility: if no media sources exist yet, a default one is created from `VIDEO_LIBRARY_PATH`
- Indexed videos now store `library_root_id`, so identical relative paths can exist in different sources
- `MEDIA_LIBRARY_ROOTS` / `MEDIA_LIBRARY_ROOTS_JSON` are **optional bootstrap helpers only** (first startup)
- After startup, normal management should happen in **Settings -> Media Sources**

### Watch progress / Resume playback
- Global (single-user) watch progress saved in SQLite
- Progress saved every 5 seconds, on pause, and on page close
- Resume from saved position or start from beginning
- Videos marked **completed** when ≥ 90 % watched
- Continue Watching API remains available, but the main Library UI is now focused on browsing/watching only

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
- Library cards are thumbnail-first with a compact hover title overlay (metadata lines are not shown under thumbnails).
- The page renders an initial batch and uses a manual **Load more** button to reveal additional cards, reducing thumbnail load spikes.

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

### Playback Compatibility and library summary
- **Playback Compatibility** section (in Settings) provides high-level library health cards:
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

## Synology deployment and recovery
## UI organization (current)

- **Library** is now browsing-focused:
  - All Videos
  - Folders
  - compact search/sort controls
- **Settings** is operations-focused:
  - Media Sources
  - HLS / Streaming
  - Duplicates
  - Playback Compatibility
  - Maintenance
  - Tags
  - System / Runtime
- Active background processes are shown in a global bottom status bar (scan, HLS batch/jobs, duplicate scan).
- Library no longer contains Duplicates/Diagnostics process panels or large maintenance controls.
- Library cards stay thumbnail-first; hover overlay shows title and assigned tag paths.
- All Videos uses manual `Load more` to keep thumbnail loading lighter on NAS/browser.

### Hierarchical tags (v1)

- Tags are assigned from the **Watch** page (above the player).
- Tags are hierarchical (for example `Family/Alex`, `Travel/Spain/Mallorca`) and can be nested to any depth.
- **Settings -> Tags** manages the global tag tree (create child tags, rename, move, delete leaf tags).
- Library cards do not edit tags; they only display assigned tag paths in the hover overlay.
- Tag filtering/sorting in Library is planned for a later phase and is not included in v1.
- Deleting a video removes its tag associations.
- Deleting a tag removes associations for that tag but does not delete videos.


### Deployment folders

Host paths:

```
/volume1/docker/video-player/project
/volume1/docker/video-player/data
/volume1/docker/video-player/thumbnails
/volume1/docker/video-player/cache
/volume1/docker/video-player/cache/hls
/volume1/docker/video-player/logs
```

Container paths:

```
/app/data
/app/thumbnails
/app/cache
/app/cache/hls
/app/logs
/media
```

`docker-compose.yml` mounts media as `/volume1:/media:rw`.

### First install on Synology

```bash
cd /volume1
mkdir -p /volume1/docker/video-player
cd /volume1/docker/video-player
git clone https://github.com/squ1sher/nas_video_player.git project
cd project
bash scripts/bootstrap-synology.sh /volume1/docker/video-player
sudo docker compose up -d --build
```

### Recovery when project/runtime folders were deleted

If your shell is currently inside a deleted directory, Docker Compose fails with:

```text
getwd: no such file or directory
```

This means your current working directory no longer exists. Fix it by switching to a valid folder first, then restoring the project.

```bash
cd /volume1
mkdir -p /volume1/docker/video-player
cd /volume1/docker/video-player
git clone https://github.com/squ1sher/nas_video_player.git project
cd project
bash scripts/bootstrap-synology.sh /volume1/docker/video-player
sudo docker compose up -d --build
```

You can also use:

```bash
bash scripts/restore-project-from-git.sh /volume1/docker/video-player
```

Important: `scripts/bootstrap-synology.sh` recreates folders only. If `/volume1/docker/video-player/project` was deleted, you must clone/copy source files again.
Container startup bootstrap only manages runtime paths under `/app/*` after Docker starts; it cannot recreate a missing host project checkout before `docker compose` runs.

### Media source paths in UI

- Compose mount is host `/volume1` -> container `/media`.
- `/media` is the mounted browse root only. It is **not** auto-added as a media source and is **never** scanned directly.
- On first startup, **Media Sources is empty** until you add subfolders.
- In **Settings -> Media Sources**, browse `/volume1` and add subfolders such as:
  - `sclad/Movies`
  - `sclad/GoPro`
  - `video/Family`
- Internally, those resolve to container paths such as `/media/sclad/Movies`.
- Paths under `/volume1/docker/video-player` are blocked because they contain app/project/runtime files.

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
      services/
        library_root_service.py
      routes/
        health.py
        videos.py          # List, detail, thumbnail, stream
        scan.py            # POST scan, GET status, GET last-result
        settings.py        # Media sources / settings endpoints
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
        SettingsPage.tsx
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
  scripts/
    bootstrap-synology.sh
    restore-project-from-git.sh
  docker-compose.yml
  Dockerfile
  README.md
```

## Environment variables

| Variable             | Default              | Description                     |
|----------------------|----------------------|---------------------------------|
| `VIDEO_LIBRARY_PATH` | `/media`      | Mounted media browse root inside the container; not scanned automatically |
| `ALLOWED_MEDIA_ROOT_BASES` | `` | Comma-separated allowed container base paths for Settings → Media Sources (recommended: `/media`) |
| `MEDIA_LIBRARY_ROOTS` | `` | Optional bootstrap-only comma-separated media sources (advanced/optional; normal UI-based setup does not require this) |
| `MEDIA_LIBRARY_ROOTS_JSON` | `` | Optional bootstrap-only JSON alternative (advanced/optional; normal UI-based setup does not require this) |
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

### Host path vs container path (important)

- In `docker-compose.yml`, you map **host path -> container path**.
- The app mounts `/volume1` as `/media`, but the Settings UI is designed around **browsing `/volume1` and selecting subfolders**.
- The mounted root itself is not scanned. Add explicit subfolders only.

Example:
- Compose mapping: `/volume1:/media:rw`
- UI browse selection: `sclad/Movies`
- Internal container path: `/media/sclad/Movies`
- Mounted root (not allowed as source): `/media`

You do not need to edit `docker-compose.yml` for every new media subfolder; add subfolders from Settings instead.

> **Note:** If you are upgrading from Phase 1 (MVP), delete or clear the existing
> SQLite database (`/volume1/docker/video-player/data/app.db`) before starting.
> Phase 1.5 adds new columns and a new table which are not auto-migrated.

## How to use

1. Open `http://NAS_IP:8080`
2. Open **Settings** → **Media Sources**
3. Browse `/volume1` and add one or more subfolders (for example `sclad/Movies`)
4. Click **Scan Library** from Settings — scan runs in background; watch the global status bar
   - If no media sources are configured, the app shows:
     `No media sources configured. Add folders in Settings -> Media Sources.`
5. Browse **All Videos** (newest first by default)
6. Use **Folders** tab to navigate by media source and directory
7. Use **Settings** → **Duplicates** to run duplicate scan and review candidates
8. Use **Settings** → **Playback Compatibility** to review media profiles/manual playback status
9. Use **Settings** → **HLS / Streaming** for HLS repair and batch preparation
10. In **Folders**, expand folders inline to browse nested folders and play files without switching tabs
11. Click any video card or folder video item -> opens watch page in a **new tab**
12. Video resumes from last position automatically
13. Close the tab - progress is saved

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

### Settings / Media Sources
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/settings/media-sources` | List configured media sources |
| `GET` | `/api/settings/media-sources/browse?relative_path=` | Browse subdirectories under `/media` (displayed as `/volume1` in UI) |
| `POST` | `/api/settings/media-sources` | Create a media source |
| `GET` | `/api/settings/media-sources/{id}` | Get one media source |
| `PUT` | `/api/settings/media-sources/{id}` | Update a media source |
| `DELETE` | `/api/settings/media-sources/{id}` | Remove a media source config |
| `POST` | `/api/settings/media-sources/validate` | Validate a selected media subfolder before saving |
| `POST` | `/api/settings/media-sources/{id}/scan` | Start a library scan of all enabled sources |

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

### `getwd: no such file or directory` when running `docker compose`

- Cause: your current shell directory was deleted (commonly `/volume1/docker/video-player/project`).
- Docker Compose cannot run from a deleted working directory.
- Fix by changing to an existing directory, then restoring project files:

```bash
cd /volume1
mkdir -p /volume1/docker/video-player
cd /volume1/docker/video-player
git clone https://github.com/squ1sher/nas_video_player.git project
cd project
bash scripts/bootstrap-synology.sh /volume1/docker/video-player
sudo docker compose up -d --build
```

- If you already have project files restored, you can skip clone and run just the bootstrap script.

### Media Sources shows empty list on first startup

- This is the expected behavior.
- The app no longer auto-creates a `Default` source pointing at `/media`.
- Browse `/volume1` in **Settings → Media Sources** and add explicit subfolders such as `sclad/Movies`.
- `/media` is the mounted root only and is not scanned directly.

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
