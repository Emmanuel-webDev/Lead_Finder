# LeadFinder · Local Business Lead Scraper & Outreach Dashboard

A lightweight, autonomous lead discovery engine for freelance web designers and digital agencies. It continuously scans OpenStreetMap (via Overpass API) across US and Canadian cities to find local businesses with no website or an outdated website, captures their contact info (phone and email), and presents them in a utilitarian outreach dashboard.

Built using **Python's standard library only** — zero third-party packages or paid dependencies.

---

## Features

- **Automated Scanning Loop**: Cycles through target cities every 5 minutes scanning craft shops, restaurants, cafes, clinics, boutiques, repair shops, and professional services.
- **Overpass Failover Pool**: Resilient against rate limits (HTTP 429) and timeouts (HTTP 504) with exponential backoff and automatic failover across multiple mirrors:
  - `overpass-api.de`
  - `lz4.overpass-api.de`
  - `z.overpass-api.de`
  - `overpass.kumi.systems`
- **Lightweight Website Audit**: Analyzes existing business websites for:
  - Missing mobile viewport tags (`<meta name="viewport">`)
  - Missing SSL / unencrypted HTTP
  - Stale copyright years (e.g. 3+ years old)
  - Broken or unreachable websites
  - Direct email extraction via `mailto:` links
- **Lead Capping & Pruning**: Automatically caps `leads.json` at a configurable limit (default: 2,000 leads). When pruning, it drops the oldest **Skipped** leads first, keeping active and new leads intact.
- **Cross-Device Status Sync**: Track outreach states (**New**, **Contacted**, **Replied**, **Skipped**). Statuses sync to the server (`status.json`) across all devices while maintaining `localStorage` for offline resilience.
- **Utilitarian Dashboard**: Fast, single-page interface with warm paper aesthetic, lime accents, search, category filters, and one-click pitch template generator with custom name and portfolio links.
- **Protected by HTTP Basic Auth**: Secure your leads list and contact information behind `DASH_PASSWORD`.

---

## Project Structure

```text
Jobber/
├── scraper.py     # Main engine: background scraper loop + HTTP server (standard library)
├── index.html     # Single-page utilitarian outreach dashboard
├── render.yaml    # Render Blueprint configuration
├── .gitignore     # Ignores runtime data (leads.json, status.json, caches)
└── README.md      # Documentation
```

---

## Getting Started Locally

### Prerequisites
- Python 3.8+ installed (no `pip install` required).

### Run the App
```bash
python scraper.py
```

By default, the server listens at **http://localhost:8000**.
- The dashboard is accessible immediately.
- The scraper runs its first cycle upon startup and repeats every 5 minutes.
- When running locally without `DASH_PASSWORD` set, password protection is disabled.

---

## Configuration Options

Configure the scraper via environment variables:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `PORT` | HTTP port to listen on. | `8000` |
| `DASH_PASSWORD` | Password required to access the dashboard and leads API. | *(None — open)* |
| `DATA_DIR` | Directory to store `leads.json` and `status.json`. | App directory (`HERE`) |
| `MAX_LEADS` | Maximum number of leads stored before pruning oldest skipped leads. | `2000` |

---

## API Endpoints

| Endpoint | Method | Auth | Description |
| :--- | :---: | :---: | :--- |
| `/` | `GET` | Yes | Serves `index.html` (the outreach dashboard). |
| `/healthz` | `GET` | **No** | Health check returning `200 ok` (ideal for uptime pingers). |
| `/leads.json` | `GET` | Yes | Returns all captured leads as a JSON array. |
| `/status.json` | `GET` | Yes | Returns the map of `{ lead_id: status }`. |
| `/status` | `POST` | Yes | Updates status for a lead: `{"id": "...", "status": "contacted"}`. |

---

## Deployment to Render

### Option 1: Render Free Tier (With Uptime Monitor)

Render's free tier provides 750 free instance hours per month, but spins down after 15 minutes of inactivity. To run 24/7 without cost:

1. **Push to GitHub**:
   ```bash
   git remote add origin https://github.com/<your-username>/<repo-name>.git
   git push -u origin main
   ```
2. **Deploy via Render Blueprint**:
   - Go to [dashboard.render.com](https://dashboard.render.com/).
   - Click **New +** > **Blueprint** and select your repository.
   - Render detects `render.yaml` (`plan: free`, `DATA_DIR=/tmp/data`).
   - Enter your desired `DASH_PASSWORD` in the environment settings prompt.
   - Click **Apply**.
3. **Set Up a Free Uptime Pinger**:
   - Create a free monitor on [UptimeRobot](https://uptimerobot.com/), [BetterStack](https://betterstack.com/), or [cron-job.org](https://cron-job.org/).
   - URL: `https://<your-service-name>.onrender.com/healthz`
   - Interval: Every **5 minutes**.
   - Because `/healthz` does not require authentication and responds with `200 ok`, it keeps the service awake without hitting the password wall or interrupting scraper cycles.

> **Note on Free Tier Storage**: The filesystem on Render Free is ephemeral. If the service restarts, the background loop immediately starts rebuilding leads every 5 minutes. Outreach statuses remain preserved in your browser's `localStorage` and automatically sync back upon interaction.

---

### Option 2: Render Starter Tier (Persistent Disk)

To keep leads permanently on a mounted persistent disk across redeployments:

1. Update `render.yaml`:
   ```yaml
   services:
     - type: web
       name: leadfinder
       runtime: python
       plan: starter
       buildCommand: echo "no dependencies"
       startCommand: python scraper.py
       healthCheckPath: /healthz
       disk:
         name: leads
         mountPath: /data
         sizeGB: 1
       envVars:
         - key: DATA_DIR
           value: /data
         - key: DASH_PASSWORD
           sync: false
         - key: PYTHON_VERSION
           value: 3.12.4
   ```
2. Push to GitHub and deploy via Render Blueprint.

---

## Compliance & Terms

- Data is sourced from OpenStreetMap via public Overpass API endpoints in accordance with the OpenStreetMap Acceptable Use Policy.
- The scraper implements polite throttling (300-second cycle interval, max 40 additions per run, custom User-Agent, and mirror rotation).
- Does **not** scrape Google Maps or proprietary directories.
