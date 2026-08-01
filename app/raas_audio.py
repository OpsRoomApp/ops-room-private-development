from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from itertools import count
from pathlib import Path
from typing import Any, Iterable

from .settings_store import app_data_dir, load_settings, save_settings

_LOCK = threading.RLock()
_QUEUE: queue.PriorityQueue[tuple[int, int, dict[str, Any]]] = queue.PriorityQueue(maxsize=50)
_COUNTER = count()
_THREAD: threading.Thread | None = None
_RUNNING = False
_PYGAME_CHANNEL_INDEX = 6
_LAST_TTS_ERROR = ""
_LAST_CLIP_ERROR = ""
_LAST_BACKEND_USED = ""
_TTS_CACHE_READY = False
_TTS_CACHE_ERROR = ""
_TTS_CACHE_TEXT = "Runway Awareness OK"
_TTS_CACHE_FILE = "raas_test_ok.wav"
_SOUND_CACHE: dict[str, Any] = {}
_LAST: dict[str, Any] = {
    "ok": True,
    "state": "STANDBY",
    "message": "RAAS audio engine not started",
    "mode": "host_pc_system_audio",
    "voice_pack": "not scanned",
}

# User-provided segmented phrase-pack names. OPS ROOM detects the local files,
# not a hard-coded archive layout, so one missing optional phrase never rejects
# the whole pack.
CLIP_KEYS = {
    "0": "0.opus", "1": "1.opus", "2": "2.opus", "3": "3.opus", "4": "4.opus",
    "5": "5.opus", "6": "6.opus", "7": "7.opus", "8": "8.opus", "9": "9.opus",
    "30": "30.opus", "rwy": "rwy.opus", "rwys": "rwys.opus", "on_rwy": "on_rwy.opus",
    "on_twy": "on_twy.opus", "twy": "twy.opus", "left": "left.opus", "right": "right.opus",
    "center": "center.opus", "rmng": "rmng.opus", "feet": "feet.opus", "meters": "meters.opus",
    "hundred": "hundred.opus", "thousand": "thousand.opus", "caution": "caution.opus",
    "short_rwy": "short_rwy.opus", "too_high": "too_high.opus", "too_fast": "too_fast.opus",
    "unstable": "unstable.opus", "long_land": "long_land.opus", "deep_land": "deep_land.opus",
    "apch": "apch.opus", "avail": "avail.opus", "alt_set": "alt_set.opus", "flaps": "flaps.opus",
    "pause": "pause.opus",
}

