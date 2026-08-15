from __future__ import annotations

"""Safe installation/status helpers for aircraft-specific Black Box adapters."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any

from .aircraft_adapter_catalog import active_specs, catalog_summary, detect_family
from .fsuipc_manager import locate_fsuipc
from .settings_store import app_data_dir
from .pmdg777_eula import accept as accept_pmdg_eula, accepted as pmdg_eula_accepted, status as pmdg_eula_status

ADAPTER_VERSION = "0.24.106"
REGISTRY_NAME = "aircraft_adapter_offsets.json"
BEGIN_MARKER = "; OPS ROOM BLACK BOX ADAPTERS BEGIN"
END_MARKER = "; OPS ROOM BLACK BOX ADAPTERS END"
_MSFS_NAMES = ("FlightSimulator.exe", "FlightSimulator2024.exe", "MicrosoftFlightSimulator.exe")

_REGISTRY_CACHE: dict[str, Any] | None = None
_REGISTRY_CACHE_AT: float = 0.0
_REGISTRY_CACHE_MTIME: float | None = None
_REGISTRY_CACHE_LOCK = threading.Lock()


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def registry_path() -> Path:
    return app_data_dir() / REGISTRY_NAME


def _recover_registry_from_ini() -> dict[str, Any]:
    """Rebuild the adapter registry from the FSUIPC.ini block when the registry
    file is missing but the mappings are still installed in the ini.

    The ini block is the authoritative source of the installed offset map; the
    registry is only a bookkeeping copy. FSUIPC reformats the block markers to
    its ``!N=`` prefixed form, so both bare and prefixed markers are accepted
    here. Returns {} (no recovery possible) when the ini has no OPS ROOM block
    or the catalog does not match the block.
    """
    try:
        path = fsuipc_ini_path()
        if not path or not path.exists():
            return {}
        lines = path.read_text(encoding="utf-8-sig", errors="replace").split("\n")
        block: list[str] = []
        skipping = False
        for line in lines:
            norm = re.sub(r"^!\d+=", "", line).strip().upper()
            if norm.startswith(BEGIN_MARKER.upper()):
                skipping = True
                continue
            if norm.startswith(END_MARKER.upper()):
                skipping = False
                break
            if skipping:
                block.append(line)
        if not block:
            return {}
        offsets: dict[str, str] = {}
        for line in block:
            match = re.match(r"^\s*\d+\s*=\s*L:([^=]+)=\s*F0x([0-9A-Fa-f]+)\s*(?:[;#].*)?$", line)
            if match:
                offsets[match.group(1).strip()] = f"0x{int(match.group(2), 16):04X}"
        if len(offsets) != len(active_specs()) or not offsets:
            return {}
        registry = {
            "version": ADAPTER_VERSION,
            "installed_utc": _utc_stamp(),
            "fsuipc_ini": str(path),
            "offsets": offsets,
            "sections": ["LvarOffsets"],
            "mapping_count": len(offsets),
            "profile_sections": [],
            "separate_profile_files": [],
            "patched_files": [],
        }
        _atomic_write(registry_path(), json.dumps(registry, indent=2, sort_keys=True) + "\n")
        return registry
    except Exception:
        return {}


def load_registry() -> dict[str, Any]:
    global _REGISTRY_CACHE, _REGISTRY_CACHE_AT, _REGISTRY_CACHE_MTIME
    path = registry_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        recovered = _recover_registry_from_ini()
        if recovered:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = None
            with _REGISTRY_CACHE_LOCK:
                _REGISTRY_CACHE = dict(recovered)
                _REGISTRY_CACHE_AT = time.monotonic()
                _REGISTRY_CACHE_MTIME = mtime
            return dict(recovered)
        with _REGISTRY_CACHE_LOCK:
            _REGISTRY_CACHE = None
            _REGISTRY_CACHE_AT = 0.0
            _REGISTRY_CACHE_MTIME = None
        return {}
    now = time.monotonic()
    with _REGISTRY_CACHE_LOCK:
        if (
            _REGISTRY_CACHE is not None
            and _REGISTRY_CACHE_MTIME == mtime
            and now - _REGISTRY_CACHE_AT < 5.0
        ):
            return dict(_REGISTRY_CACHE)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        parsed = raw if isinstance(raw, dict) else {}
    except Exception:
        parsed = {}
    with _REGISTRY_CACHE_LOCK:
        _REGISTRY_CACHE = dict(parsed)
        _REGISTRY_CACHE_AT = now
        _REGISTRY_CACHE_MTIME = mtime
    return dict(parsed)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass


def _backup(path: Path) -> Path:
    backup = path.with_name(f"{path.name}.opsroom-backup-{_utc_stamp()}")
    shutil.copy2(path, backup)
    return backup


def msfs_running() -> bool:
    if os.name != "nt":
        return False
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for name in _MSFS_NAMES:
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"IMAGENAME eq {name}"], text=True,
                stderr=subprocess.DEVNULL, timeout=1.5, creationflags=flags,
            )
            if name.lower() in out.lower():
                return True
        except Exception:
            continue
    return False


def fsuipc_ini_path() -> Path | None:
    exe = locate_fsuipc()
    if not exe:
        return None
    candidate = exe.parent / "FSUIPC7.ini"
    return candidate if candidate.is_file() else candidate


def _strip_opsroom_block(lines: list[str]) -> list[str]:
    out: list[str] = []
    skipping = False
    for line in lines:
        # FSUIPC rewrites comment lines in its ini to the "!N=" prefixed form
        # (e.g. "!1=; OPS ROOM BLACK BOX ADAPTERS BEGIN v0.24.106"). Normalise
        # that prefix away so the block markers are matched either bare or
        # prefixed, and the old block is always stripped before re-allocation.
        norm = re.sub(r"^!\d+=", "", line).strip().upper()
        if norm.startswith(BEGIN_MARKER.upper()):
            skipping = True
            continue
        if norm.startswith(END_MARKER.upper()):
            skipping = False
            continue
        if not skipping:
            out.append(line)
    return out


def _sections(lines: list[str]) -> list[tuple[str, int, int]]:
    found: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
        if match:
            found.append((match.group(1).strip(), index))
    result: list[tuple[str, int, int]] = []
    for pos, (name, start) in enumerate(found):
        end = found[pos + 1][1] if pos + 1 < len(found) else len(lines)
        result.append((name, start, end))
    return result


def _mapping_line(line: str) -> tuple[int, str, int, int] | None:
    # index=L:name=F0xA000 or index=L:name=UB0xA000
    match = re.match(r"^\s*(\d+)\s*=\s*(.+?)\s*=\s*(SB|UB|SW|UW|SD|UD|F)?\s*0x([0-9A-Fa-f]+)\s*(?:[;#].*)?$", line)
    if not match:
        return None
    sizes = {"SB":1,"UB":1,"SW":2,"UW":2,"SD":4,"UD":4,"F":4,None:8}
    size = sizes.get(match.group(3), 8)
    return int(match.group(1)), match.group(2).strip(), int(match.group(4),16), int(size)


def _used_ranges(lines: list[str]) -> tuple[set[int], set[int]]:
    used_bytes: set[int] = set()
    used_indexes: set[int] = set()
    for line in _strip_opsroom_block(lines):
        parsed = _mapping_line(line)
        if not parsed:
            continue
        index, _name, offset, size = parsed
        used_indexes.add(index)
        for address in range(offset, offset + size):
            used_bytes.add(address)
    return used_bytes, used_indexes


def _allocate_offsets(lines: list[str], previous: dict[str, Any], extra_line_sets: list[list[str]] | None = None) -> dict[str, int]:
    all_used: set[int] = set()
    for line_set in [lines, *(extra_line_sets or [])]:
        for name, start, end in _sections(line_set):
            if name.lower().startswith("lvaroffsets"):
                used, _ = _used_ranges(line_set[start + 1:end])
                all_used.update(used)
    assignments: dict[str, int] = {}
    old = previous.get("offsets") if isinstance(previous.get("offsets"), dict) else {}
    # Only ACTIVE (validated) specs are allocated FSUIPC user offsets. A validated=False
    # candidate (gated behind a live-validation checkpoint) is intentionally left un-installed
    # so it consumes no offset and is never published/read (see catalog active_specs()).
    for spec in active_specs():
        try:
            offset = int(str(old.get(spec.lvar)), 0) if isinstance(old.get(spec.lvar), str) else int(old.get(spec.lvar))
        except Exception:
            continue
        if 0xA000 <= offset <= 0xA1FC and offset % 4 == 0 and all(address not in all_used for address in range(offset, offset + 4)):
            assignments[spec.lvar] = offset
            all_used.update(range(offset, offset + 4))
    for spec in active_specs():
        if spec.lvar in assignments:
            continue
        allocated = None
        for offset in range(0xA000, 0xA200, 4):
            if all(address not in all_used for address in range(offset, offset + 4)):
                allocated = offset
                break
        if allocated is None:
            raise RuntimeError(
                "FSUIPC user offset area 0xA000-0xA1FF does not have enough free 4-byte slots for the compact OPS ROOM adapter catalogue"
            )
        assignments[spec.lvar] = allocated
        all_used.update(range(allocated, allocated + 4))
    return assignments


def _adapter_block(section_lines: list[str], assignments: dict[str, int]) -> list[str]:
    clean = _strip_opsroom_block(section_lines)
    _used, indexes = _used_ranges(clean)
    index = max(indexes, default=-1) + 1
    block = [f"{BEGIN_MARKER} v{ADAPTER_VERSION}"]
    # Mirror _allocate_offsets: only active (validated) specs are written to the FSUIPC .ini.
    for spec in active_specs():
        block.append(f"{index}=L:{spec.lvar}=F0x{assignments[spec.lvar]:04X}")
        index += 1
    block.append(END_MARKER)
    while clean and not clean[-1].strip():
        clean.pop()
    if clean:
        clean.append("")
    clean.extend(block)
    clean.append("")
    return clean


def _normalised_lines(text: str) -> tuple[list[str], str]:
    newline = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), newline


def _patch_lvar_file(path: Path, assignments: dict[str, int], *, main_file: bool) -> dict[str, Any]:
    original = path.read_text(encoding="utf-8-sig", errors="replace")
    lines, newline = _normalised_lines(original)
    sections = _sections(lines)
    if main_file:
        targets = [(name,start,end) for name,start,end in sections if name.lower() == "lvaroffsets" or name.lower().startswith("lvaroffsets.")]
        if not any(name.lower() == "lvaroffsets" for name,_,_ in targets):
            while lines and not lines[-1].strip(): lines.pop()
            if lines: lines.append("")
            lines.extend(["[LvarOffsets]", ""])
            targets = [(name,start,end) for name,start,end in _sections(lines) if name.lower() == "lvaroffsets" or name.lower().startswith("lvaroffsets.")]
    else:
        # A separate profile file represents one profile already, so the section
        # name is simply [LvarOffsets] (no .Profile suffix).
        targets = [(name,start,end) for name,start,end in sections if name.lower() == "lvaroffsets"]
        if not targets:
            while lines and not lines[-1].strip(): lines.pop()
            if lines: lines.append("")
            lines.extend(["[LvarOffsets]", ""])
            targets = [(name,start,end) for name,start,end in _sections(lines) if name.lower() == "lvaroffsets"]
    patched_names: list[str] = []
    for name, start, end in reversed(targets):
        lines[start + 1:end] = _adapter_block(lines[start + 1:end], assignments)
        patched_names.append(name)
    rendered = newline.join(lines).rstrip() + newline
    backup = None
    if rendered != original:
        backup = _backup(path)
        _atomic_write(path, rendered)
    return {
        "path": str(path), "changed": rendered != original,
        "backup": str(backup) if backup else None, "sections": sorted(patched_names),
    }


def install_lvar_offsets() -> dict[str, Any]:
    path = fsuipc_ini_path()
    if not path:
        return {"ok": False, "installed": False, "reason": "FSUIPC7.exe was not found. Configure the FSUIPC path in OPS ROOM first."}
    if not path.exists():
        return {"ok": False, "installed": False, "reason": f"FSUIPC7.ini was not found beside {path.parent / 'FSUIPC7.exe'}", "path": str(path)}

    original = path.read_text(encoding="utf-8-sig", errors="replace")
    main_lines, _ = _normalised_lines(original)
    profile_dir = path.parent / "Profiles"
    profile_files = sorted(item for item in profile_dir.glob("*.ini") if item.is_file()) if profile_dir.is_dir() else []
    profile_line_sets: list[list[str]] = []
    for profile in profile_files:
        try:
            profile_line_sets.append(_normalised_lines(profile.read_text(encoding="utf-8-sig", errors="replace"))[0])
        except Exception:
            profile_line_sets.append([])

    previous = load_registry()
    assignments = _allocate_offsets(main_lines, previous, profile_line_sets)
    patched_files = [_patch_lvar_file(path, assignments, main_file=True)]
    for profile in profile_files:
        patched_files.append(_patch_lvar_file(profile, assignments, main_file=False))

    main_sections = patched_files[0].get("sections") or []
    profile_sections = [name for name in main_sections if str(name).lower().startswith("lvaroffsets.")]
    registry = {
        "version": ADAPTER_VERSION,
        "installed_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "fsuipc_ini": str(path),
        "offsets": {name: f"0x{offset:04X}" for name, offset in assignments.items()},
        "sections": main_sections,
        "mapping_count": len(assignments),
        "profile_sections": profile_sections,
        "separate_profile_files": [str(item) for item in profile_files],
        "patched_files": patched_files,
    }
    _atomic_write(registry_path(), json.dumps(registry, indent=2, sort_keys=True) + "\n")
    global _REGISTRY_CACHE, _REGISTRY_CACHE_AT, _REGISTRY_CACHE_MTIME
    with _REGISTRY_CACHE_LOCK:
        _REGISTRY_CACHE = dict(registry)
        _REGISTRY_CACHE_AT = time.monotonic()
        try:
            _REGISTRY_CACHE_MTIME = registry_path().stat().st_mtime
        except OSError:
            _REGISTRY_CACHE_MTIME = None
    changed_files = [item for item in patched_files if item.get("changed")]
    return {
        "ok": True, "installed": True, "changed": bool(changed_files),
        "path": str(path), "backup": patched_files[0].get("backup"),
        "backups": [item.get("backup") for item in changed_files if item.get("backup")],
        "mapping_count": len(assignments), "capacity": 128,
        "sections": main_sections,
        "profile_sections": profile_sections,
        "separate_profile_files": [str(item) for item in profile_files],
        "patched_files": patched_files,
        "reload_required": True,
        "note": "Restart FSUIPC7/MSFS or use FSUIPC Add-ons → WASM → Reload so the new LVar offsets are published.",
    }


def _pmdg_candidate_paths() -> list[Path]:
    result: list[Path] = []
    local = os.getenv("LOCALAPPDATA")
    roaming = os.getenv("APPDATA")
    if local:
        package_root = Path(local) / "Packages"
        for package_name in ("Microsoft.Limitless_8wekyb3d8bbwe", "Microsoft.FlightSimulator_8wekyb3d8bbwe"):
            state = package_root / package_name / "LocalState"
            for sim in ("MSFS2024", "MSFS2020"):
                base = state / "WASM" / sim
                if base.is_dir():
                    result.extend(base.glob("pmdg-aircraft-77*/work/777_Options.ini"))
            result.extend(state.glob("packages/pmdg-aircraft-77*/work/777_Options.ini"))
            result.extend(state.glob("Packages/pmdg-aircraft-77*/work/777_Options.ini"))
    if roaming:
        for base_name in ("Microsoft Flight Simulator", "Microsoft Flight Simulator 2024"):
            base = Path(roaming) / base_name / "Packages"
            if base.is_dir():
                result.extend(base.glob("pmdg-aircraft-77*/work/777_Options.ini"))
    seen: set[str] = set(); unique: list[Path] = []
    for path in result:
        key = str(path).lower()
        if key not in seen and path.is_file():
            seen.add(key); unique.append(path)
    return unique


def pmdg_options_paths() -> list[Path]:
    return _pmdg_candidate_paths()


def _ini_key_value(text: str, section: str, key: str) -> str | None:
    active = False
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = re.match(r"^\s*\[([^\]]+)\]", line)
        if match:
            active = match.group(1).strip().lower() == section.lower()
            continue
        if active:
            match = re.match(rf"^\s*{re.escape(key)}\s*=\s*(.*?)\s*(?:[;#].*)?$", line, re.I)
            if match:
                return match.group(1).strip()
    return None


def _set_ini_key(text: str, section: str, key: str, value: str) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    section_start = None; section_end = len(lines)
    for index, line in enumerate(lines):
        match = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
        if not match:
            continue
        if section_start is not None:
            section_end = index; break
        if match.group(1).strip().lower() == section.lower():
            section_start = index
    if section_start is None:
        while lines and not lines[-1].strip(): lines.pop()
        if lines: lines.append("")
        lines.extend([f"[{section}]", f"{key}={value}", ""])
    else:
        replaced = False
        for index in range(section_start + 1, section_end):
            if re.match(rf"^\s*{re.escape(key)}\s*=", lines[index], re.I):
                lines[index] = f"{key}={value}"; replaced = True; break
        if not replaced:
            lines.insert(section_end, f"{key}={value}")
    return newline.join(lines).rstrip() + newline


def install_pmdg777_broadcast(*, eula_acceptance: bool = False) -> dict[str, Any]:
    paths = pmdg_options_paths()
    if not paths:
        return {
            "ok": False, "installed": False,
            "reason": "No PMDG 777_Options.ini was found. Load the PMDG 777 once so its persistent work folder is created, then retry.",
        }
    if not pmdg_eula_accepted():
        if not eula_acceptance:
            return {
                "ok": False, "installed": False, "eula_required": True,
                "reason": "Manual acceptance of the PMDG 777 SDK EULA is required before OPS ROOM can enable or consume the official SDK data broadcast.",
                "eula": pmdg_eula_status(),
            }
        accepted = accept_pmdg_eula()
        if not accepted.get("ok"):
            return {"ok": False, "installed": False, "eula_required": True, "reason": accepted.get("reason"), "eula": pmdg_eula_status()}
    changed: list[str] = []; backups: list[str] = []
    for path in paths:
        original = path.read_text(encoding="utf-8-sig", errors="replace")
        rendered = _set_ini_key(original, "SDK", "EnableDataBroadcast", "1")
        if rendered != original:
            backup = _backup(path); backups.append(str(backup))
            _atomic_write(path, rendered); changed.append(str(path))
    return {
        "ok": True, "installed": True, "configured_paths": [str(path) for path in paths],
        "changed_paths": changed, "backups": backups,
        "restart_required": True,
        "note": "Only EnableDataBroadcast=1 was set. CDU broadcast settings were not added or changed.",
    }


def _lvar_log_status() -> dict[str, Any]:
    exe = locate_fsuipc()
    log = exe.parent / "FSUIPC7.log" if exe else None
    count = None
    if log and log.is_file():
        try:
            # Read only the first/last 256 KiB; never ingest a huge trace log.
            with log.open("rb") as handle:
                head = handle.read(262144)
                try:
                    handle.seek(max(0, log.stat().st_size - 262144))
                except OSError:
                    pass
                tail = handle.read(262144)
            text = (head + b"\n" + tail).decode("utf-8", "ignore")
            matches = re.findall(r"(\d+)\s+LVars", text, flags=re.I)
            if matches: count = int(matches[-1])
        except Exception:
            pass
    return {
        "detected": bool(count and count > 0), "lvar_count": count,
        "log": str(log) if log else None,
    }


def _current_aircraft() -> dict[str, Any]:
    try:
        from .simconnect_position import read_position
        sample = read_position(force=False)
        return sample.get("aircraft") if isinstance(sample.get("aircraft"), dict) else {}
    except Exception:
        return {}


def adapter_status() -> dict[str, Any]:
    registry = load_registry()
    path = fsuipc_ini_path()
    ini_text = ""
    try:
        ini_text = path.read_text(encoding="utf-8-sig", errors="replace") if path and path.is_file() else ""
    except Exception:
        pass
    mappings_installed = bool(registry.get("version") == ADAPTER_VERSION and BEGIN_MARKER in ini_text and len(registry.get("offsets") or {}) == len(active_specs()))
    aircraft = _current_aircraft()
    family = detect_family(aircraft)
    pmdg_paths = pmdg_options_paths()
    pmdg_enabled: list[str] = []
    for item in pmdg_paths:
        try:
            if _ini_key_value(item.read_text(encoding="utf-8-sig", errors="replace"), "SDK", "EnableDataBroadcast") == "1":
                pmdg_enabled.append(str(item))
        except OSError:
            continue
    eula = pmdg_eula_status()
    try:
        from .pmdg777_sdk import status as pmdg_sdk_status
        pmdg_sdk = pmdg_sdk_status()
    except Exception as exc:
        pmdg_sdk = {"connected": False, "receiving": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": True,
        "version": ADAPTER_VERSION,
        "current_aircraft": aircraft,
        "current_adapter": family,
        "catalog": catalog_summary(),
        "fsuipc": {
            "found": bool(locate_fsuipc()), "exe": str(locate_fsuipc()) if locate_fsuipc() else None,
            "ini": str(path) if path else None,
            "mappings_installed": mappings_installed,
            "registry": str(registry_path()),
            "registry_mapping_count": len(registry.get("offsets") or {}),
            "lvar_module": _lvar_log_status(),
            "profile_sections": registry.get("profile_sections") or [],
        },
        "pmdg777": {
            "options_found": [str(item) for item in pmdg_paths],
            "broadcast_enabled": bool(pmdg_enabled),
            "broadcast_enabled_paths": pmdg_enabled,
            "eula": eula,
            "sdk": pmdg_sdk,
        },
        "msfs_running": msfs_running(),
        "restart_recommended": bool(msfs_running() and (not mappings_installed or (family.get("key") == "pmdg_777" and not pmdg_enabled))),
    }


def install_adapters(include_pmdg: bool = True, *, accept_pmdg_sdk_eula: bool = False) -> dict[str, Any]:
    running = msfs_running()
    lvars = install_lvar_offsets()
    pmdg = install_pmdg777_broadcast(eula_acceptance=accept_pmdg_sdk_eula) if include_pmdg else {"ok": True, "installed": False, "skipped": True}
    ok = bool(lvars.get("ok")) and bool(pmdg.get("ok") or pmdg.get("skipped") or not pmdg_options_paths())
    return {
        "ok": ok,
        "lvar_offsets": lvars,
        "pmdg777": pmdg,
        "msfs_was_running": running,
        "restart_required": bool(running and (lvars.get("changed") or pmdg.get("changed_paths"))),
        "restart_message": "Close and restart MSFS and FSUIPC7 before testing the adapter." if running else "Start MSFS and FSUIPC7, then load the aircraft to test the adapter.",
        "status": adapter_status(),
    }


# FSUIPC [General] logging switches that, when enabled, cause FSUIPC7.log to
# grow to multi-gigabyte sizes in minutes during a busy flight (every LVar
# broadcast read, every axis event, every Lua debug line). OPS ROOM only ever
# needs genuine error lines from FSUIPC; turn off everything that floods the
# log. Kept as a single source of truth consumed by reduce_fsuipc_log_size().
_FSUIPC_QUIET_KEYS = (
    ("General", "LogReads", "No"),
    ("General", "LogEvents", "No"),
    ("General", "LogInputEvents", "No"),
    ("General", "LogAxes", "No"),
    ("General", "LogButtonsKeys", "No"),
    ("General", "LogExtras", "No"),
    ("General", "LogLvars", "No"),
    ("General", "LogLua", "No"),
    ("General", "DebugLua", "No"),
    ("General", "Console", "No"),
    ("WAPI", "LogLevel", "Info"),
)

# Captured LVar dump file FSUIPC writes when LogLvars=Yes; we surface and prune it.
_LVAR_LOG_NAME = "LVarLog.txt"
_FSUIPC_DEFAULT_MAX_BYTES = 50 * 1024 * 1024
_FSUIPC_DIAGNOSTIC_TAIL_BYTES = 2 * 1024 * 1024
_FSUIPC_STATUS_INI_BYTES = 512 * 1024
_OPSROOM_ROTATION_MARKER = ".opsroom-rotated-"
_OPSROOM_TAIL_SUFFIX = ".opsroom-tail"


def _fsuipc_log_files(exe: Path | None) -> list[Path]:
    if not exe:
        return []
    base = exe.parent
    return [
        base / "FSUIPC7.log",
        base / "FSUIPC7.Previous.log",
        base / _LVAR_LOG_NAME,
    ]


def _legacy_fsuipc_rotations(exe: Path | None) -> list[Path]:
    """Return only legacy files created by OPS ROOM's old rotation scheme."""
    found: list[Path] = []
    for source in _fsuipc_log_files(exe):
        try:
            found.extend(path for path in source.parent.glob(f"{source.name}{_OPSROOM_ROTATION_MARKER}*") if path.is_file())
        except OSError:
            continue
    return sorted(set(found), key=lambda path: path.name.lower())


