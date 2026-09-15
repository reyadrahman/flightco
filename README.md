# DAC Flight Terminal — live, auto-updating

A static site that shows real flights out of Dhaka (VGHS/DAC) and real fare
quotes, refreshed automatically every 12 hours by a free GitHub Actions job.
It's designed to run **outside** Claude.ai on purpose — Claude.ai's artifact
sandbox blocks outbound network calls entirely, so there's no way to make a
truly live-updating board run inside a chat artifact. This does it for real.

## What updates, and how

| Piece | Source | Update cadence | What it needs |
|---|---|---|---|
| `data/flights.json` | OpenSky Network (real ADS-B departures) | every 12h, via Actions | free account, OAuth2 client |
| `data/fares.json` | Amadeus Self-Service Flight Offers Search | every 12h, via Actions | free developer account |
| `index.html` | reads the two JSON files above | live in the browser | nothing — just hosting |

## International destinations covered

Beyond the original six (Dubai, Bangkok, Singapore, Kuala Lumpur, London,
New York), the route list now also covers the destinations that actually
account for most Bangladeshi outbound travel over the last 12 months:

| Destination | Why it's included |
|---|---|
| Jeddah (JED), Saudi Arabia | DAC's single largest international market — labor migration + Umrah/Hajj travel |
| Kolkata (CCU), India | Highest-frequency neighboring route; heavily used for medical tourism |
| Guangzhou (CAN), China | Fast-growing shopping/multi-city tour destination |
| Doha (DOH), Qatar | Major Gulf labor-migration corridor |
| Muscat (MCT), Oman | Major Gulf labor-migration corridor |
| Kathmandu (KTM), Nepal | Visa-free, popular nearby leisure destination |
| Colombo (CMB), Sri Lanka | eTA access, popular nearby leisure destination |
| Malé (MLE), Maldives | Popular leisure destination |
| Kuala Lumpur (KUL), Malaysia | Fastest-growing destination (185k+ visitors in the first 8 months of 2025 alone), driven by medical tourism and shopping |

That's 14 international + 7 domestic = 21 tracked routes in total.

## 1. Get free API credentials

**OpenSky Network** (flight activity)
1. Sign up at https://opensky-network.org/
2. Go to your Account page → create a new API client → note the `client_id` and `client_secret`.
   (Anonymous access still works with no credentials, just at a much lower rate limit —
   the script falls back to that automatically if the secrets aren't set.)

**Amadeus for Developers** (fares)
1. Sign up at https://developers.amadeus.com/
2. Create a new app under "My Self-Service Workspace" → note the API Key and API Secret.
3. Free tier quota is limited per month — at every 12h across all 21 routes
   (~1,260 calls/month) you should be comfortably inside most free-tier
   allowances, but double check current limits on your Amadeus dashboard.
   If you hit 429s, trim the `ROUTES` list in `fetch_fares.py` or lengthen
   the cron schedule further (e.g. once daily).

## 2. Create the repo and push these files

```bash
git init
git add .
git commit -m "Initial commit: DAC flight terminal"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

## 3. Add your API credentials as repo secrets

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**,
add each of:

- `OPENSKY_CLIENT_ID`
- `OPENSKY_CLIENT_SECRET`
- `AMADEUS_API_KEY`
- `AMADEUS_API_SECRET`

## 4. Turn on GitHub Pages

**Settings → Pages → Source: Deploy from a branch → Branch: `main` / root.**
Your site will be live at `https://<your-username>.github.io/<your-repo>/`.

## 5. Turn on the schedule

The workflow at `.github/workflows/update-data.yml` is already set to run every
12 hours, at 00:00 and 12:00 UTC (`cron: "0 */12 * * *"`). GitHub enables scheduled workflows automatically
once the file is on the default branch — no extra step needed. You can also
trigger it immediately: **Actions tab → Update flight data → Run workflow**.

Each run fetches fresh data, commits `data/flights.json` and `data/fares.json`
back to the repo, and GitHub Pages redeploys automatically. The page itself
also re-checks those files every 5 minutes in the browser, so anyone with the
tab open sees new data without reloading.

## Local testing (optional)

```bash
pip install -r requirements.txt
export OPENSKY_CLIENT_ID=...        # optional, or leave unset for anonymous
export OPENSKY_CLIENT_SECRET=...
export AMADEUS_API_KEY=...
export AMADEUS_API_SECRET=...
python fetch_flights.py
python fetch_fares.py
python -m http.server 8000          # then open http://localhost:8000
```

## Notes & honest limits

- **OpenSky** only sees ADS-B transponder traffic — real callsigns and
  destinations, but no gate, no delay reason, no fare.
- **Amadeus** returns real bookable-style offers for a date ~2 weeks out
  (configurable in `fetch_fares.py`), not this exact minute's live price —
  airline fares change with search date and booking class, so "the" price
  doesn't really exist; the median across returned offers is a reasonable
  proxy, matching what the original request asked for.
- If a route has no scheduled service on the search date, Amadeus returns
  zero offers and the card will show `—`. That's expected for thin routes.
- Domestic routes (Cox's Bazar, Chattogram, etc.) may return fewer/no
  Amadeus offers if those airlines aren't in Amadeus's GDS content — in that
  case you'd see `offersSeen: 0`. Biman, Emirates, Singapore Airlines and
  most major international carriers are well covered.