OPTIONAL_CLIPS = sorted(set(CLIP_KEYS.values()))
_DETECTION_MARKERS = {
    "0.opus", "1.opus", "2.opus", "3.opus", "4.opus", "5.opus", "6.opus", "7.opus", "8.opus", "9.opus",
    "rwy.opus", "on_rwy.opus", "apch.opus", "caution.opus", "feet.opus", "rmng.opus",
}
_URGENT_PRIORITIES = {"critical", "urgent", "caution", "operational"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resource_roots() -> list[Path]:
    """Likely runtime roots in source, PyInstaller one-folder, and PyInstaller temp layouts.

    v0.23.34 could still miss the bundled phrase pack when the packaged app
    resolved resources under _internal/_MEIPASS differently from source mode.
    Keep this broad but deterministic.
    """
    roots: list[Path] = []
    for raw in (
        _repo_root(),
        Path(__file__).resolve().parents[0],
        Path.cwd(),
        Path(sys.executable).resolve().parent if getattr(sys, "executable", None) else None,
        Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", None) else None,
    ):
        if raw:
            try:
                roots.append(Path(raw).resolve())
            except Exception:
                roots.append(Path(raw))
    # If executable is the visible OPS ROOM folder, resources may sit below
    # _internal. If the current file is already in _internal/app, parents cover it.
    expanded: list[Path] = []
    for root in roots:
        expanded.extend([root, root / "_internal", root.parent, root.parent / "_internal"])
    out: list[Path] = []
    seen: set[str] = set()
    for root in expanded:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            out.append(root)
    return out


def _ensure_voice_dirs() -> None:
    # Create only the known defaults. Do not mutate a user-selected path by
    # appending female/ again, because the selected folder may already be the
    # final clip folder.
    for path in [app_data_dir() / "raas_voice" / "female", app_data_dir() / "RAAS" / "female"]:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def _repair_windows_path_text(raw: str) -> str:
    """Normalize a path received from the browser/settings layer.

    The real bug seen in v0.23.34 was that the UI could show a plausible
    Windows path while the backend never proved which path it actually scanned.
    Keep this conservative: reject display placeholders, but preserve normal
    backslashes and spaces exactly.
    """
    text = os.path.expandvars(str(raw or "").strip().strip('"').strip("'"))
    if not text:
        return ""
    if "..." in text or "<" in text or ">" in text:
        return ""
    # Remove accidental control characters without destroying valid Windows
    # backslash sequences that arrived through JSON.stringify correctly.
    text = "".join(ch for ch in text if ch == "\t" or ch >= " ").strip()
    return text


def _path_variants(raw: str) -> list[Path]:
    text = _repair_windows_path_text(raw)
    if not text:
        return []
    p = Path(text).expanduser()
    variants = [p]
    # Accept C:\...\raas_voice and C:\...\raas_voice\female, but never generate
    # C:\...\female\female.
    if p.name.lower() != "female":
        variants.append(p / "female")
    # Also check one level below the selected path. This catches unpacked voice
    # packs that contain a nested female/ folder without changing the saved path.
    try:
        if p.is_dir():
            for child in p.iterdir():
                if child.is_dir() and child.name.lower() == "female":
                    variants.append(child)
                elif child.is_dir():
                    nested = child / "female"
                    if nested.is_dir():
                        variants.append(nested)
    except Exception:
        pass
    return variants


def _candidate_voice_dirs() -> list[Path]:
    _ensure_voice_dirs()
    roots: list[Path] = []
    try:
        configured = str(load_settings().get("integrations", {}).get("raas_voice_path", "") or "")
    except Exception:
        configured = ""
    env = os.getenv("OPSROOM_RAAS_VOICE_PATH", "")
    for raw in (configured, env):
        roots.extend(_path_variants(raw))

    user_profile = os.getenv("USERPROFILE") or str(Path.home())
    user_local = Path(user_profile) / "AppData" / "Local" / "Ops Room"
    roots.extend([
        app_data_dir() / "raas_voice" / "female",
        app_data_dir() / "raas_voice",
        app_data_dir() / "RAAS" / "female",
        app_data_dir() / "RAAS",
        user_local / "raas_voice" / "female",
        user_local / "raas_voice",
        user_local / "RAAS" / "female",
        user_local / "RAAS",
    ])

    for root in _resource_roots():
        roots.extend([
            root / "app" / "static" / "audio" / "raas" / "female",
            root / "app" / "static" / "audio" / "raas",
            root / "static" / "audio" / "raas" / "female",
            root / "static" / "audio" / "raas",
            root / "audio" / "raas" / "female",
            root / "audio" / "raas",
        ])

    out: list[Path] = []
    seen: set[str] = set()
    for p in roots:
        try:
            key = str(p.resolve()).lower()
        except Exception:
            key = str(p).lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out

def _clip_files_in(path: Path) -> list[Path]:
    try:
        if not path.is_dir():
            return []
        return sorted([p for p in path.glob("*.opus") if p.is_file()], key=lambda x: x.name.lower())
    except OSError:
        return []


def _detect_clip_dir(path: Path) -> Path | None:
    """Return the real folder containing *.opus clips for a candidate path."""
    if _clip_files_in(path):
        return path
    try:
        if not path.is_dir():
            return None
        # Prefer female/ if present, then any direct child with a usable pack,
        # then one additional nested female/ level for unpacked archives.
        preferred = [path / "female", path / "Female", path / "FEMALE"]
        for child in preferred:
            if _clip_files_in(child):
                return child
        for child in sorted((p for p in path.iterdir() if p.is_dir()), key=lambda x: x.name.lower()):
            if _clip_files_in(child):
                return child
        for child in sorted((p for p in path.iterdir() if p.is_dir()), key=lambda x: x.name.lower()):
            nested = child / "female"
            if _clip_files_in(nested):
                return nested
    except OSError:
        return None
    return None


def _scan_dir(path: Path) -> dict[str, Any]:
    try:
        is_dir = path.is_dir()
    except OSError as exc:
        return {"path": str(path), "is_dir": False, "clip_dir": "", "clip_count": 0, "present": [], "error": f"{type(exc).__name__}: {exc}"}
    if not is_dir:
        return {"path": str(path), "is_dir": False, "clip_dir": "", "clip_count": 0, "present": [], "error": "folder does not exist"}
    clip_dir = _detect_clip_dir(path)
    if not clip_dir:
        return {"path": str(path), "is_dir": True, "clip_dir": "", "clip_count": 0, "present": [], "marker_count": 0, "missing_optional_clips": OPTIONAL_CLIPS, "error": "no .opus clips found in this folder, female/, child folders, or one-level nested female/"}
    error = ""
    try:
        files = _clip_files_in(clip_dir)
        names = sorted({p.name.lower() for p in files})
    except OSError as exc:
        names = []
        error = f"{type(exc).__name__}: {exc}"
    present = sorted(set(names) & set(OPTIONAL_CLIPS))
    data = {
        "path": str(path),
        "is_dir": True,
        "clip_dir": str(clip_dir),
        "clip_count": len(names),
        "present": present,
        "marker_count": len(set(names) & _DETECTION_MARKERS),
        "missing_optional_clips": sorted(set(OPTIONAL_CLIPS) - set(names)),
    }
    if error:
        data["error"] = error
    return data

def _voice_dir() -> Path | None:
    best: tuple[int, int, Path] | None = None
    for path in _candidate_voice_dirs():
        data = _scan_dir(path)
        clip_count = int(data.get("clip_count") or 0)
        marker_count = int(data.get("marker_count") or 0)
        clip_dir_text = str(data.get("clip_dir") or "")
        # Detection is intentionally permissive: actual .opus files plus known
        # phrase names are enough. Do not require one old fixed list.
        if clip_dir_text and clip_count >= 4 and marker_count >= 1:
            clip_dir = Path(clip_dir_text)
            # Prefer configured/app-data packs over bundled fallback when tied.
            configured_boost = 1 if str(path).lower() in str(clip_dir).lower() else 0
            score = (marker_count + configured_boost, clip_count)
            if best is None or score > (best[0], best[1]):
                best = (score[0], score[1], clip_dir)
    return best[2] if best else None

def _archive_hint() -> str:
    # Public packages do not bundle voice-pack archives. Only report a local
    # user-provided archive if the user placed one in AppData.
    for p in [app_data_dir() / "raas_voice" / "voice_pack.rar"]:
        if p.is_file():
            return str(p)
    return ""


def _audio_backend_status() -> dict[str, Any]:
    secure = os.name == "nt"
    pygame_available = False
    pygame_error = ""
    try:
        import pygame  # type: ignore  # noqa: F401
        pygame_available = True
    except Exception as exc:
        pygame_error = f"{type(exc).__name__}: {exc}"
    return {
        "windows": secure,
        "powershell": "available" if secure else "unavailable",
        "tts": "Windows System.Speech" if secure else "display-only outside Windows",
        "pygame_mixer": "available" if pygame_available else f"unavailable: {pygame_error}" if pygame_error else "unavailable",
        "opus_playback": "pygame SDL_mixer Opus, with Windows MediaPlayer fallback" if pygame_available else ("Windows MediaPlayer fallback only" if secure else "unavailable outside Windows"),
        "ffmpeg": shutil.which("ffmpeg") or shutil.which("ffmpeg.exe") or "not bundled / not on PATH",
        "priority_queue": True,
        "urgent_lane": True,
        "last_backend_used": _LAST_BACKEND_USED,
        "last_tts_error": _LAST_TTS_ERROR,
        "last_clip_error": _LAST_CLIP_ERROR,
        "tts_cache_ready": _TTS_CACHE_READY,
        "tts_cache_error": _TTS_CACHE_ERROR,
        "tts_cache_path": str(_tts_cache_path(_TTS_CACHE_TEXT) or ""),
    }


def _update(state: str, message: str, **extra: Any) -> None:
    global _LAST
    with _LOCK:
        _LAST = {
            "ok": True,
            "state": state,
            "message": message,
            "mode": "host_pc_system_audio",
            "updated_at_monotonic": time.monotonic(),
            **extra,
        }


def _audio_cache_dir() -> Path:
    path = app_data_dir() / "raas_audio_cache"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return path


def _tts_cache_path(text: str) -> Path | None:
    # Only cache the manual test phrase for now. Operational callouts should use
    # phrase-pack clips, and arbitrary synthesized text should not create many
    # files on the user's machine.
    if str(text or "").strip().lower() != _TTS_CACHE_TEXT.lower():
        return None
    return _audio_cache_dir() / _TTS_CACHE_FILE


def _build_tts_cache(text: str) -> tuple[bool, str]:
    path = _tts_cache_path(text)
    if path is None:
        return False, "not cacheable"
    if path.is_file() and path.stat().st_size > 1024:
        return True, ""
    if os.name != "nt":
        return False, "not running on Windows"
    payload = json.dumps(str(path))
    escaped_payload = payload.replace("'", "''")
    clean = str(text or "").replace("'", "''")[:180]
    script = (
        "try { "
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.Rate = -1; $s.Volume = 100; "
        f"$f = ConvertFrom-Json '{escaped_payload}'; "
        "$s.SetOutputToWaveFile($f); "
        f"$s.Speak('{clean}'); "
        "$s.Dispose(); exit 0 } catch { Write-Error $_; exit 1 }"
    )
    ok, err = _run_powershell(script, timeout=12)
    if ok and path.is_file() and path.stat().st_size > 1024:
        return True, ""
    return False, err or "TTS cache was not created"


def _warm_tts_cache_async() -> None:
    def worker() -> None:
        global _TTS_CACHE_READY, _TTS_CACHE_ERROR
        ok, err = _build_tts_cache(_TTS_CACHE_TEXT)
        _TTS_CACHE_READY = ok
        _TTS_CACHE_ERROR = "" if ok else err
    try:
        threading.Thread(target=worker, name="OpsRoom-RAASTTSWarmup", daemon=True).start()
    except Exception:
        pass


def _run_powershell(script: str, timeout: float = 12.0) -> tuple[bool, str]:
    if os.name != "nt":
        return False, "not running on Windows"
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            return True, ""
        err = (result.stderr or result.stdout or f"PowerShell exited {result.returncode}").strip()
        return False, err[:260]
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _speak_tts(text: str) -> bool:
    global _LAST_TTS_ERROR, _LAST_BACKEND_USED, _TTS_CACHE_READY, _TTS_CACHE_ERROR
    clean = str(text or "").replace("'", "''")[:180]
    if not clean:
        return False
    cached = _tts_cache_path(text)
    if cached is not None:
        if not (cached.is_file() and cached.stat().st_size > 1024):
            ok_cache, err_cache = _build_tts_cache(text)
            _TTS_CACHE_READY = ok_cache
            _TTS_CACHE_ERROR = "" if ok_cache else err_cache
        if cached.is_file() and cached.stat().st_size > 1024 and _play_clip(cached):
            _LAST_BACKEND_USED = "cached Windows TTS WAV"
            _LAST_TTS_ERROR = ""
            return True
    script = (
        "try { "
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.Rate = -1; $s.Volume = 100; "
        f"$s.Speak('{clean}'); "
        "$s.Dispose(); exit 0 } catch { exit 1 }"
    )
    ok, err = _run_powershell(script, timeout=12)
    _LAST_BACKEND_USED = "Windows System.Speech TTS" if ok else _LAST_BACKEND_USED
    _LAST_TTS_ERROR = "" if ok else err
    return ok


def _play_clip_pygame(path: Path) -> bool:
    """Play an Ogg/Opus phrase through pygame/SDL_mixer when available.

    The packaged OPS ROOM build already bundles pygame for the announcement
    system. SDL_mixer builds used by pygame normally include Ogg/Opus support,
    which is more reliable than asking Windows MediaPlayer to decode .opus.
    """
    global _LAST_CLIP_ERROR, _LAST_BACKEND_USED
    try:
        import pygame  # type: ignore
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        if pygame.mixer.get_num_channels() <= _PYGAME_CHANNEL_INDEX:
            pygame.mixer.set_num_channels(_PYGAME_CHANNEL_INDEX + 2)
        cache_key = str(path.resolve())
        sound = _SOUND_CACHE.get(cache_key)
        if sound is None:
            sound = pygame.mixer.Sound(str(path))
            _SOUND_CACHE[cache_key] = sound
        channel = pygame.mixer.Channel(_PYGAME_CHANNEL_INDEX)
        channel.play(sound)
        deadline = time.monotonic() + max(0.25, min(2.5, float(sound.get_length() or 1.0) + 0.35))
        while channel.get_busy() and time.monotonic() < deadline:
            time.sleep(0.015)
        _LAST_BACKEND_USED = "pygame SDL_mixer"
        _LAST_CLIP_ERROR = ""
        return True
    except Exception as exc:
        _LAST_CLIP_ERROR = f"pygame: {type(exc).__name__}: {exc}"
        return False


def _play_clip(path: Path) -> bool:
    global _LAST_CLIP_ERROR, _LAST_BACKEND_USED
    if not path.is_file() or os.name != "nt":
        _LAST_CLIP_ERROR = "clip missing or non-Windows host"
        return False
    if _play_clip_pygame(path):
        return True
    payload = json.dumps(str(path))
    escaped_payload = payload.replace("'", "''")
    script = (
        "try { Add-Type -AssemblyName PresentationCore; "
        f"$f = ConvertFrom-Json '{escaped_payload}'; "
        "$p = New-Object System.Windows.Media.MediaPlayer; "
        "$p.Open([Uri]$f); $p.Play(); "
        "$timeout = [DateTime]::UtcNow.AddMilliseconds(1250); "
        "while([DateTime]::UtcNow -lt $timeout){ Start-Sleep -Milliseconds 40 }; "
        "$p.Close(); exit 0 } catch { exit 1 }"
    )
    ok, err = _run_powershell(script, timeout=4)
    if ok:
        _LAST_BACKEND_USED = "Windows MediaPlayer"
        _LAST_CLIP_ERROR = ""
    else:
        _LAST_CLIP_ERROR = (_LAST_CLIP_ERROR + "; " if _LAST_CLIP_ERROR else "") + f"media player: {err}"
    return ok


def _runway_tokens(runway: str) -> list[tuple[str, str]]:
    text = str(runway or "").strip().upper().replace("RWY", "").replace("RUNWAY", "")
    suffix = ""
    if text.endswith("L"):
        suffix = "left"; text = text[:-1]
    elif text.endswith("R"):
        suffix = "right"; text = text[:-1]
    elif text.endswith("C"):
        suffix = "center"; text = text[:-1]
    text = text.zfill(2)[-2:]
    out = [(ch, ch) for ch in text]
    if suffix:
        out.append((suffix, suffix))
    return out


def _number_tokens(value: int) -> list[tuple[str, str]]:
    value = max(0, int(value))
    tokens: list[tuple[str, str]] = []
    if value >= 1000:
        thousands = value // 1000
        remainder = value % 1000
        tokens.extend((ch, ch) for ch in str(thousands))
        tokens.append(("thousand", "thousand"))
        if remainder:
            if remainder >= 100 and remainder % 100 == 0:
                tokens.extend((ch, ch) for ch in str(remainder // 100))
                tokens.append(("hundred", "hundred"))
            else:
                tokens.extend((ch, ch) for ch in str(remainder))
        return tokens
    if value >= 100 and value % 100 == 0:
        tokens.extend((ch, ch) for ch in str(value // 100))
        tokens.append(("hundred", "hundred"))
        return tokens
    return [(ch, ch) for ch in str(value)]


def _distance_tokens(value: int) -> list[tuple[str, str]]:
    value = max(0, int(round(value / 100.0) * 100))
    return _number_tokens(value)


def _segments_for(event_type: str, runway: str = "", distance_ft: int | None = None, distance_value: int | None = None, distance_unit: str = "feet") -> list[tuple[str, str]]:
    typ = str(event_type or "").lower()
    if typ == "test":
        return []
    if typ == "approaching_runway":
        return [("apch", "approaching"), ("rwy", "runway"), *_runway_tokens(runway)]
    if typ == "on_runway":
        return [("on_rwy", "on runway"), *_runway_tokens(runway)]
    if typ == "taxiway_takeoff":
        return [("caution", "caution"), ("on_twy", "taxiway")]
    if typ == "short_runway":
        return [("caution", "caution"), ("short_rwy", "short runway")]
    if typ == "remaining":
        unit = "meters" if str(distance_unit or "").lower().startswith(("m", "met")) else "feet"
        value = int(distance_value) if isinstance(distance_value, int) else int(distance_ft or 0)
        return [*_distance_tokens(value), (unit, unit), ("rmng", "remaining")]
    if typ == "unstable":
        return [("unstable", "unstable")]
    if typ == "too_fast":
        return [("too_fast", "too fast")]
    if typ == "too_high":
        return [("too_high", "too high")]
    if typ == "long_landing":
        return [("long_land", "long landing")]
    if typ == "deep_landing":
        return [("deep_land", "deep landing")]
    return []


def _play_segmented_callout(event_type: str, text: str, runway: str = "", distance_ft: int | None = None, distance_value: int | None = None, distance_unit: str = "feet") -> tuple[bool, bool, list[str]]:
    base = _voice_dir()
    segments = _segments_for(event_type, runway=runway, distance_ft=distance_ft, distance_value=distance_value, distance_unit=distance_unit)
    if not base or not segments:
        return _speak_tts(text), False, []
    used_clips = False
    missing: list[str] = []
    played_any = False
    for key, fallback in segments:
        filename = CLIP_KEYS.get(key)
        clip = base / filename if filename else None
        if clip and clip.is_file() and _play_clip(clip):
            used_clips = True
            played_any = True
        else:
            missing.append(filename or key)
            if _speak_tts(fallback):
                played_any = True
    return played_any, used_clips, missing


def _priority_value(priority: str, event_type: str) -> int:
    p = str(priority or "advisory").lower()
    e = str(event_type or "").lower()
    if p in {"critical", "urgent"} or e in {"on_runway", "taxiway_takeoff"}:
        return 0
    if p == "caution" or e == "short_runway":
        return 1
    if p == "operational" or e == "remaining":
        return 2
    return 5


def queue_callout(text: str, event_type: str = "callout", runway: str = "", distance_ft: int | None = None, priority: str = "advisory", distance_value: int | None = None, distance_unit: str = "feet") -> dict[str, Any]:
    start()
    item = {"text": str(text or "").strip() or "RAAS", "event_type": event_type, "runway": runway, "distance_ft": distance_ft, "distance_value": distance_value, "distance_unit": distance_unit, "priority": priority, "queued_at": time.monotonic()}
    payload = (_priority_value(priority, event_type), next(_COUNTER), item)
    try:
        _QUEUE.put_nowait(payload)
    except queue.Full:
        try:
            _QUEUE.get_nowait()
        except Exception:
            pass
        try:
            _QUEUE.put_nowait(payload)
        except Exception:
            pass
    return {"ok": True, "queued": True, "audio": status()}


def _loop() -> None:
    global _RUNNING
    _update("READY", "RAAS host audio queue ready", voice_pack_status=voice_pack_status())
    while _RUNNING:
        try:
            _prio, _seq, item = _QUEUE.get(timeout=0.35)
        except queue.Empty:
            continue
        text = item.get("text") or "RAAS"
        event_type = str(item.get("event_type") or "callout")
        runway = str(item.get("runway") or "")
        distance_ft = item.get("distance_ft")
        distance_value = item.get("distance_value")
        distance_unit = str(item.get("distance_unit") or "feet")
        played, used_clips, missing = _play_segmented_callout(event_type, text, runway=runway, distance_ft=distance_ft if isinstance(distance_ft, int) else None, distance_value=distance_value if isinstance(distance_value, int) else None, distance_unit=distance_unit)
        _update(
            "PLAYED" if played else "DISPLAY_ONLY",
            text,
            voice_pack_status=voice_pack_status(),
            used_clips=used_clips,
            tts_fallback=not used_clips,
            missing_phrase_segments=missing,
        )


def start() -> dict[str, Any]:
    global _RUNNING, _THREAD
    _ensure_voice_dirs()
    _warm_tts_cache_async()
    if _RUNNING and _THREAD and _THREAD.is_alive():
        return status()
    _RUNNING = True
    _THREAD = threading.Thread(target=_loop, name="OpsRoom-RAASAudio", daemon=True)
    _THREAD.start()
    return status()


def stop() -> dict[str, Any]:
    global _RUNNING
    _RUNNING = False
    _update("STOPPED", "RAAS host audio queue stopped", voice_pack_status=voice_pack_status())
    return status()


def voice_pack_status() -> dict[str, Any]:
    candidates = _candidate_voice_dirs()[:18]
    scans = [_scan_dir(p) for p in candidates]
    path = _voice_dir()
    backend = _audio_backend_status()
    try:
        configured = str(load_settings().get("integrations", {}).get("raas_voice_path", "") or "")
    except Exception:
        configured = ""
    if path:
        data = _scan_dir(path)
        names = sorted(p.name.lower() for p in _clip_files_in(path))
        configured_scans = [_scan_dir(p) for p in _path_variants(configured)] if configured else []
        return {
            "available": True,
            "path": str(path),
            "format": "segmented_opus_phrase_pack",
            "clip_count": int(data.get("clip_count") or len(names)),
            "present_clips": names,
            "missing_optional_clips": data.get("missing_optional_clips") or [],
            "audio_backend_status": backend,
            "test_mode": "windows_tts_status_phrase",
            "available_phrases": sorted(k for k, filename in CLIP_KEYS.items() if filename in names),
            "scan_candidates": scans,
            "configured_path": configured,
            "configured_path_scans": configured_scans,
            "message": "Voice pack detected",
        }
    archive = _archive_hint()
    return {
        "available": False,
        "path": "",
        "archive_present": bool(archive),
        "archive_path": archive,
        "clip_count": 0,
        "present_clips": [],
        "missing_optional_clips": OPTIONAL_CLIPS,
        "audio_backend_status": backend,
        "test_mode": "windows_tts_status_phrase",
        "scan_candidates": scans,
        "configured_path": configured,
        "configured_path_scans": [_scan_dir(p) for p in _path_variants(configured)] if configured else [],
        "message": "No phrase pack found. TTS fallback active.",
    }


def clip_path_for_key(key: str) -> Path | None:
    filename = CLIP_KEYS.get(str(key or "").lower().strip())
    if not filename:
        return None
    base = _voice_dir()
    if not base:
        return None
    path = base / filename
    return path if path.is_file() else None


def clip_path_for_name(filename: str) -> Path | None:
    name = Path(str(filename or "")).name.lower()
    if name not in set(CLIP_KEYS.values()):
        return None
    base = _voice_dir()
    if not base:
        return None
    path = base / name
    return path if path.is_file() else None

def set_voice_path(path: str) -> dict[str, Any]:
    """Store a local voice folder path.

    The path may point directly at female/*.opus or at a parent folder containing
    female/*.opus. OPS ROOM never uploads or redistributes the files.
    """
    raw = _repair_windows_path_text(path)
    settings = load_settings()
    settings.setdefault("integrations", {})["raas_voice_path"] = raw
    save_settings(settings)
    _ensure_voice_dirs()
    vp = voice_pack_status()
    message = f"Voice folder saved: {raw}" if raw else "Default RAAS voice-pack search path restored"
    if raw and not vp.get("available"):
        message = f"Voice folder saved but no usable .opus pack was detected at: {raw}"
    elif raw and vp.get("available"):
        resolved = str((vp.get("path") or ""))
        if resolved and raw.lower() not in resolved.lower() and resolved.lower() not in raw.lower():
            message = f"Voice folder saved; using detected fallback pack at: {resolved}"
    _update("VOICE PATH SET", message, voice_pack_status=vp)
    return status()


def status() -> dict[str, Any]:
    with _LOCK:
        data = dict(_LAST)
    data["thread_running"] = bool(_THREAD and _THREAD.is_alive())
    data["queue_depth"] = _QUEUE.qsize()
    data["voice_pack_status"] = voice_pack_status()
    try:
        data["configured_voice_path"] = str(load_settings().get("integrations", {}).get("raas_voice_path", "") or "")
    except Exception:
        data["configured_voice_path"] = ""
    return data