def _diagnostic_tail_path(path: Path) -> Path:
    source_name = path.name.split(_OPSROOM_ROTATION_MARKER, 1)[0]
    return path.with_name(f"{source_name}{_OPSROOM_TAIL_SUFFIX}")


def _diagnostic_tail_files(exe: Path | None) -> list[Path]:
    return [_diagnostic_tail_path(path) for path in _fsuipc_log_files(exe)]


def _tracked_fsuipc_files(exe: Path | None) -> list[tuple[str, Path]]:
    return [
        *(("active", path) for path in _fsuipc_log_files(exe)),
        *(("legacy_rotation", path) for path in _legacy_fsuipc_rotations(exe)),
        *(("diagnostic_tail", path) for path in _diagnostic_tail_files(exe)),
    ]


def _bounded_ini_text(path: Path | None) -> tuple[str, bool]:
    if not path:
        return "", False
    with path.open("rb") as handle:
        raw = handle.read(_FSUIPC_STATUS_INI_BYTES + 1)
    truncated = len(raw) > _FSUIPC_STATUS_INI_BYTES
    return raw[:_FSUIPC_STATUS_INI_BYTES].decode("utf-8-sig", "replace"), truncated


def fsuipc_log_status() -> dict[str, Any]:
    exe = locate_fsuipc()
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for kind, path in _tracked_fsuipc_files(exe):
        item: dict[str, Any] = {"path": str(path), "kind": kind, "exists": False, "size": 0}
        try:
            if path.is_file():
                item["exists"] = True
                item["size"] = int(path.stat().st_size)
                total_bytes += item["size"]
        except OSError as exc:
            item["error"] = f"{type(exc).__name__}: {exc}"
        files.append(item)
    ini_text = ""
    ini_truncated = False
    ini_path = fsuipc_ini_path()
    try:
        if ini_path and ini_path.is_file():
            ini_text, ini_truncated = _bounded_ini_text(ini_path)
    except OSError:
        pass
    noisy: list[str] = []
    for section, key, quiet_value in _FSUIPC_QUIET_KEYS:
        current = _ini_key_value(ini_text, section, key)
        if current is not None and str(current).strip().lower() != str(quiet_value).lower():
            noisy.append(f"{section}.{key}={current}")
    oversized = [
        item for item in files
        if item["exists"] and (
            (item["kind"] == "active" and item["size"] > _FSUIPC_DEFAULT_MAX_BYTES)
            or item["kind"] == "legacy_rotation"
            or (item["kind"] == "diagnostic_tail" and item["size"] > _FSUIPC_DIAGNOSTIC_TAIL_BYTES)
        )
    ]
    return {
        "ok": True,
        "found": bool(exe),
        "exe": str(exe) if exe else None,
        "ini": str(ini_path) if ini_path else None,
        "files": files,
        "total_size": total_bytes,
        "active_size": sum(item["size"] for item in files if item["kind"] == "active"),
        "legacy_rotation_size": sum(item["size"] for item in files if item["kind"] == "legacy_rotation"),
        "diagnostic_tail_size": sum(item["size"] for item in files if item["kind"] == "diagnostic_tail"),
        "oversized_files": [item["path"] for item in oversized],
        "cleanup_pending": bool(oversized),
        "noisy_keys": noisy,
        "noisy": bool(noisy),
        "ini_status_truncated": ini_truncated,
        "diagnostic_tail_limit": _FSUIPC_DIAGNOSTIC_TAIL_BYTES,
        "diagnostic_retained_file_limit": len(_fsuipc_log_files(exe)),
        "diagnostic_retained_total_limit": len(_fsuipc_log_files(exe)) * _FSUIPC_DIAGNOSTIC_TAIL_BYTES,
    }


