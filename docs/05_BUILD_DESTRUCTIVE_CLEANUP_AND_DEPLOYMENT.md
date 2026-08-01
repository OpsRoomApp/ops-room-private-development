# OPS ROOM v0.25.47 — Build, Packaging, Cleanup & CI/CD

> **Exhaustive reference** for the complete build pipeline, destructive cleanup routines, release validation, installer generation, and packaging security rules.

**Version:** v0.25.47
**Last Updated:** 2026-07-31

---

## 1. Build Scripts

Two batch scripts in the source root (`opsroom-app/source/`):

### `BUILD OPS ROOM COMPLETE.bat`

Full production build pipeline executed sequentially:

```
1. Inject managed API keys (Lido, OpenAIP) into app/managed_keys.py
2. Verify RAAS audio module is importable
3. Build Camera Bridge 2024 (MSVC C++ — desktop_binding project)
4. PyInstaller packaging via OPS_ROOM.spec → dist/OPS ROOM/
5. Run tools/validate_v0256_public_release.py → 77 required checks
6. Generate SHA-256 checksum for the output ZIP
7. Run tools/write_update_manifest.py → update.json
8. Detect Inno Setup 7 → optional installer compilation
9. Report build summary (portable + installer paths)
```

### `BUILD WINDOWS APP ONLY.bat`

App-only build — skips Camera Bridge rebuild for faster iteration:

```
Same pipeline as COMPLETE but:
- Skips step 3 (Camera Bridge MSVC build)
- Uses existing camera_bridge_2024 binary from project root
```

### Error Handling

The build script uses `setlocal enabledelayedexpansion` and checks `!ERRORLEVEL!` after each step. On failure:
- The step name is printed in red with `[FAILED]`
- The build aborts immediately
- A summary of passed/failed checks is printed
- The `dist/` folder contents are preserved for debugging

---

## 2. PyInstaller Packaging (`OPS_ROOM.spec` — 127 lines)

### Configuration

```python
# One-folder bundle (not one-file — enables CleanBrowsingData)
a = Analysis(
    ['opsroom_launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('version.json', '.'),
        ('update.json', '.'),
        ('camera_bridge_2024.exe', '.'),
        ('app/static', 'app/static'),
        ('app/data/airports.csv', 'app/data'),
    ],
    hiddenimports=[
        'app.raas', 'app.raas_audio', 'app.charts',
        # + collect_submodules('uvicorn', 'websockets', 'SimConnect',
        #   'qrcode', 'reportlab', 'pystray', 'PIL')
        # + collect_all('pygame')
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)

pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(pyz, ...)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, ...)
```

### Key Details

- **Entry point:** `opsroom_launcher.py`
- **Bundle type:** One-folder (enables WebView2 `ClearBrowsingDataAsync` which requires writable profile directory)
- **Hidden imports:** All `app.*` submodules, `raas_audio`, third-party packages via `collect_submodules` and `collect_all`
- **Data includes:** `app/static/*` (entire frontend), `app/data/airports.csv` (60K airports), `version.json`, `update.json`, `camera_bridge_2024.exe`
- **Output:** `dist/OPS ROOM/OPS ROOM.exe`, `dist/OPS ROOM/OPS ROOM Camera Bridge 2024.exe`
- **ZIP artifact:** `dist/OPS_ROOM_v0_25_00_Public_Windows_x64.zip`

---

## 3. Update Manifest Generation (`tools/write_update_manifest.py`)

Generates the `update.json` manifest consumed by the dual-channel auto-updater.

### Parameters

```bash
python tools/write_update_manifest.py \
  --version "0.25.47" \
  --zip "dist/OPS_ROOM_v0_25_00_Public_Windows_x64.zip" \
  --out "update.json" \
  --repo "https://github.com/OpsRoomApp/ops-room-releases" \
  --channel "stable"
```

### Output Manifest Structure

```json
{
  "version": "0.25.47",
  "channel": "stable",
  "codename": "Release Migration",
  "release_date": "2026-07-31",
  "download_url": "https://opsroom.live/downloads/OPS_ROOM_v0_25_00_Public_Windows_x64.zip",
  "fallback_download_url": "https://github.com/OpsRoomApp/ops-room-releases/releases/download/v0.25.47/OPS_ROOM_v0_25_00_Public_Windows_x64.zip",
  "sha256": "AFA80454495CEE29F4CB92856F73EBB2C633DB46A4EA493F467365F0987CAC3D",
  "release_notes": "OPS ROOM v0.25.47 is available."
}
```

### SHA-256 Verification

