#!/usr/bin/env python3
"""OPS ROOM developer diagnostic: probe pilot control inputs (READ-ONLY).

PURPOSE
    Determine, for the currently loaded aircraft (Fenix A320 first), WHICH data
    source actually carries the pilot control inputs (aileron / elevator /
    rudder / throttle). This tells us whether OPS ROOM can capture those inputs
    through standard SimConnect / FSUIPC channels, or whether it needs
    aircraft-specific L:Vars.

    It reads FOUR views side by side so the source is visible, not just the
    derived value:
        [SimConnect raw SimVars] | [OPS ROOM SimConnect-derived]
        [FSUIPC raw offsets]     | [OPS ROOM FSUIPC-derived]

    It reuses OPS ROOM's OWN provider code (app/simconnect_position.py and
    app/telemetry_provider.py) for the derived columns, so the readings match
    exactly what the Black Box recorder would capture.

SAFETY
    This is READ-ONLY. It never writes any SimVar / L:Var / FSUIPC offset, never
    changes settings, never starts GSX automation or recording, never touches
    dist/**. It only opens read sessions, reads, and prints. Run it manually
    from the build venv. It is NOT part of the build gate or the packaged app.

USAGE (run from the repository root, i.e. the folder that contains "app" and
"tools", using the SAME build venv Python that has SimConnect / pyuipc):

    <build-venv-python> tools\\probe_control_inputs.py
        Live ~20 Hz view of all four columns + a per-control verdict on Ctrl+C.

    <build-venv-python> tools\\probe_control_inputs.py --hz 30
        Same, polling at 30 Hz (clamped to 1..60).

    <build-venv-python> tools\\probe_control_inputs.py --seconds 20
        Auto-stop after 20 seconds instead of waiting for Ctrl+C.

    <build-venv-python> tools\\probe_control_inputs.py --discover --label aileron
        L:Var move-and-diff discovery. Snapshot all L:Vars, prompt you to move
        one axis, snapshot again, and report every L:Var that changed. Repeat
        per axis (aileron / elevator / rudder / throttle) to find the Fenix
        sidestick / rudder / thrust L:Vars (they are NOT in fnx320_scripts.xml).

    <build-venv-python> tools\\probe_control_inputs.py --discover --label rudder \\
        --lvar-candidates my_candidates.txt
        If the runtime cannot ENUMERATE all L:Vars (see notes below), you may
        supply a newline-delimited list of candidate L:Var names; the tool will
        diff those named reads instead.

REQUIREMENTS / NOTES
    * MSFS must be running with an aircraft loaded into an active flight.
    * Both providers are probed. Many users have no FSUIPC7; if FSUIPC / pyuipc
      is missing or not connected, its columns show "FSUIPC: not available" and
      the SimConnect columns still produce a full result.
    * FSUIPC offset labelling note: OPS ROOM's own decoder (telemetry_provider)
      treats offset 0x0BB2 as ELEVATOR and 0x0BB6 as AILERON, whereas the
      FSUIPC offset-status documentation labels 0x0BB2 as AILERON and 0x0BB6 as
      ELEVATOR. Because this tool's job is precisely to reveal which channel
      moves, the raw FSUIPC rows are labelled BY ADDRESS with both readings and
      you should trust the observed [MOVED] markers over either label. The
      "OPS ROOM FSUIPC-derived" column follows OPS ROOM's own decode so it
      matches the recorder.
    * L:Var enumeration: the codebase's SimConnect/FSUIPC libraries expose
      reading of a NAMED L:Var (see app/gsx_remote.py `_lvar_request`, which
      builds `SimConnect.RequestList.Request((name, b"Number"), sm)` through the
      MobiFlight WASM gateway that GSX installs), but they do not guarantee an
      API to ENUMERATE every L:Var. This tool probes for an enumeration API and,
      if none is available, prints a clear message and (optionally) falls back
      to a supplied --lvar-candidates list. It never crashes when enumeration is
      unavailable.
    * `python -m compileall tools/probe_control_inputs.py` parses cleanly even
      in a bare environment: all sim/library imports live inside functions and
      are guarded.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Callable

# --------------------------------------------------------------------------
# Repository import bootstrap. Running "tools\probe_control_inputs.py" from the
# repo root must be able to `import app.*`. app/__init__.py is empty, so this is
# side-effect free.
# --------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _ensure_repo_on_path() -> None:
    root = str(_REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


# ==========================================================================
# Field / probe definitions
# ==========================================================================
# Each probe declares:
#   control       coarse control axis for the verdict (aileron/elevator/rudder/throttle N)
#   category      coarse SOURCE category used in the verdict
#   short         short display label inside a column cell
#   column        which of the four columns it renders in
#   source        snapshot sub-dict key ("sc_raw"/"sc_deriv"/"fs_raw"/"fs_deriv")
#   key           lookup key inside that sub-dict
#   eps           movement epsilon (kind-dependent)

COL_SC_RAW = "sc_raw"
COL_SC_DERIV = "sc_deriv"
COL_FS_RAW = "fs_raw"
COL_FS_DERIV = "fs_deriv"

CAT_SC_INPUT = "SimConnect input SimVar"
CAT_SC_SURFACE = "SimConnect surface SimVar"
CAT_SC_DERIVED = "OPS ROOM SimConnect-derived field"
CAT_FS_OFFSET = "FSUIPC offset"
CAT_FS_DERIVED = "OPS ROOM FSUIPC-derived field"

EPS_POS = 0.02      # normalized -1..1 axes
EPS_PCT = 1.5       # 0..100 percent
EPS_OFF = 150.0     # raw signed 16-bit offset (+-16383)

# Standard SimConnect raw SimVars requested through the same session the
# recorder uses. Units mirror the SDK types used in simconnect_position.py.
SC_RAW_SIMVARS: list[tuple[str, bytes]] = [
    ("YOKE X POSITION", b"Position"),
    ("YOKE Y POSITION", b"Position"),
    ("RUDDER PEDAL POSITION", b"Position"),
    ("AILERON POSITION", b"Position"),
    ("ELEVATOR POSITION", b"Position"),
    ("RUDDER POSITION", b"Position"),
    ("GENERAL ENG THROTTLE LEVER POSITION:1", b"Percent"),
    ("GENERAL ENG THROTTLE LEVER POSITION:2", b"Percent"),
]

# Raw FSUIPC control offsets read directly (see note in the module docstring
# about the OPS ROOM vs FSUIPC-doc label mismatch on 0x0BB2 / 0x0BB6).
# (offset, struct_fmt, address_label, opsroom_decode, fsuipc_doc_decode)
FS_RAW_OFFSETS: list[tuple[int, str, str, str, str]] = [
    (0x0BB2, "h", "0x0BB2", "elevator", "aileron"),
    (0x0BB6, "h", "0x0BB6", "aileron", "elevator"),
    (0x0BBA, "h", "0x0BBA", "rudder", "rudder"),
    (0x088C, "h", "0x088C", "throttle1", "throttle1"),
    (0x0924, "h", "0x0924", "throttle2", "throttle2"),
]


def _build_probes() -> list[dict[str, Any]]:
    """Flat probe list; the display groups these back together per control."""
    p: list[dict[str, Any]] = []

    def add(control, category, short, column, source, key, eps):
        p.append({
            "control": control, "category": category, "short": short,
            "column": column, "source": source, "key": key, "eps": eps,
        })

    # ---- Aileron ----
    add("aileron", CAT_SC_INPUT, "YOKE X", COL_SC_RAW, "sc_raw", "YOKE X POSITION", EPS_POS)
    add("aileron", CAT_SC_SURFACE, "AIL POS", COL_SC_RAW, "sc_raw", "AILERON POSITION", EPS_POS)
    add("aileron", CAT_SC_DERIVED, "pilot_ail", COL_SC_DERIV, "sc_deriv", "pilot_aileron_input", EPS_POS)
    add("aileron", CAT_SC_DERIVED, "ail_pos", COL_SC_DERIV, "sc_deriv", "aileron_position", EPS_POS)
    add("aileron", CAT_FS_OFFSET, "0x0BB6", COL_FS_RAW, "fs_raw", "0x0BB6", EPS_OFF)
    add("aileron", CAT_FS_DERIVED, "pilot_ail", COL_FS_DERIV, "fs_deriv", "pilot_aileron_input", EPS_POS)
    add("aileron", CAT_FS_DERIVED, "ail_pos", COL_FS_DERIV, "fs_deriv", "aileron_position", EPS_POS)

    # ---- Elevator ----
    add("elevator", CAT_SC_INPUT, "YOKE Y", COL_SC_RAW, "sc_raw", "YOKE Y POSITION", EPS_POS)
    add("elevator", CAT_SC_SURFACE, "ELE POS", COL_SC_RAW, "sc_raw", "ELEVATOR POSITION", EPS_POS)
    add("elevator", CAT_SC_DERIVED, "pilot_ele", COL_SC_DERIV, "sc_deriv", "pilot_elevator_input", EPS_POS)
    add("elevator", CAT_SC_DERIVED, "ele_pos", COL_SC_DERIV, "sc_deriv", "elevator_position", EPS_POS)
    add("elevator", CAT_FS_OFFSET, "0x0BB2", COL_FS_RAW, "fs_raw", "0x0BB2", EPS_OFF)
    add("elevator", CAT_FS_DERIVED, "pilot_ele", COL_FS_DERIV, "fs_deriv", "pilot_elevator_input", EPS_POS)
    add("elevator", CAT_FS_DERIVED, "ele_pos", COL_FS_DERIV, "fs_deriv", "elevator_position", EPS_POS)

    # ---- Rudder ----
    add("rudder", CAT_SC_INPUT, "PEDAL", COL_SC_RAW, "sc_raw", "RUDDER PEDAL POSITION", EPS_POS)
    add("rudder", CAT_SC_SURFACE, "RUD POS", COL_SC_RAW, "sc_raw", "RUDDER POSITION", EPS_POS)
    add("rudder", CAT_SC_DERIVED, "pilot_rud", COL_SC_DERIV, "sc_deriv", "pilot_rudder_input", EPS_POS)
    add("rudder", CAT_SC_DERIVED, "rud_pos", COL_SC_DERIV, "sc_deriv", "rudder_position", EPS_POS)
    add("rudder", CAT_FS_OFFSET, "0x0BBA", COL_FS_RAW, "fs_raw", "0x0BBA", EPS_OFF)
    add("rudder", CAT_FS_DERIVED, "pilot_rud", COL_FS_DERIV, "fs_deriv", "pilot_rudder_input", EPS_POS)
    add("rudder", CAT_FS_DERIVED, "rud_pos", COL_FS_DERIV, "fs_deriv", "rudder_position", EPS_POS)

    # ---- Throttle 1 ----
    add("throttle1", CAT_SC_INPUT, "THR:1", COL_SC_RAW, "sc_raw", "GENERAL ENG THROTTLE LEVER POSITION:1", EPS_PCT)
    add("throttle1", CAT_SC_DERIVED, "thr1_pct", COL_SC_DERIV, "sc_deriv", "throttle_1_percent", EPS_PCT)
    add("throttle1", CAT_FS_OFFSET, "0x088C", COL_FS_RAW, "fs_raw", "0x088C", EPS_OFF)
    add("throttle1", CAT_FS_DERIVED, "thr1_pct", COL_FS_DERIV, "fs_deriv", "throttle_1_percent", EPS_PCT)

    # ---- Throttle 2 ----
    add("throttle2", CAT_SC_INPUT, "THR:2", COL_SC_RAW, "sc_raw", "GENERAL ENG THROTTLE LEVER POSITION:2", EPS_PCT)
    add("throttle2", CAT_SC_DERIVED, "thr2_pct", COL_SC_DERIV, "sc_deriv", "throttle_2_percent", EPS_PCT)
    add("throttle2", CAT_FS_OFFSET, "0x0924", COL_FS_RAW, "fs_raw", "0x0924", EPS_OFF)
    add("throttle2", CAT_FS_DERIVED, "thr2_pct", COL_FS_DERIV, "fs_deriv", "throttle_2_percent", EPS_PCT)

    return p


CONTROL_ORDER = ["aileron", "elevator", "rudder", "throttle1", "throttle2"]


# ==========================================================================
# SimConnect probe (reuses app/simconnect_position.py session + derived read)
# ==========================================================================
class SimConnectProbe:
    """Reads raw SimVars through the SAME session OPS ROOM uses, plus the
    OPS ROOM-derived control fields via `read_position`."""

    def __init__(self) -> None:
        self.available = False
        self.reason = ""
        self._sp: Any = None          # app.simconnect_position module
        self._requests: dict[str, Any] = {}
        self._session_id: int | None = None

    def start(self) -> None:
        try:
            from app import simconnect_position as sp  # type: ignore
        except Exception as exc:  # pragma: no cover - import guard
            self.reason = f"app.simconnect_position not importable: {type(exc).__name__}: {exc}"
            return
        self._sp = sp
        diag = sp.simconnect_diagnostics()
        if not diag.get("python_package_importable"):
            self.reason = "Python SimConnect package is not importable in this venv"
            return
        if not diag.get("dll_found"):
            self.reason = "SimConnect.dll was not found in this runtime"
            return
        try:
            with sp._LOCK:
                sp._ensure_session(diag)
            self.available = True
        except Exception as exc:
            self.reason = f"SimConnect session not established: {type(exc).__name__}: {exc}"

    def _raw_request(self, sm: Any, name: str, unit: bytes) -> Any:
        """Cache a raw-SimVar Request per session, mirroring gsx_remote._lvar_request."""
        session_id = id(sm)
        if self._session_id != session_id:
            self._requests.clear()
            self._session_id = session_id
        req = self._requests.get(name)
        if req is None:
            from SimConnect.RequestList import Request  # type: ignore
            req = Request((name.encode("ascii"), unit), sm, _time=100)
            self._requests[name] = req
        return req

    def read_raw(self) -> dict[str, Any]:
        """Read the standard raw input/surface SimVars via the shared session."""
        out: dict[str, Any] = {}
        if not self.available or self._sp is None:
            return out
        sp = self._sp
        try:
            with sp._LOCK:
                sm, _aq = sp._ensure_session(sp.simconnect_diagnostics())
                for name, unit in SC_RAW_SIMVARS:
                    try:
                        value = self._raw_request(sm, name, unit).value
                        out[name] = float(value) if value is not None else None
                    except Exception:
                        out[name] = None
        except Exception as exc:
            out["_error"] = f"{type(exc).__name__}: {exc}"
        return out

    def read_derived(self) -> dict[str, Any]:
        """OPS ROOM SimConnect-derived control fields (exact recorder path)."""
        if not self.available or self._sp is None:
            return {}
        try:
            return self._sp.read_position(force=True)
        except Exception as exc:
            return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


# ==========================================================================
# FSUIPC probe (reuses app/telemetry_provider.py IO + derived read)
# ==========================================================================
class FsuipcProbe:
    """Reads raw control offsets directly through pyuipc (using OPS ROOM's own
    import/open helpers) plus the OPS ROOM FSUIPC-derived control fields."""

    def __init__(self) -> None:
        self.available = False
        self.reason = ""
        self._tp: Any = None          # app.telemetry_provider module
        self._pyuipc: Any = None

    def start(self) -> None:
        try:
            from app import telemetry_provider as tp  # type: ignore
        except Exception as exc:  # pragma: no cover - import guard
            self.reason = f"app.telemetry_provider not importable: {type(exc).__name__}: {exc}"
            return
        self._tp = tp
        if not tp._pyuipc_available():
            self.reason = "pyuipc bridge is not installed/available"
            return
        try:
            with tp._FSUIPC_IO_LOCK:
                self._pyuipc = tp._import_pyuipc()
                tp._open_fsuipc(self._pyuipc)
            self.available = True
        except Exception as exc:
            self.reason = f"FSUIPC/pyuipc not connected: {type(exc).__name__}: {exc}"

    def read_raw(self) -> dict[str, Any]:
        """Direct raw offset read (bypasses OPS ROOM's 80 ms adapter cache so the
        live view updates every poll). Signed 16-bit control offsets."""
        out: dict[str, Any] = {}
        if not self.available or self._tp is None or self._pyuipc is None:
            return out
        tp = self._tp
        requests = [(off, fmt) for off, fmt, *_ in FS_RAW_OFFSETS]
        try:
            with tp._FSUIPC_IO_LOCK:
                tp._open_fsuipc(self._pyuipc)
                values = self._pyuipc.read(requests)
            if isinstance(values, (list, tuple)) and len(values) == len(FS_RAW_OFFSETS):
                for (off, _fmt, label, *_rest), value in zip(FS_RAW_OFFSETS, values):
                    try:
                        out[label] = float(value) if value is not None else None
                    except (TypeError, ValueError):
                        out[label] = None
        except Exception as exc:
            out["_error"] = f"{type(exc).__name__}: {exc}"
        return out

    def read_derived(self) -> dict[str, Any]:
        """OPS ROOM FSUIPC-derived control fields (exact recorder path)."""
        if not self.available or self._tp is None:
            return {}
        try:
            return self._tp._read_fsuipc()
        except Exception as exc:
            return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


# ==========================================================================
# L:Var enumeration + move-and-diff discovery
# ==========================================================================
def _read_named_lvar(sp: Any, sm: Any, name: str) -> float | None:
    """Read a single named L:Var through the codebase's Request/WASM gateway.

    Mirrors app/gsx_remote.py `_lvar_request` / `_read_value`.
    """
    try:
        from SimConnect.RequestList import Request  # type: ignore
    except Exception:
        return None
    lvar_name = name if name.upper().startswith("L:") else f"L:{name}"
    try:
        req = Request((lvar_name.encode("ascii"), b"Number"), sm, _time=100, _settable=False)
        value = req.value
        return None if value is None else float(value)
    except Exception:
        return None


def _try_enumerate_lvar_names(sp: Any, sm: Any, pyuipc: Any) -> tuple[list[str] | None, str]:
    """Best-effort L:Var name enumeration.

    Returns (names, note). names is None when no enumeration API is available.
    Probes the MobiFlight SimConnect fork and FSUIPC in turn without assuming a
    specific method exists.
    """
    # --- 1) SimConnect (MobiFlight fork) possible enumeration entry points ---
    for attr in ("get_lvar_list", "getLvarList", "list_lvars", "get_lvars", "lvars", "get_LVars"):
        obj = getattr(sm, attr, None)
        if obj is None:
            continue
        try:
            result = obj() if callable(obj) else obj
        except Exception:
            continue
        names = _coerce_name_list(result)
        if names:
            return names, f"enumerated via SimConnect.{attr}"
    # Some forks expose enumeration on the dll wrapper.
    dll = getattr(sm, "dll", None)
    for attr in ("get_lvar_list", "getLvarList", "list_lvars", "get_lvars"):
        obj = getattr(dll, attr, None)
        if obj is None:
            continue
        try:
            result = obj() if callable(obj) else obj
        except Exception:
            continue
        names = _coerce_name_list(result)
        if names:
            return names, f"enumerated via SimConnect.dll.{attr}"

    # --- 2) FSUIPC / pyuipc possible enumeration entry points ---
    if pyuipc is not None:
        for attr in ("lvars", "get_lvars", "list_lvars", "read_lvars", "enumerate_lvars"):
            obj = getattr(pyuipc, attr, None)
            if obj is None:
                continue
            try:
                result = obj() if callable(obj) else obj
            except Exception:
                continue
            names = _coerce_name_list(result)
            if names:
                return names, f"enumerated via pyuipc.{attr}"

    return None, (
        "No L:Var enumeration API is exposed by this runtime's SimConnect/FSUIPC "
        "libraries. Named-L:Var reads still work, but full discovery needs an "
        "enumeration-capable build or a --lvar-candidates file."
    )


def _coerce_name_list(result: Any) -> list[str]:
    names: list[str] = []
    if isinstance(result, dict):
        for k in result.keys():
            names.append(str(k))
    elif isinstance(result, (list, tuple, set)):
        for item in result:
            if isinstance(item, (list, tuple)) and item:
                names.append(str(item[0]))
            else:
                names.append(str(item))
    return [n for n in (s.strip() for s in names) if n]


def _snapshot_lvars(sp: Any, sm: Any, pyuipc: Any, names: list[str]) -> dict[str, float]:
    snap: dict[str, float] = {}
    for name in names:
        value = _read_named_lvar(sp, sm, name)
        if value is not None:
            snap[name] = value
    return snap


def run_discover(label: str, lvar_candidates_path: str | None) -> int:
    _ensure_repo_on_path()
    print("=" * 78)
    print(f"L:VAR MOVE-AND-DIFF DISCOVERY  (axis label: {label})")
    print("READ-ONLY. No L:Var is written. Ctrl+C to abort.")
    print("=" * 78)

    try:
        from app import simconnect_position as sp  # type: ignore
    except Exception as exc:
        print(f"app.simconnect_position not importable: {type(exc).__name__}: {exc}")
        return 2

    diag = sp.simconnect_diagnostics()
    if not diag.get("python_package_importable") or not diag.get("dll_found"):
        print("SimConnect is not available in this venv/runtime; cannot read L:Vars.")
        print(f"  python_package_importable={diag.get('python_package_importable')} dll_found={diag.get('dll_found')}")
        return 2

    try:
        with sp._LOCK:
            sm, _aq = sp._ensure_session(diag)
    except Exception as exc:
        print(f"Could not open SimConnect session: {type(exc).__name__}: {exc}")
        return 2

    pyuipc = None
    try:
        from app import telemetry_provider as tp  # type: ignore
        if tp._pyuipc_available():
            with tp._FSUIPC_IO_LOCK:
                pyuipc = tp._import_pyuipc()
                tp._open_fsuipc(pyuipc)
    except Exception:
        pyuipc = None

    names: list[str] | None
    note: str
    with sp._LOCK:
        names, note = _try_enumerate_lvar_names(sp, sm, pyuipc)
    print(f"\nEnumeration: {note}")

    if not names:
        if lvar_candidates_path:
            try:
                text = Path(lvar_candidates_path).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                print(f"Could not read --lvar-candidates file: {exc}")
                return 2
            names = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
            print(f"Using {len(names)} candidate L:Var names from {lvar_candidates_path}")
        else:
            print(
                "\nDiscovery skipped: no way to list L:Vars on this runtime.\n"
                "Provide a candidate list with --lvar-candidates <file> (one L:Var "
                "name per line) to diff named reads instead."
            )
            return 0

    print(f"Baseline: reading {len(names)} L:Vars...")
    with sp._LOCK:
        before = _snapshot_lvars(sp, sm, pyuipc, names)
    print(f"Baseline captured: {len(before)} L:Vars returned a value.")

    try:
        input(f"\n>>> Move the {label.upper()} control NOW (e.g. full deflection), then press Enter...")
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return 0

    with sp._LOCK:
        after = _snapshot_lvars(sp, sm, pyuipc, names)

    changes: list[tuple[str, float, float, float]] = []
    for name in names:
        b = before.get(name)
        a = after.get(name)
        if b is None or a is None:
            continue
        delta = a - b
        if abs(delta) > 1e-6:
            changes.append((name, b, a, delta))
    changes.sort(key=lambda row: abs(row[3]), reverse=True)

    print("\n" + "-" * 78)
    if not changes:
        print(f"No L:Var changed for '{label}'. Either the axis is not L:Var-driven, "
              "the move was too small, or enumeration missed it.")
    else:
        print(f"L:Vars that changed for '{label}' (sorted by |delta|):")
        for name, b, a, delta in changes:
            print(f"  {name}: {b:.4f} -> {a:.4f}  (delta {delta:+.4f})")
    print("-" * 78)
    print("Re-run with a different --label (aileron / elevator / rudder / throttle) "
          "to map each axis.")
    return 0


# ==========================================================================
# Live view
# ==========================================================================
def _enable_windows_ansi() -> bool:
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return True
    except Exception:
        return False


def _fmt_value(value: Any, is_offset: bool) -> str:
    if value is None:
        return "--"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)[:8]
    if is_offset:
        return f"{num:+.0f}"
    return f"{num:+.3f}"


class MovementTracker:
    """Latches whether each probe's value has moved beyond its epsilon."""

    def __init__(self) -> None:
        self._start: dict[tuple[str, str], float] = {}
        self.moved: dict[tuple[str, str], bool] = {}

    def update(self, probe: dict[str, Any], value: Any) -> bool:
        if value is None:
            return self.moved.get((probe["control"], probe["short"]), False)
        try:
            num = float(value)
        except (TypeError, ValueError):
            return False
        pkey = (probe["control"], probe["short"])
        if pkey not in self._start:
            self._start[pkey] = num
            self.moved.setdefault(pkey, False)
            return False
        if abs(num - self._start[pkey]) > probe["eps"]:
            self.moved[pkey] = True
        return self.moved[pkey]