def _read_bounded_tail(path: Path, size: int, limit: int = _FSUIPC_DIAGNOSTIC_TAIL_BYTES) -> bytes:
    with path.open("rb") as handle:
        handle.seek(max(0, size - limit))
        return handle.read(limit)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass


def _truncate_in_place(path: Path) -> None:
    # Opening the existing inode avoids replacing the live file behind FSUIPC.
    # Windows will reject this while FSUIPC holds an incompatible share lock.
    with path.open("r+b") as handle:
        handle.truncate(0)


def _preserve_tail(path: Path, tail: bytes) -> tuple[str | None, str | None]:
    if not tail:
        return None, None
    diagnostic = _diagnostic_tail_path(path)
    try:
        _atomic_write_bytes(diagnostic, tail[-_FSUIPC_DIAGNOSTIC_TAIL_BYTES:])
        return str(diagnostic), None
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _truncate_or_rotate(path: Path, *, max_bytes: int, rotate: bool) -> dict[str, Any]:
    """Clear an oversized log without ever copying it in full.

    ``rotate`` is retained for API compatibility; when true it now preserves
    only a bounded diagnostic tail after a successful in-place truncation.
    """
    result: dict[str, Any] = {
        "path": str(path), "kind": "active", "changed": False,
        "cleanup_complete": True, "pending": False, "bytes_reclaimed": 0,
    }
    try:
        if not path.is_file():
            return {**result, "status": "unchanged", "reason": "missing", "size": 0}
        size = int(path.stat().st_size)
    except OSError as exc:
        return {**result, "status": "failed", "cleanup_complete": False, "reason": f"{type(exc).__name__}: {exc}"}
    result["size_before"] = size
    if size <= max_bytes:
        return {**result, "status": "unchanged", "size": size}
    tail = b""
    tail_read_error = None
    if rotate:
        try:
            tail = _read_bounded_tail(path, size)
        except OSError as exc:
            tail_read_error = f"{type(exc).__name__}: {exc}"
    try:
        _truncate_in_place(path)
        remaining = int(path.stat().st_size)
    except OSError as exc:
        return {
            **result, "status": "pending", "cleanup_complete": False, "pending": True,
            "reason": f"{type(exc).__name__}: {exc}", "size": size, "tail_read_error": tail_read_error,
        }
    if remaining > max_bytes:
        return {
            **result, "status": "pending", "changed": remaining != size,
            "cleanup_complete": False, "pending": True, "size": remaining,
            "bytes_reclaimed": max(0, size - remaining), "reason": "File remained oversized after truncation.",
        }
    diagnostic, diagnostic_error = _preserve_tail(path, tail) if rotate else (None, None)
    return {
        **result, "status": "cleaned", "changed": True, "size": remaining,
        "bytes_reclaimed": max(0, size - remaining), "diagnostic_tail": diagnostic,
        "diagnostic_error": diagnostic_error, "tail_read_error": tail_read_error,
    }