The manifest generator computes SHA-256 of the entire ZIP file using streaming block hashing (1MB chunks). A `.sha256` sidecar file is written alongside the ZIP for integrity verification.

---

## 4. Release Validation Suite (`tools/validate_v0256_public_release.py`)

### Purpose

77 independent checks run before PyInstaller packaging proceeds. Each check is a named assertion — failures are printed with `FAIL:` prefixes and the failing detail.

### Check Categories

| Category | Count | Examples |
|---|---|---|
| **Version Consistency** | ~12 | All Python/JS/HTML/CSS/batch files reference `0.25.47`, no stale version strings |
| **Source Manifest** | ~4 | Manifest targets exact GitHub release, build placeholder present |
| **Static File Integrity** | ~6 | JavaScript syntax passes, CSS valid, HTML well-formed, no mojibake |
| **Black Box Renderers** | ~6 | Engines + Systems use HTML/SVG views, not canvas; drawBlackBox routes correctly |
| **Friendly Error Routing** | ~4 | Operational advisories route through `friendlyError`, raw exceptions excluded |
| **Recording Schema** | ~4 | Recording schema v2, FO stick fields appended, frontend Controls wired |
| **PMDG EULA Gate** | ~4 | PMDG SDK enforces EULA acceptance before snapshot/start |
| **Route Surface** | ~1 | **SKIP** — hardcoded route count assertion removed per 0.25.47 policy |
| **Build Script** | ~4 | Package name matches, manifest channel correct |
| **README Integrity** | ~4 | Public user guidance, no developer handoff text |
| **Python Compilation** | ~1 | `python -m compileall` passes |
| **JS Syntax** | ~2 | `node --check opsroom.js` and `node --check service-worker.js` pass |
| **UI/UX** | ~6 | Footer icons, focus-visible outline, Coffee icon present |
| **FSUIPC** | ~2 | FSUIPC log section in Black Box page |
| **Misc** | ~16 | Global focus rule, adapter provenance, cached registry, etc. |

### Example Output

```
PASS: version metadata is the stable v0.25.47 public release
PASS: source manifest targets the exact v0.25.47 GitHub release
PASS: runtime, launcher, diagnostics and system status target v0.25.47
...
SKIP: FastAPI route/OpenAPI surface check DISABLED
PASS: Python compileall passes
PASS: frontend JavaScript syntax passes
PASS: service worker JavaScript syntax passes

SUMMARY: 77/77 passed
```

---

## 5. Version Bump Synchronization

When bumping the version, update **every** location — a single inconsistency fails the build:

| File | Key / Pattern | Example Value |
|---|---|---|
| `app/main.py` | FastAPI version, diagnostics version, updater fallback | `"0.25.47"` |
| `app/charts.py` | ChartFox diagnostics version | `"0.25.47"` |
| `app/realworld.py` | Search engine version comment | `"0.25.47"` |
| `app/system_status.py` | System summary version | `"0.25.47"` |
| `app/updater.py` | `DEFAULT_VERSION` | `"0.25.47"` |
| `app/static/opsroom.js` | In-app version stamp | `"0.25.47"` |
| `app/static/opsroom.css` | Cache-buster comment | `/* v0.25.47 */` |
| `app/static/index.html` | Script/link cache-buster | `?v=0-25-00` |
| `app/static/service-worker.js` | SW version | `"0.25.47"` |
| `version.json` | Build manifest version | `"0.25.47"` |
| `update.json` | Update manifest version | `"0.25.47"` |
| `opsroom_launcher.py` | Launcher version | `"0.25.47"` |
| `README.md` | Public readme version | `v0.25.47` |
| `BUILD OPS ROOM COMPLETE.bat` | Package name, version stamps | `OPS_ROOM_v0_25_00_Public` |
| `BUILD WINDOWS APP ONLY.bat` | Package name, version stamps | `OPS_ROOM_v0_25_00_Public` |
| `tools/validate_*.py` | Validation target version | `"0.25.47"` |
| `tools/write_update_manifest.py` | Manifest version | `"0.25.47"` |
| `installer_script.iss` | Installer output name | `OPS_ROOM_Setup_v0_25_00.exe` |

### Cache-Busting

All static assets use query-string versioning:
```html
<script src="/static/opsroom.js?v=0-25-00"></script>
<link rel="stylesheet" href="/static/opsroom.css?v=0-25-00">
```

WebView2 cache is cleared at startup via `ClearBrowsingDataAsync()`.

---

## 6. Inno Setup 7 Integration (Optional)

After the PyInstaller portable build completes, `BUILD OPS ROOM COMPLETE.bat` detects Inno Setup 7 and optionally produces a Windows installer.

