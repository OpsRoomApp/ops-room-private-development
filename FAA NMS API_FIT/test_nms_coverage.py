"""
NMS-API coverage test — checks whether the FAA NMS-API returns NOTAM data
for non-US airports, or only for US ones.

USAGE:
    1. pip install requests
    2. Set your credentials as environment variables (don't hardcode them):
         set NMS_CLIENT_ID=your_key_here        (Windows cmd)
         set NMS_CLIENT_SECRET=your_secret_here
       or on PowerShell:
         $env:NMS_CLIENT_ID="your_key_here"
         $env:NMS_CLIENT_SECRET="your_secret_here"
    3. Run: python test_nms_coverage.py

    Defaults to the Staging (Pre-Prod) environment, matching what the FAQ
    recommends for testing. Pass --env prod to hit the production host once
    you're ready (only do this once staging confirms your credentials work).
"""

import argparse
import os
import sys

import requests

ENVIRONMENTS = {
    "fit": "https://api-fit.cgifederal-aim.com",
    "staging": "https://api-staging.cgifederal-aim.com",
    "prod": "https://api-nms.aim.faa.gov",
}

# A mix of US and non-US airports to make the comparison unambiguous.
# US ones are expected to return data. Western Europe (EGLL/LFPG/EDDF)
# already confirmed working in an earlier run — this list adds other world
# regions to check how far the coverage actually extends before assuming
# it's comprehensively global.
TEST_LOCATIONS = [
    ("KJFK", "New York JFK — US, expected to have data"),
    ("KATL", "Atlanta — US, expected to have data"),
    ("EGLL", "London Heathrow — Western Europe, already confirmed"),
    ("RJTT", "Tokyo Haneda — East Asia"),
    ("RJAA", "Tokyo Narita — East Asia"),
    ("OMDB", "Dubai — Middle East"),
    ("SBGR", "São Paulo Guarulhos — South America"),
    ("YSSY", "Sydney — Oceania"),
    ("FAOR", "Johannesburg O.R. Tambo — Africa"),
    ("VABB", "Mumbai — South Asia"),
    ("ZBAA", "Beijing Capital — China"),
    ("UUEE", "Moscow Sheremetyevo — Russia/CIS"),
]


def get_bearer_token(base_host: str, client_id: str, client_secret: str) -> str:
    resp = requests.post(
        f"{base_host}/v1/auth/token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    token = body.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in response: {body}")
    print(f"[ok] Got bearer token, expires in {body.get('expires_in')}s")
    return token


def check_location(base_host: str, token: str, icao: str, note: str) -> None:
    resp = requests.get(
        f"{base_host}/nmsapi/v1/notams/checklist",
        params={"location": icao},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    print(f"\n--- {icao} ({note}) ---")
    print(f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"Body: {resp.text[:500]}")
        return
    data = resp.json()
    checklist = (data.get("data") or {}).get("checklist") or []
    print(f"NOTAM checklist entries returned: {len(checklist)}")
    if not checklist:
        return

    first = checklist[0]
    print(f"Checklist entry (index only, no text yet): {first}")
    fetch_full_notam(base_host, token, icao, first["number"])


def fetch_full_notam(base_host: str, token: str, icao: str, number: str) -> None:
    """
    Second-stage call: the checklist only gives you an index (id/number).
    To get the actual NOTAM text, coordinates, and effective dates, you
    have to call /v1/notams with the real filter + the required
    nmsResponseFormat header.
    """
    resp = requests.get(
        f"{base_host}/nmsapi/v1/notams",
        params={"location": icao, "notamNumber": number},
        headers={
            "Authorization": f"Bearer {token}",
            "nmsResponseFormat": "GEOJSON",
        },
        timeout=15,
    )
    print(f"  -> full NOTAM fetch: HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"     Body: {resp.text[:500]}")
        return
    data = resp.json()
    features = (data.get("data") or {}).get("geojson") or []
    if not features:
        print("     No geojson features returned.")
        return
    props = features[0].get("properties", {}).get("coreNOTAMData", {})
    notam = props.get("notam", {})
    print(f"     TEXT: {notam.get('text')}")
    print(f"     EFFECTIVE: {notam.get('effectiveStart')} -> {notam.get('effectiveEnd')}")
    print(f"     COORDS: {notam.get('coordinates')}  RADIUS: {notam.get('radius')}")
    for t in props.get("notamTranslation", []):
        if t.get("type") == "ICAO":
            print(f"     ICAO FORMAT: {t.get('icao_message')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", choices=ENVIRONMENTS.keys(), default="staging")
    args = parser.parse_args()

    client_id = os.environ.get("NMS_CLIENT_ID")
    client_secret = os.environ.get("NMS_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERROR: set NMS_CLIENT_ID and NMS_CLIENT_SECRET environment variables first.")
        return 1

    base_host = ENVIRONMENTS[args.env]
    print(f"Using {args.env} environment: {base_host}")

    try:
        token = get_bearer_token(base_host, client_id, client_secret)
    except Exception as exc:
        print(f"ERROR getting token: {exc}")
        return 1

    for icao, note in TEST_LOCATIONS:
        try:
            check_location(base_host, token, icao, note)
        except Exception as exc:
            print(f"ERROR checking {icao}: {exc}")

    print(
        "\nVerdict guide: if the US airports return entries and the non-US "
        "ones return zero entries (or a 'location not found'-style error), "
        "that confirms US-only coverage. If any non-US airport returns real "
        "NOTAM data, coverage is broader than assumed — update the app's "
        "scoping accordingly."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