def _remove_legacy_rotation(path: Path, *, preserve_tail: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path), "kind": "legacy_rotation", "changed": False,
        "cleanup_complete": True, "pending": False, "bytes_reclaimed": 0,
    }
    try:
        if not path.is_file():
            return {**result, "status": "unchanged", "reason": "missing", "size": 0}
        size = int(path.stat().st_size)
    except OSError as exc:
        return {**result, "status": "failed", "cleanup_complete": False, "reason": f"{type(exc).__name__}: {exc}"}
    tail = b""
    tail_read_error = None
    if preserve_tail:
        try:
            tail = _read_bounded_tail(path, size)
        except OSError as exc:
            tail_read_error = f"{type(exc).__name__}: {exc}"
    try:
        path.unlink()
    except OSError as exc:
        return {
            **result, "status": "pending", "cleanup_complete": False, "pending": True,
            "reason": f"{type(exc).__name__}: {exc}", "size": size, "tail_read_error": tail_read_error,
        }
    diagnostic, diagnostic_error = _preserve_tail(path, tail) if preserve_tail else (None, None)
    return {
        **result, "status": "cleaned", "changed": True, "size_before": size, "size": 0,
        "bytes_reclaimed": size, "diagnostic_tail": diagnostic,
        "diagnostic_error": diagnostic_error, "tail_read_error": tail_read_error,
    }