def _cell_for(column: str, control: str, snap: dict[str, dict], probes: list[dict], tracker: MovementTracker) -> str:
    parts: list[str] = []
    for probe in probes:
        if probe["control"] != control or probe["column"] != column:
            continue
        sub = snap.get(probe["source"], {}) or {}
        value = sub.get(probe["key"])
        moved = tracker.update(probe, value)
        is_offset = probe["source"] == "fs_raw"
        marker = "*" if moved else " "
        parts.append(f"{probe['short']}={_fmt_value(value, is_offset)}{marker}")
    return "  ".join(parts) if parts else "-"


def _render_frame(snap: dict[str, dict], probes: list[dict], tracker: MovementTracker,
                  sc: "SimConnectProbe", fs: "FsuipcProbe", elapsed: float) -> list[str]:
    lines: list[str] = []
    lines.append("OPS ROOM CONTROL INPUT PROBE  (READ-ONLY)  "
                 f"elapsed={elapsed:5.1f}s   (Ctrl+C to stop -> verdict)")

    ac = (snap.get("sc_deriv") or {}).get("aircraft") or (snap.get("fs_deriv") or {}).get("aircraft") or {}
    ac_title = ac.get("title") if isinstance(ac, dict) else None
    lines.append(f"Aircraft: {ac_title or 'unknown (load a flight)'}")

    sc_state = "OK" if sc.available else f"not available ({sc.reason})"
    fs_state = "OK" if fs.available else f"not available ({fs.reason})"
    lines.append(f"SimConnect: {sc_state}")
    lines.append(f"FSUIPC:     {fs_state}")
    lines.append("* marks a channel that has moved beyond its epsilon since start.")
    lines.append("")

    cw = 34
    header = (f"{'CONTROL':<9}| {'SimConnect raw SimVars':<{cw}}| "
              f"{'OPS ROOM SimConnect-derived':<{cw}}| "
              f"{'FSUIPC raw offsets':<{cw}}| OPS ROOM FSUIPC-derived")
    lines.append(header)
    lines.append("-" * len(header))
    for control in CONTROL_ORDER:
        c1 = _cell_for(COL_SC_RAW, control, snap, probes, tracker)
        c2 = _cell_for(COL_SC_DERIV, control, snap, probes, tracker)
        c3 = _cell_for(COL_FS_RAW, control, snap, probes, tracker)
        c4 = _cell_for(COL_FS_DERIV, control, snap, probes, tracker)
        lines.append(f"{control:<9}| {c1:<{cw}}| {c2:<{cw}}| {c3:<{cw}}| {c4}")
    return lines


