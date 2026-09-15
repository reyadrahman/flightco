#!/usr/bin/env python3
"""
Pulls real economy/business fare quotes for DAC -> each tracked destination
from the Amadeus for Developers self-service API (free tier) and writes a
median per route to data/fares.json.

Why Amadeus instead of scraping airline sites: it's a sanctioned, documented
API with a free quota, so it won't break when an airline changes its booking
widget or blocks automated browsers, and it doesn't risk violating a site's
terms of use.

Setup:
  1. Create a free account at https://developers.amadeus.com
  2. Create an app (Self-Service) to get an API key + secret
  3. Set as env vars / GitHub Actions secrets:
       AMADEUS_API_KEY
       AMADEUS_API_SECRET

Free-tier quota note: the self-service test environment typically allows a
limited number of calls per month. Running every 12 hours across all 21
routes is ~42 calls/day (~1,260/month) - comfortably under most free-tier
allowances, but check your current quota on the Amadeus dashboard. If you
add more routes or shorten the schedule and start hitting 429s, either trim
ROUTES or upgrade the Amadeus plan.
"""
import json
import os
import sys
import time
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

TOKEN_URL = "https://test.api.amadeus.com/v1/security/oauth2/token"
SEARCH_URL = "https://test.api.amadeus.com/v2/shopping/flight-offers"
ORIGIN = "DAC"
OUT_PATH = Path(__file__).parent / "data" / "fares.json"

ROUTES = [
    {"city": "Cox's Bazar", "iata": "CXB", "kind": "domestic"},
    {"city": "Chattogram", "iata": "CGP", "kind": "domestic"},
    {"city": "Sylhet", "iata": "ZYL", "kind": "domestic"},
    {"city": "Saidpur", "iata": "SPD", "kind": "domestic"},
    {"city": "Jessore", "iata": "JSR", "kind": "domestic"},
    {"city": "Barishal", "iata": "BZL", "kind": "domestic"},
    {"city": "Rajshahi", "iata": "RJH", "kind": "domestic"},
    {"city": "Dubai", "iata": "DXB", "kind": "intl"},
    {"city": "Bangkok", "iata": "BKK", "kind": "intl"},
    {"city": "Singapore", "iata": "SIN", "kind": "intl"},
    {"city": "Kuala Lumpur", "iata": "KUL", "kind": "intl"},
    {"city": "London", "iata": "LHR", "kind": "intl"},
    {"city": "New York", "iata": "JFK", "kind": "intl"},
    # Added based on last-12-months outbound travel patterns for Bangladeshi
    # travelers (Saudi Arabia = DAC's #1 international market; India = top
    # neighbor route/medical tourism; Malaysia/China = fastest-growing;
    # Qatar/Oman = major labor-migration corridors; Nepal/Sri Lanka/Maldives
    # = most popular nearby leisure destinations).
    {"city": "Jeddah", "iata": "JED", "kind": "intl"},
    {"city": "Kolkata", "iata": "CCU", "kind": "intl"},
    {"city": "Guangzhou", "iata": "CAN", "kind": "intl"},
    {"city": "Doha", "iata": "DOH", "kind": "intl"},
    {"city": "Muscat", "iata": "MCT", "kind": "intl"},
    {"city": "Kathmandu", "iata": "KTM", "kind": "intl"},
    {"city": "Colombo", "iata": "CMB", "kind": "intl"},
    {"city": "Malé", "iata": "MLE", "kind": "intl"},
]

SEARCH_DATE = (datetime.now(timezone.utc) + timedelta(days=14)).strftime("%Y-%m-%d")


def get_token() -> str:
    key = os.environ["AMADEUS_API_KEY"]
    secret = os.environ["AMADEUS_API_SECRET"]
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials", "client_id": key, "client_secret": secret},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def search_fares(token: str, dest_iata: str) -> list[dict]:
    resp = requests.get(
        SEARCH_URL,
        headers={"Authorization": f"Bearer {token}"},
        params={
            "originLocationCode": ORIGIN,
            "destinationLocationCode": dest_iata,
            "departureDate": SEARCH_DATE,
            "adults": 1,
            "currencyCode": "BDT",
            "max": 15,
        },
        timeout=30,
    )
    if resp.status_code == 400:
        return []  # e.g. route not served / no offers
    resp.raise_for_status()
    return resp.json().get("data", [])


def median_fares(offers: list[dict]) -> tuple[float | None, float | None]:
    econ_prices, biz_prices = [], []
    for offer in offers:
        try:
            price = float(offer["price"]["total"])
        except (KeyError, ValueError):
            continue
        cabin = ""
        try:
            cabin = offer["travelerPricings"][0]["fareDetailsBySegment"][0].get("cabin", "")
        except (KeyError, IndexError):
            pass
        if cabin == "BUSINESS":
            biz_prices.append(price)
        else:
            econ_prices.append(price)
    econ = statistics.median(econ_prices) if econ_prices else None
    biz = statistics.median(biz_prices) if biz_prices else None
    return econ, biz


def main():
    try:
        token = get_token()
    except Exception as e:
        print(f"Could not authenticate with Amadeus: {e}", file=sys.stderr)
        print("Set AMADEUS_API_KEY / AMADEUS_API_SECRET as env vars.", file=sys.stderr)
        sys.exit(1)

    results = []
    for route in ROUTES:
        try:
            offers = search_fares(token, route["iata"])
            econ, biz = median_fares(offers)
            results.append({
                **route,
                "medianEconomyBDT": econ,
                "medianBusinessBDT": biz,
                "offersSeen": len(offers),
            })
            print(f"{route['iata']}: {len(offers)} offers, econ~{econ}, biz~{biz}")
        except requests.HTTPError as e:
            print(f"Fare lookup failed for {route['iata']}: {e}", file=sys.stderr)
            results.append({**route, "medianEconomyBDT": None, "medianBusinessBDT": None, "offersSeen": 0})
        time.sleep(0.4)  # be polite to the free-tier rate limit

    payload = {
        "source": "Amadeus Self-Service Flight Offers Search",
        "searchDate": SEARCH_DATE,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "routes": results,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"Wrote fares for {len(results)} routes to {OUT_PATH}")


if __name__ == "__main__":
    main()
