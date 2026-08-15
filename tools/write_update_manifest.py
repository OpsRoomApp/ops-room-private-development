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
    parser.add_argument(
        "--site",
        default="https://opsroom.live",
        help="Primary download base (default: https://opsroom.live). Pass an empty string to emit GitHub-only URLs.",
    )
    parser.add_argument("--channel", default=RELEASE_CHANNEL)
    # #78 bridge: dual-publish. When --installer is given, the manifest gains
    # the additive installer_url/installer_sha256 fields. Old updaters ignore
    # unknown fields, so this is safe to publish while v0.24.1 is still on the
    # zip path; the bridge updater uses the installer path for installer-
    # managed installs and the zip path for loose-folder installs.
    parser.add_argument("--installer", default="", help="Path to the Setup .exe to dual-publish in the manifest")
    args = parser.parse_args()
    version = args.version.strip()
    zip_path = Path(args.zip)
    out_path = Path(args.out)
    digest = sha256(zip_path)
    sha_path = zip_path.with_suffix(zip_path.suffix + ".sha256")
    sha_path.write_text(f"{digest}  {zip_path.name}\n", encoding="ascii")
    # The release tag is the plain version (no 'v' prefix).
    repo_download = f"{args.repo}/releases/download/{version}/{zip_path.name}"
    site = (args.site or "").strip()
    # Website (opsroom.live /downloads/) is the primary download host; the
    # GitHub Releases copy is the fallback when the site is unreachable. With
    # --site "" the manifest keeps the historical GitHub-only URLs.
    download_url = f"{site}/downloads/{zip_path.name}" if site else repo_download
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
    if site and download_url != repo_download:
        manifest["fallback_download_url"] = repo_download
    installer = str(args.installer or "").strip()
    if installer:
        installer_path = Path(installer)
        if not installer_path.is_file():
            raise SystemExit(f"Installer file not found: {installer}")
        installer_digest = sha256(installer_path)
        installer_name = installer_path.name
        installer_url = f"{site}/downloads/{installer_name}" if site else f"{args.repo}/releases/download/{version}/{installer_name}"
        manifest["installer_url"] = installer_url
        manifest["installer_sha256"] = installer_digest
        if site:
            # Same bytes on GitHub Releases, so the checksum is identical.
            manifest["fallback_installer_url"] = f"{args.repo}/releases/download/{version}/{installer_name}"
            manifest["fallback_installer_sha256"] = installer_digest
    out_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