def _print_verdict(probes: list[dict], tracker: MovementTracker,
                   sc: "SimConnectProbe", fs: "FsuipcProbe") -> None:
    print("\n" + "=" * 78)
    print("PER-CONTROL VERDICT  (which source(s) actually carried the input)")
    print("=" * 78)
    if not sc.available:
        print(f"NOTE: SimConnect was not available ({sc.reason}).")
    if not fs.available:
        print(f"NOTE: FSUIPC was not available ({fs.reason}).")

    for control in CONTROL_ORDER:
        moved_categories: list[str] = []
        seen: set[str] = set()
        for probe in probes:
            if probe["control"] != control:
                continue
            if tracker.moved.get((probe["control"], probe["short"]), False):
                if probe["category"] not in seen:
                    seen.add(probe["category"])
                    moved_categories.append(probe["category"])
        print(f"\n{control.upper()}")
        if moved_categories:
            for cat in moved_categories:
                print(f"  MOVED: {cat}")
            print("  => Standard channels carry it (OPS ROOM can capture this input directly).")
        else:
            standard_available = sc.available or fs.available
            if standard_available:
                print("  No standard channel moved during this session.")
                print("  => Likely needs aircraft-specific L:Vars (run --discover for this axis).")
            else:
                print("  No provider was available; move not observed.")
    print("\n" + "=" * 78)
    print("Decision guide: a control marked 'standard channels carry it' can be")
    print("recorded via SimConnect/FSUIPC as-is. A control with no standard movement")
    print("needs aircraft L:Vars; use --discover --label <axis> to find them.")
    print("=" * 78)


