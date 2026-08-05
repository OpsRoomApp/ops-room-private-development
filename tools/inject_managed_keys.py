from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

DEFAULT_PRIVATE_KEY_PATH = r"E:\Ops Room Project\private_keys\opsroom_api_keys.local.json"
ALLOWED_KEYS = {
    "openaip_key",
    "openaip_proxy_url",
    "openaip_proxy_token",
    "lido_subscription_key",
    "lido_charts_subscription_key",
    "lido_library_code",
    "lido_revision_week",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Inject private managed API keys into OPS ROOM backend constants for a local build.")
    parser.add_argument("--keys", default=DEFAULT_PRIVATE_KEY_PATH)
    parser.add_argument("--target", default="app/managed_keys.py")
    args = parser.parse_args()
    source = Path(args.keys)
    target = Path(args.target)
    payload = {}
    if source.is_file():
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise SystemExit("Private key file must contain a JSON object")
        payload = {k: str(v).strip() for k, v in data.items() if k in ALLOWED_KEYS and str(v).strip()}
    encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii") if payload else ""
    text = target.read_text(encoding="utf-8")
    marker = 'MANAGED_KEYS_B64 = '
    lines = []
    replaced = False
    for line in text.splitlines():
        if line.startswith(marker):
            lines.append(f'MANAGED_KEYS_B64 = "{encoded}"')
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        raise SystemExit("MANAGED_KEYS_B64 marker not found")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if payload:
        print(f"Managed API keys injected for: {', '.join(sorted(payload))}")
    else:
        print("No private managed API key file found; building without managed online keys.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
