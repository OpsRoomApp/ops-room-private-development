from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FORBIDDEN_TEXT = (
    "Little " + "Navmap",
    "little_" + "navmap",
    "Navi" + "graph",
    "NAVI" + "GRAPH",
    "open" + "aip_managed",
)
TEXT_SUFFIXES = {
    ".bat", ".cmd", ".css", ".csv", ".html", ".ini", ".js", ".json", ".md",
    ".py", ".txt", ".xml", ".yaml", ".yml",
}

# ---------------------------------------------------------------------------
# Static mojibake scan (Black Box telemetry & UI fix - Task 12.2)
#
# Flags the mis-decoded-UTF-8 signatures called out in the design (section 8)
# and Requirements 2.15 / 3.12 across UI text assets under app/static/** plus
# templates. Static-only: it reads bytes and reports; it changes no behavior.
#
# The signature families below are the broad two-code-point leads requested by
# the task (Ã. Â. â€. â†. â˜. ðŸ.) plus the U+FFFD replacement char. They are a
# superset of the narrower per-glyph list in tests/mojibake_scan.py (which the
# Task 1 "Mechanism F" exploration check uses), so after the Task 12 byte repair
# BOTH scanners report zero and therefore agree.
# ---------------------------------------------------------------------------
MOJIBAKE_SIGNATURES: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("latin_capital_A_tilde",     re.compile("\u00c3.")),        # Ã.  -> e.g. Ã— (×)
    ("latin_capital_A_circumflex", re.compile("\u00c2.")),       # Â.  -> e.g. Â· (·) Â° (°) Â© (©)
    ("e2_euro_lead",              re.compile("\u00e2\u20ac.")),  # â€. -> em/en dash, ellipsis, bullet
    ("e2_dagger_lead",            re.compile("\u00e2\u2020.")),  # â†. -> right arrow (→)
    ("e2_small_tilde_lead",       re.compile("\u00e2\u02dc.")),  # â˜. -> trigram (☰), coffee (☕)
    ("f0_supplementary_emoji",    re.compile("\u00f0\u0178.")),  # ðŸ. -> supplementary emoji (🐞)
    ("replacement_char",          re.compile("\ufffd")),          # U+FFFD
)

# Correctly-encoded, intentional Unicode that legitimately remains in the UI
# after the repair. Each is a single code point that does NOT begin with a
# mojibake lead byte, so none of them can match a signature above - they are
# listed here for traceability and drive the (deliberately conservative)
# allowlist check in ``scan_text_for_mojibake``.
#
# IMPORTANT: suppression requires the ENTIRE matched sequence to consist only of
# these code points. We do NOT allowlist by "context contains this glyph",
# because several intentional glyphs (— · ° • –) are also the TRAILING code
# point of a mojibake run (e.g. "Ã—" ends in U+2014, "Â·" ends in U+00B7), so a
# context-substring allowlist would silently hide real mojibake.
INTENTIONAL_UNICODE_ALLOWLIST: tuple[str, ...] = (
    "\u2014",       # — em dash
    "\u2013",       # – en dash
    "\u2026",       # … ellipsis
    "\u2022",       # • bullet
    "\u2192",       # → right arrow
    "\u2212",       # − minus sign
    "\u2265",       # ≥ greater-than-or-equal
    "\u2713",       # ✓ check mark
    "\u25b2",       # ▲ up-pointing triangle
    "\u2630",       # ☰ trigram (hamburger menu)
    "\u2615",       # ☕ hot beverage
    "\U0001f41e",   # 🐞 lady beetle (Report Bug)
    "\u00b7",       # · middle dot
    "\u00b0",       # ° degree
    "\u00a9",       # © copyright
    "\u00d7",       # × multiplication sign
    "\u0394",       # Δ Greek capital delta
)

