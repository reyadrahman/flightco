#!/usr/bin/env python3
"""
Pulls real flights that departed Hazrat Shahjalal Int'l Airport (VGHS / DAC)
in the last N hours from the OpenSky Network REST API, and writes them to
data/flights.json for the site to read.

Auth: OpenSky retired basic auth on 2026-03-18. This script uses their
OAuth2 client-credentials flow. Create an API client at
https://opensky-network.org/ -> Account page, then set these as environment
variables (in GitHub Actions: repo Settings -> Secrets and variables -> Actions):

    OPENSKY_CLIENT_ID
    OPENSKY_CLIENT_SECRET

Without credentials the script still runs, but falls back to OpenSky's
reduced-rate anonymous access, which is less reliable.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

AIRPORT_ICAO = "VGHS"          # Dhaka / Hazrat Shahjalal Int'l
LOOKBACK_HOURS = 13            # covers the 12h gap between runs with a 1h safety margin (keep <=24h, must not cross >1 UTC day boundary)
TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
API_URL = "https://opensky-network.org/api/flights/departure"
OUT_PATH = Path(__file__).parent / "data" / "flights.json"

# ICAO airport -> friendly city/IATA, for the routes this site tracks
ROUTE_MAP = {
    "VGCB": {"city": "Cox's Bazar", "iata": "CXB", "kind": "domestic"},
    "VGEG": {"city": "Chattogram", "iata": "CGP", "kind": "domestic"},
    "VGSY": {"city": "Sylhet", "iata": "ZYL", "kind": "domestic"},
    "VGSD": {"city": "Saidpur", "iata": "SPD", "kind": "domestic"},
    "VGJR": {"city": "Jessore", "iata": "JSR", "kind": "domestic"},
    "VGBR": {"city": "Barishal", "iata": "BZL", "kind": "domestic"},
    "VGRJ": {"city": "Rajshahi", "iata": "RJH", "kind": "domestic"},
    "OMDB": {"city": "Dubai", "iata": "DXB", "kind": "intl"},
    "VTBS": {"city": "Bangkok", "iata": "BKK", "kind": "intl"},
    "WSSS": {"city": "Singapore", "iata": "SIN", "kind": "intl"},
    "WMKK": {"city": "Kuala Lumpur", "iata": "KUL", "kind": "intl"},
    "EGLL": {"city": "London", "iata": "LHR", "kind": "intl"},
    "KJFK": {"city": "New York", "iata": "JFK", "kind": "intl"},
    # Added based on last-12-months outbound travel patterns for Bangladeshi
    # travelers: Saudi Arabia is DAC's single largest international market
    # (labor + Umrah/Hajj travel); India (Kolkata) is the highest-frequency
    # neighbor route, heavily used for medical tourism; Malaysia and China are
    # the fastest-growing leisure/medical/shopping destinations; Qatar and
    # Oman are major Gulf labor-migration corridors; Nepal, Sri Lanka and the
    # Maldives are the most popular nearby leisure destinations.
    "OEJN": {"city": "Jeddah", "iata": "JED", "kind": "intl"},
    "VECC": {"city": "Kolkata", "iata": "CCU", "kind": "intl"},
    "ZGGG": {"city": "Guangzhou", "iata": "CAN", "kind": "intl"},
    "OTHH": {"city": "Doha", "iata": "DOH", "kind": "intl"},
    "OOMS": {"city": "Muscat", "iata": "MCT", "kind": "intl"},
    "VNKT": {"city": "Kathmandu", "iata": "KTM", "kind": "intl"},
    "VCBI": {"city": "Colombo", "iata": "CMB", "kind": "intl"},
    "VRMM": {"city": "Malé", "iata": "MLE", "kind": "intl"},
}

CALLSIGN_AIRLINE = [
    ("BBC", "Biman Bangladesh"), ("UBG", "US-Bangla"), ("AWA", "Air Astra"),
    ("NOS", "Novoair"), ("UAE", "Emirates"), ("FDB", "FlyDubai"),
    ("ABY", "Air Arabia"), ("AXM", "AirAsia"), ("SIA", "Singapore Airlines"),
    ("TGW", "Scoot"), ("MAS", "Malaysia Airlines"), ("BTK", "Batik Air"),
    ("SVA", "Saudia"), ("AIC", "Air India"), ("IGO", "IndiGo"),
    ("CSN", "China Southern"), ("QTR", "Qatar Airways"), ("OMA", "Oman Air"),
    ("RNA", "Nepal Airlines"), ("ALK", "SriLankan Airlines"), ("DQA", "Maldivian"),
]


def guess_airline(callsign: str) -> str:
    cs = (callsign or "").strip().upper()
    for prefix, name in CALLSIGN_AIRLINE:
        if cs.startswith(prefix):
            return name
    return f"{cs[:3]} (unmapped)" if cs else "Unidentified operator"


def get_token() -> str | None:
    client_id = os.environ.get("OPENSKY_CLIENT_ID")
    client_secret = os.environ.get("OPENSKY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("No OpenSky credentials set - using anonymous access (reduced rate limits).")
        return None
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_departures(token: str | None) -> list[dict]:
    end = int(time.time())
    begin = end - LOOKBACK_HOURS * 3600
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = requests.get(
        API_URL,
        params={"airport": AIRPORT_ICAO, "begin": begin, "end": end},
        headers=headers,
        timeout=30,
    )
    if resp.status_code == 404:
        return []  # no flights found for this window
    resp.raise_for_status()
    return resp.json()


def main():
    try:
        token = get_token()
        raw = fetch_departures(token)
    except requests.HTTPError as e:
        print(f"OpenSky request failed: {e}", file=sys.stderr)
        raw = []
    except Exception as e:
        print(f"Unexpected error fetching OpenSky data: {e}", file=sys.stderr)
        raw = []

    flights = []
    for f in raw:
        callsign = (f.get("callsign") or "").strip()
        if not callsign:
            continue
        dest_icao = f.get("estArrivalAirport")
        route = ROUTE_MAP.get(dest_icao)
        ts = f.get("firstSeen") or f.get("lastSeen") or int(time.time())
        flights.append({
            "flightNo": callsign,
            "airline": guess_airline(callsign),
            "city": route["city"] if route else (dest_icao or "Unidentified destination"),
            "iata": route["iata"] if route else (dest_icao or "-"),
            "kind": route["kind"] if route else "other",
            "timestampUtc": ts,
            "timeIso": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
        })

    flights.sort(key=lambda f: f["timestampUtc"], reverse=True)

    payload = {
        "source": "opensky-network.org",
        "airport": AIRPORT_ICAO,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "lookbackHours": LOOKBACK_HOURS,
        "count": len(flights),
        "flights": flights,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {len(flights)} flights to {OUT_PATH}")


if __name__ == "__main__":
    main()