def _bound_diagnostic_tail(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path), "kind": "diagnostic_tail", "changed": False,
        "cleanup_complete": True, "pending": False, "bytes_reclaimed": 0,
    }
    try:
        if not path.is_file():
            return {**result, "status": "unchanged", "reason": "missing", "size": 0}
        size = int(path.stat().st_size)
        if size <= _FSUIPC_DIAGNOSTIC_TAIL_BYTES:
            return {**result, "status": "unchanged", "size": size}
        tail = _read_bounded_tail(path, size)
        _atomic_write_bytes(path, tail)
        remaining = int(path.stat().st_size)
        return {
            **result, "status": "cleaned", "changed": True, "size_before": size,
            "size": remaining, "bytes_reclaimed": max(0, size - remaining),
        }
    except OSError as exc:
        return {
            **result, "status": "pending", "cleanup_complete": False, "pending": True,
            "reason": f"{type(exc).__name__}: {exc}", "size": locals().get("size", 0),
        }


def reduce_fsuipc_log_size(*, rotate_logs: bool = True, max_bytes: int = _FSUIPC_DEFAULT_MAX_BYTES) -> dict[str, Any]:
    """Quiet verbose FSUIPC settings and perform disk-bounded log cleanup.

    No oversized file is copied. At most one 2 MiB diagnostic tail is retained
    for each of the three known FSUIPC logs, and old OPS ROOM full rotations are
    reclaimed. Active Windows locks are returned as pending rather than success.
    """
    path = fsuipc_ini_path()
    if not path or not path.exists():
        return {"ok": False, "cleanup_status": "failed", "cleanup_complete": False, "pending": False, "bytes_reclaimed": 0, "reason": "FSUIPC7.ini was not found. Launch FSUIPC7 or configure the path in OPS ROOM first.", "log_status": fsuipc_log_status()}
    try:
        original = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        return {"ok": False, "cleanup_status": "failed", "cleanup_complete": False, "pending": False, "bytes_reclaimed": 0, "reason": f"FSUIPC7.ini could not be read: {type(exc).__name__}: {exc}", "log_status": fsuipc_log_status()}
    rendered = original
    changed_keys: list[str] = []
    for section, key, value in _FSUIPC_QUIET_KEYS:
        next_text = _set_ini_key(rendered, section, key, value)
        if next_text != rendered:
            rendered = next_text
            changed_keys.append(f"{section}.{key}={value}")
    backup = None
    ini_changed = rendered != original
    if ini_changed:
        try:
            backup = _backup(path)
            _atomic_write(path, rendered)
        except OSError as exc:
            return {"ok": False, "cleanup_status": "failed", "cleanup_complete": False, "pending": False, "bytes_reclaimed": 0, "reason": f"FSUIPC7.ini could not be updated: {type(exc).__name__}: {exc}", "backup": str(backup) if backup else None, "log_status": fsuipc_log_status()}
    max_bytes = max(0, int(max_bytes))
    before = fsuipc_log_status()
    log_results: list[dict[str, Any]] = []
    exe = locate_fsuipc()
    if rotate_logs and exe:
        # Remove old full-file rotations first. Processing oldest-to-newest means
        # one bounded tail per source is retained, never one per legacy copy.
        for legacy_path in _legacy_fsuipc_rotations(exe):
            log_results.append(_remove_legacy_rotation(legacy_path, preserve_tail=True))
        for log_path in _fsuipc_log_files(exe):
            log_results.append(_truncate_or_rotate(log_path, max_bytes=max_bytes, rotate=True))
        for tail_path in _diagnostic_tail_files(exe):
            if tail_path.is_file():
                log_results.append(_bound_diagnostic_tail(tail_path))
    after = fsuipc_log_status()
    remaining = [
        item for item in after.get("files", [])
        if item.get("exists") and (
            (item.get("kind") == "active" and int(item.get("size") or 0) > max_bytes)
            or item.get("kind") == "legacy_rotation"
            or (item.get("kind") == "diagnostic_tail" and int(item.get("size") or 0) > _FSUIPC_DIAGNOSTIC_TAIL_BYTES)
        )
    ] if rotate_logs else []
    pending_files = [item for item in log_results if item.get("pending")]
    failed_files = [item for item in log_results if item.get("status") == "failed"]
    cleanup_complete = not pending_files and not failed_files and not remaining
    cleanup_status = "complete" if cleanup_complete else ("failed" if failed_files else "pending")
    bytes_reclaimed = max(0, int(before.get("total_size") or 0) - int(after.get("total_size") or 0))
    restart_required = ini_changed
    return {
        "ok": True,
        "ini_path": str(path),
        "ini_changed": ini_changed,
        "changed_keys": changed_keys,
        "backup": str(backup) if backup else None,
        "log_files": log_results,
        "cleanup_status": cleanup_status,
        "cleanup_complete": cleanup_complete,
        "pending": not cleanup_complete,
        "pending_files": pending_files,
        "failed_files": failed_files,
        "remaining_files": remaining,
        "bytes_reclaimed": bytes_reclaimed,
        "before": before,
        "after": after,
        "restart_required": restart_required,
        "restart_message": "FSUIPC logging switches were silenced. Use FSUIPC's Reload option or restart FSUIPC7/MSFS for the quieter settings to take effect." if restart_required else "FSUIPC verbose logging switches are already quiet; no reload is required.",
        "note": "OPS ROOM reads telemetry directly through FSUIPC offsets. Log cleanup never parses logs for telemetry and retains at most a small bounded diagnostic tail.",
    }