### Detection Paths

```
C:\Program Files\Inno Setup 7\ISCC.exe
C:\Program Files (x86)\Inno Setup 7\ISCC.exe
```

### Compilation

```bash
"%ISCC_PATH%" installer_script.iss
```

### Output

| Artifact | Path | Always Produced? |
|---|---|---|
| Portable folder | `dist/OPS ROOM/` | Yes |
| ZIP archive | `dist/OPS_ROOM_v0_25_00_Public_Windows_x64.zip` | Yes |
| Installer EXE | `dist_installer/OPS_ROOM_Setup_v0_25_00.exe` | Only if ISCC found |

### Installer Features

- 64-bit target: `%ProgramFiles%\OPS ROOM` (not `Program Files (x86)`)
- Desktop and Start Menu shortcuts
- Modern wizard style with dark theme customization
- LZMA2/ultra64 compression
- Uninstall support via Windows Add/Remove Programs
- **Additive only** — does not modify or replace portable `dist/OPS ROOM/`

---

## 7. Destructive Cleanup Scripts

### Build Artifact Cleanup

Run after every successful build to reclaim disk space:

```bash
rm -rf app/__pycache__ tools/__pycache__ dist build opsroom-temp .freebuff
```

### ChartFox Cache Cleanup

At startup, a background daemon thread purges stale ChartFox cache files:

```python
def _chartfox_cleanup():
    result = chartfox_force_cache_cleanup()
    # Removes old cached chart files (PDF/IMG) from app data directory
    # Deleted files count + bytes logged at INFO level
```

This prevents the app data directory from accumulating gigabytes of stale chart downloads across version updates.

### FSUIPC Log Mitigation

On startup, `FSUIPC7.ini` verbose log switches are silenced and oversized logs (>50MB) are truncated in-place without full-file copies, preventing multi-gigabyte log accumulation.

### Storage Maintenance (`app/storage_maintenance.py`)

```python
def clear_local_logs_cache(logs=True, diagnostics=True, map_cache=False):
    """Clear selectable cache categories."""
    # logs: opsroom.log rotation archives
    # diagnostics: cached diagnostic ZIPs
    # map_cache: OpenLayers tile cache (default off — expensive to rebuild)
```

---

## 8. Packaging Security Rules

### What IS baked into the build:
- Lido API key (injected at build time by the batch script)
- OpenAIP API key (injected at build time)
- Version manifest URLs (primary + fallback)
- `app/data/airports.csv` (60K airports — public data)
- `app/static/*` (entire frontend — public by design)
- ChartFox OAuth **client ID** (`019f9162-...` — public identifier, not a secret)

### What is NEVER baked into the build:
- `OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET` — live only on website VPS
- `GITHUB_CLIENT_SECRET` — live only on website VPS
- `JWT_SECRET` — live only on website VPS
- ChartFox OAuth **client secret** — exchanged server-side only
- Any database password, API private key, or credential string

### Pre-Release Verification

Before public distribution, verify:

```bash
# No plain-text secrets in any compiled file
grep -r "badgujarnishant" opsroom-app/     # Must return 0 matches
grep -r "HQbVw1jn" opsroom-app/            # Must return 0 matches
grep -r "OPSROOM_VPS_USER" opsroom-app/    # Must return 0 matches
grep -r "OPSROOM_VPS_PASS" opsroom-app/    # Must return 0 matches

# Version consistency
grep -r "0.25.47" --include="*.py" --include="*.js" --include="*.bat" --include="*.json" --include="*.html" --include="*.css"
# Must find all expected entries, with no stale version strings
```

---

## 9. Dual-Channel Auto-Updater Flow

```
App startup / manual check
        │
        ▼
GET https://opsroom.live/api/update.json
        │  (25s timeout)
        ├── Success ──▶ Parse manifest, compare versions
        │                    │
        │                    ├── Newer available ──▶ Offer download
        │                    └── Same/older ──────▶ No update
        │
        └── Fail (DNS, timeout, HTTP error, invalid JSON)
                │
                ▼
        GET https://raw.githubusercontent.com/OpsRoomApp/ops-room-releases/main/update.json
                │  (25s timeout)
                ├── Success ──▶ Parse manifest, compare versions
                └── Fail ────▶ UI: "Update check failed"
```

### Staged Update Installation

1. Download ZIP to temp directory
2. Verify SHA-256 against manifest
3. Extract to staging folder
4. Create `update_state.json` with staging path and version
5. Prompt user: "Update ready. Restart now?"
6. On restart: launcher checks `update_state.json`, swaps binaries, relaunches