def run_live(hz: float, seconds: float | None) -> int:
    _ensure_repo_on_path()
    hz = max(1.0, min(60.0, float(hz)))
    interval = 1.0 / hz

    sc = SimConnectProbe()
    fs = FsuipcProbe()
    sc.start()
    fs.start()

    if not sc.available and not fs.available:
        print("Neither provider is available. Nothing to probe.")
        print(f"  SimConnect: {sc.reason}")
        print(f"  FSUIPC:     {fs.reason}")
        print("Ensure MSFS is running with an aircraft loaded and that this venv has "
              "SimConnect (and optionally pyuipc) installed.")
        return 1

    probes = _build_probes()
    tracker = MovementTracker()
    ansi = _enable_windows_ansi()

    start = time.monotonic()
    prev_lines = 0
    print("Starting live probe... move each control (aileron, elevator, rudder, "
          "throttles) fully at least once.\n")
    try:
        while True:
            now = time.monotonic()
            elapsed = now - start
            snap = {
                "sc_raw": sc.read_raw(),
                "sc_deriv": sc.read_derived(),
                "fs_raw": fs.read_raw(),
                "fs_deriv": fs.read_derived(),
            }
            lines = _render_frame(snap, probes, tracker, sc, fs, elapsed)

            if ansi and prev_lines:
                sys.stdout.write(f"\033[{prev_lines}A")
            buf = []
            for line in lines:
                if ansi:
                    buf.append("\033[2K" + line + "\n")
                else:
                    buf.append(line + "\n")
            if not ansi:
                buf.append("-" * 40 + "\n")
            sys.stdout.write("".join(buf))
            sys.stdout.flush()
            prev_lines = len(lines) if ansi else 0

            if seconds is not None and elapsed >= seconds:
                break
            sleep_for = interval - (time.monotonic() - now)
            if sleep_for > 0:
                time.sleep(sleep_for)
    except KeyboardInterrupt:
        print("\n(stopped)")

    _print_verdict(probes, tracker, sc, fs)
    return 0


# ==========================================================================
# CLI
# ==========================================================================
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="probe_control_inputs.py",
        description="READ-ONLY OPS ROOM diagnostic: find which source carries pilot control inputs.",
    )
    parser.add_argument("--hz", type=float, default=20.0,
                        help="Live poll rate in Hz (default 20, clamped 1..60).")
    parser.add_argument("--seconds", type=float, default=None,
                        help="Auto-stop after N seconds (default: run until Ctrl+C).")
    parser.add_argument("--discover", action="store_true",
                        help="L:Var move-and-diff discovery mode instead of the live view.")
    parser.add_argument("--label", type=str, default="aileron",
                        help="Axis label for --discover (aileron/elevator/rudder/throttle).")
    parser.add_argument("--lvar-candidates", type=str, default=None,
                        help="Optional file of candidate L:Var names (one per line) for "
                             "--discover when enumeration is unavailable.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.discover:
        return run_discover(args.label, args.lvar_candidates)
    return run_live(args.hz, args.seconds)


if __name__ == "__main__":
    raise SystemExit(main())
