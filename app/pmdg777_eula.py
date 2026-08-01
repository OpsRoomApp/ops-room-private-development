from __future__ import annotations

"""PMDG 777 SDK EULA display and acceptance state.

The PMDG 777 SDK requires applications using the SDK to display the SDK EULA
and require a manual opt-in at installation or first use. Acceptance is stored
outside the source/install directory in the normal OPS ROOM app-data folder.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from .settings_store import app_data_dir

EULA_REVISION = "PMDG 777 SDK JUN 2024"
EULA_FILENAME = "PMDG_777_SDK_EULA.txt"
ACCEPTANCE_FILENAME = "pmdg777_sdk_eula_acceptance.json"


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []
    try:
        paths.append(Path(__file__).resolve().parents[1] / EULA_FILENAME)
    except Exception:
        pass
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        paths.append(Path(bundle) / EULA_FILENAME)
    paths.append(Path.cwd() / EULA_FILENAME)
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def eula_path() -> Path | None:
    return next((path for path in _candidate_paths() if path.is_file()), None)


def eula_text() -> str:
    path = eula_path()
    if not path:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def eula_sha256() -> str:
    return hashlib.sha256(eula_text().encode("utf-8")).hexdigest()


def acceptance_path() -> Path:
    return app_data_dir() / ACCEPTANCE_FILENAME


def acceptance_record() -> dict[str, Any]:
    try:
        data = json.loads(acceptance_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def accepted() -> bool:
    record = acceptance_record()
    digest = eula_sha256()
    return bool(
        digest
        and record.get("accepted") is True
        and record.get("revision") == EULA_REVISION
        and record.get("eula_sha256") == digest
    )


def accept() -> dict[str, Any]:
    text = eula_text()
    if not text:
        return {"ok": False, "accepted": False, "reason": f"{EULA_FILENAME} is missing from the OPS ROOM installation."}
    record = {
        "accepted": True,
        "revision": EULA_REVISION,
        "eula_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "accepted_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "notice": "Accepted manually in OPS ROOM before enabling the read-only PMDG 777 SDK integration.",
    }
    path = acceptance_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return {"ok": True, **record, "path": str(path)}


def status() -> dict[str, Any]:
    text = eula_text()
    record = acceptance_record()
    return {
        "available": bool(text),
        "accepted": accepted(),
        "revision": EULA_REVISION,
        "eula_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
        "source_file": str(eula_path()) if eula_path() else None,
        "acceptance_file": str(acceptance_path()),
        "accepted_utc": record.get("accepted_utc") if isinstance(record, dict) else None,
    }
