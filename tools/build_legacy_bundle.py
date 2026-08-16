"""Regenerate the OPS ROOM in-sim legacy frontend bundle (Coherent GT / Chrome 49).

The MSFS in-game webview is Coherent GT (Chromium 49), which cannot parse the
modern ES2017+ syntax in ``app/static/opsroom.js``. This script produces two
*additive* artifacts so the in-sim tablet can run the same app without the
modern frontend ever being modified:

  1. ``app/static/opsroom.legacy.js`` - Babel-transpiled ``opsroom.js``
     (async/await, optional chaining, nullish coalescing, for..of and object
     spread lowered to Chrome 49; Babel inlines the regenerator runtime).
  2. ``app/static/index.legacy.html`` - a copy of ``index.html`` with the
     OpenLayers and pdf.js dependencies removed and the legacy scripts loaded
     instead (polyfills.legacy.js -> ol.legacy.js -> opsroom.legacy.js).

The legacy entry point is served from ``/static/index.legacy.html``; only the
in-sim tablet panel requests it. The normal browser/desktop path (``/`` ->
``index.html`` -> ``opsroom.js``) is byte-for-byte unchanged.

Usage (from the repo ``source`` directory)::

    python tools/build_legacy_bundle.py

Requires Node.js + npm. Babel dependencies are installed into
``tools/legacy-build/node_modules`` (gitignored) on first run.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

#: Head block to strip from the legacy HTML (OpenLayers CSS + pdf.js).
_HEAD_REMOVE = """\
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ol@10.9.0/ol.css" />
  <link rel="stylesheet" href="/static/opsroom.css?v=0-25-1" />
  <script src="/static/pdf.min.js?v=0-25-1"></script>
  <script>pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/pdf.worker.min.js?v=0-25-1';</script>"""

_HEAD_KEEP = """\
  <link rel="stylesheet" href="/static/opsroom.css?v=0-25-1" />
  <link rel="stylesheet" href="/static/opsroom.legacy.css?v=0-25-1" />"""

_BODY_OLD = """\
  <script src="https://cdn.jsdelivr.net/npm/ol@10.9.0/dist/ol.js"></script>
  <script src="/static/opsroom.js?v=0-25-1"></script>"""

_BODY_NEW = """\
  <script src="/static/polyfills.legacy.js?v=0-25-1"></script>
  <script src="/static/ol.legacy.js?v=0-25-1"></script>
  <script src="/static/opsroom.legacy.js?v=0-25-1"></script>
  <script>
    // Signal a hosting MSFS 2024 EFB shell (if this page is inside its iframe)
    // that OPS ROOM is running, so the shell can reveal the app and stop its
    // retry loop. Harmless everywhere else (no-op postMessage to parent).
    (function () {
      try {
        var ping = function () { window.parent.postMessage({ type: "opsroom-ready" }, "*"); };
        window.addEventListener("load", ping);
        window.setTimeout(ping, 1500);
        window.setInterval(ping, 2000);
      } catch (e) {}
    })();
  </script>"""


def _source_root() -> Path:
    return Path(__file__).resolve().parent.parent


def regenerate_legacy_html(root: Path) -> None:
    src = root / "app" / "static" / "index.html"
    dst = root / "app" / "static" / "index.legacy.html"
    html = src.read_text(encoding="utf-8")
    if _HEAD_REMOVE not in html:
        print("WARN: index.html head block no longer matches the legacy template; "
              "index.legacy.html was not regenerated. Update build_legacy_bundle.py.", file=sys.stderr)
        return
    if _BODY_OLD not in html:
        print("WARN: index.html body script block no longer matches the legacy template; "
              "index.legacy.html was not regenerated. Update build_legacy_bundle.py.", file=sys.stderr)
        return
    html = html.replace(_HEAD_REMOVE, _HEAD_KEEP, 1)
    html = html.replace(_BODY_OLD, _BODY_NEW, 1)
    dst.write_text(html, encoding="utf-8")
    print(f"  index.legacy.html regenerated from index.html")


def run_babel(build_dir: Path) -> None:
    if not (build_dir / "node_modules").is_dir():
        print("  installing legacy build deps (npm install)...")
        subprocess.run("npm install --no-audit --no-fund", cwd=build_dir, shell=True, check=True)
    print("  transpiling opsroom.js -> opsroom.legacy.js (Babel, target chrome49)...")
    subprocess.run("npm run build", cwd=build_dir, shell=True, check=True)


def main() -> int:
    root = _source_root()
    print("Building OPS ROOM in-sim legacy frontend (Chrome 49)")
    regenerate_legacy_html(root)
    run_babel(root / "tools" / "legacy-build")
    print("  legacy bundle ready:")
    print(f"    {root / 'app' / 'static' / 'index.legacy.html'}")
    print(f"    {root / 'app' / 'static' / 'opsroom.legacy.js'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
