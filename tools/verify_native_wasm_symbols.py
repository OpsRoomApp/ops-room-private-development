from __future__ import annotations

import sys
from pathlib import Path

REQUIRED = [
    b"fsChartsGetIndex",
    b"fsChartsGetPages",
    b"fsCameraAcquire",
    b"fsCameraGetStatus",
    b"fsCameraSet",
    b"fsCameraRelease",
]

FORBIDDEN = [
    b"MSFS Charts API header MSFS_Charts.h is not available",
    b"MSFS_Camera.h is not available",
    b"Charts/Camera API headers missing",
]


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: verify_native_wasm_symbols.py <OpsRoomNativeApi2024.wasm>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"ERROR: WASM file not found: {path}", file=sys.stderr)
        return 2
    data = path.read_bytes()
    missing = [name.decode("ascii") for name in REQUIRED if name not in data]
    forbidden = [name.decode("ascii", "replace") for name in FORBIDDEN if name in data]
    if missing or forbidden:
        print("ERROR: OpsRoomNativeApi2024.wasm is not a real MSFS 2024 Charts/Camera validation build.", file=sys.stderr)
        if missing:
            print("Missing required imports/symbol names:", ", ".join(missing), file=sys.stderr)
        if forbidden:
            print("Fallback/stub strings still present:", ", ".join(forbidden), file=sys.stderr)
        print("The native WASM must import the documented MSFS Charts/Camera API symbols. The project uses official headers when present and documented fallback declarations when they are absent.", file=sys.stderr)
        return 1
    print("OK: Native API WASM contains required MSFS Charts/Camera API symbols.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
