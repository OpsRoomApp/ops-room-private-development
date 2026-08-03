from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


RELEASE_CODENAME = "Release Migration"
RELEASE_CHANNEL = "stable"
RELEASE_MESSAGE = "OPS ROOM {version} is available."
RELEASE_NOTES = (
    "OPS ROOM {version} is a reliability pass. Fenix/EFB detection holds its last known state across "
    "brief probe delays so Ground Control, Flight Watch and Black Box stay steady. RAAS and landing "
    "alerts are delivered reliably, including right after app start, with burst polling after a "
    "landing. Short SimConnect/FSUIPC telemetry gaps are bridged in flight recording while long gaps "
    "are still reported. Full PIREP PDF export inlines the current assets regardless of cache-busting "
    "version suffixes, and the Windows installer is produced again with the correct version name. "
    "Recording schema v2 is unchanged."
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description="Write OPS ROOM GitHub updater manifest")
    parser.add_argument("--version", required=True)
    parser.add_argument("--zip", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo", default="https://github.com/OpsRoomApp/ops-room-releases")
    parser.add_argument("--channel", default=RELEASE_CHANNEL)
    args = parser.parse_args()
    version = args.version.strip()
    zip_path = Path(args.zip)
    out_path = Path(args.out)
    digest = sha256(zip_path)
    sha_path = zip_path.with_suffix(zip_path.suffix + ".sha256")
    sha_path.write_text(f"{digest}  {zip_path.name}\n", encoding="ascii")
    # version already includes the 'v' prefix (e.g. '0.25.60')
    download_url = f"{args.repo}/releases/download/{version}/{zip_path.name}"
    manifest = {
        "latest_version": version,
        "version": version,
        "codename": RELEASE_CODENAME,
        "channel": args.channel,
        "minimum_supported_version": "0.22.0",
        "mandatory": False,
        "release_notes_url": f"{args.repo}/releases/tag/{version}",
        "download_url": download_url,
        "url": download_url,
        "sha256": digest,
        "message": RELEASE_MESSAGE.format(version=version),
        "notes": RELEASE_NOTES.format(version=version),
    }
    out_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