# Suffixes treated as UI text assets for the mojibake scan.
MOJIBAKE_TEXT_SUFFIXES = TEXT_SUFFIXES | {".svg", ".webmanifest"}


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def scan_text_for_mojibake(
    text: str,
    allowlist: tuple[str, ...] = INTENTIONAL_UNICODE_ALLOWLIST,
) -> list[dict]:
    """Return every mojibake signature found in ``text`` that is not allowlisted.

    A match is suppressed only when the whole matched sequence is composed
    entirely of allowlisted intentional code points - which never happens for a
    genuine mojibake run (those always start with a Latin-1 lead byte that is
    not in the allowlist), so real defects are never hidden.
    """
    findings: list[dict] = []
    for name, pattern in MOJIBAKE_SIGNATURES:
        for match in pattern.finditer(text):
            seq = match.group(0)
            if seq and all(ch in allowlist for ch in seq):
                continue
            idx = match.start()
            context = text[max(0, idx - 24): idx + 24].replace("\n", " ").strip()
            findings.append({
                "signature": name,
                "line": text.count("\n", 0, idx) + 1,
                "context": context,
            })
    return findings


def _in_ui_asset_scope(rel_posix: str, root_is_scoped: bool) -> bool:
    """True when a package-relative path belongs to the app/static or templates scope."""
    if root_is_scoped:
        return True
    p = "/" + rel_posix
    return "/app/static/" in p or "/app/templates/" in p or "/templates/" in p


def scan_tree_for_mojibake(root: Path | str) -> list[str]:
    """Scan UI text assets under ``root`` for mojibake; return formatted violations.

    When ``root`` is itself a ``static``/``templates`` directory (e.g. the source
    ``app/static``), every text asset under it is scanned. Otherwise the scan is
    scoped to the ``app/static``/``templates`` subtrees within the tree (so a
    packaged dist folder is only checked over its UI assets).
    """
    root = Path(root)
    if not root.exists():
        return [f"mojibake scan root not found: {root}"]
    root_is_scoped = root.name.lower() in {"static", "templates"}
    violations: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in MOJIBAKE_TEXT_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        if not _in_ui_asset_scope(rel, root_is_scoped):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            violations.append(f"could not scan text asset {rel}: {exc}")
            continue
        for finding in scan_text_for_mojibake(text):
            violations.append(
                f"mojibake [{finding['signature']}] {rel}:{finding['line']} ...{finding['context']}..."
            )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the public OPS ROOM package: no exposed private/provider artifacts and no UI mojibake."
    )
    parser.add_argument("--root", help="Dist/public package folder to scan for forbidden artifacts + UI mojibake")
    parser.add_argument(
        "--static-root",
        help="UI asset directory to scan for mojibake directly (e.g. app/static). "
             "Defaults to the repo's app/static when neither --root nor --static-root is given.",
    )
    args = parser.parse_args()

    violations: list[str] = []
    scanned_any = False

    if args.root:
        scanned_any = True
        root = Path(args.root)
        if not root.exists():
            print(f"ERROR: package root not found: {root}")
            return 2
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            lower_name = path.name.lower()
            if path.suffix.lower() == ".key" or ".key" in lower_name:
                violations.append(f"forbidden key file: {rel}")
            if path.suffix.lower() == ".opus":
                violations.append(f"forbidden bundled RAAS audio clip: {rel}")
            if is_text_file(path):
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError as exc:
                    violations.append(f"could not scan text file {rel}: {exc}")
                    continue
                for token in FORBIDDEN_TEXT:
                    if token in text:
                        violations.append(f"forbidden text token {token!r}: {rel}")
        # Also flag mojibake in the packaged UI assets (scoped to static/templates).
        violations += scan_tree_for_mojibake(root)

    if args.static_root:
        scanned_any = True
        violations += scan_tree_for_mojibake(args.static_root)

    if not scanned_any:
        default_static = Path(__file__).resolve().parent.parent / "app" / "static"
        print(f"(no --root/--static-root given; scanning source UI assets under {default_static})")
        violations += scan_tree_for_mojibake(default_static)

    if violations:
        print("PUBLIC PACKAGE VERIFICATION FAILED")
        for item in violations:
            print(" -", item)
        return 1
    print("Public package verification OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
