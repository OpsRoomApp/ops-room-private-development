from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
# Repo currently has folders such as custom_logos, flightaware_logos, radarbox_logos,
# plus banner folders. Logo folders are preferred, but the script can scan everything.
SOURCE_PRIORITY = [
    "custom_logos",
    "flightaware_logos",
    "radarbox_logos",
    "logos",
    "avcodes_banners",
    "custom_banners",
    "fr24_banners",
    "radarbox_banners",
    "banners",
]


def _looks_like_icao(stem: str) -> bool:
    return re.fullmatch(r"[A-Z0-9]{2,4}", stem.upper()) is not None


def copy_logos(repo: Path, out: Path, overwrite: bool = False, scan_all: bool = True) -> None:
    out.mkdir(parents=True, exist_ok=True)
    copied = 0
    skipped = 0
    seen_sources: set[Path] = set()

    folders = [repo / name for name in SOURCE_PRIORITY if (repo / name).exists()]
    if scan_all:
        folders.append(repo)

    for folder in folders:
        for src in folder.rglob("*"):
            if src in seen_sources or src.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            seen_sources.add(src)
            stem = src.stem.strip().upper()
            if not _looks_like_icao(stem):
                continue
            dst = out / f"{stem}{src.suffix.lower()}"
            preferred_png = out / f"{stem}.png"
            if preferred_png.exists() and src.suffix.lower() != ".png" and not overwrite:
                skipped += 1
                continue
            if dst.exists() and not overwrite:
                skipped += 1
                continue
            shutil.copy2(src, dst)
            copied += 1

    print(f"Copied {copied} images to {out}")
    print(f"Skipped {skipped} existing images")
    print("Restart the board after importing logos, or use --reload while running uvicorn.")
    print("Open http://localhost:8080/api/logos to verify that logos are indexed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import airline/operator logos into VATSIM Traffic Board assets.")
    # New names
    parser.add_argument("--repo", help="Path to cloned Jxck-S/airline-logos repository")
    parser.add_argument("--out", default="app/assets/logos", help="Output logos folder")
    # Backward-compatible names from the first instructions
    parser.add_argument("--source", help="Alias for --repo")
    parser.add_argument("--dest", help="Alias for --out")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing logos")
    parser.add_argument("--no-scan-all", action="store_true", help="Only scan known logo/banner folders")
    args = parser.parse_args()
    repo_arg = args.repo or args.source
    out_arg = args.dest or args.out
    if not repo_arg:
        raise SystemExit("Provide --repo PATH or --source PATH")
    copy_logos(Path(repo_arg).expanduser().resolve(), Path(out_arg).expanduser().resolve(), args.overwrite, scan_all=not args.no_scan_all)


if __name__ == "__main__":
    main()
