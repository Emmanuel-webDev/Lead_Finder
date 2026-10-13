#!/usr/bin/env python3
"""Lead scraper for local businesses in the US and Canada.

Source: OpenStreetMap via the Overpass API (free, no key, allowed for this use).
Every 5 minutes it scans one city, adds new businesses to leads.json, and serves
the dashboard at http://localhost:8000. Standard library only.

Run:  python3 scraper.py  (opens on http://localhost:8000)
"""
import http.server, json, os, re, threading, time, urllib.parse, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", HERE)  # point at a persistent disk when deployed
os.makedirs(DATA_DIR, exist_ok=True)
OUT = os.path.join(DATA_DIR, "leads.json")
STATUS_FILE = os.path.join(DATA_DIR, "status.json")
INTERVAL = 300  # seconds
PASSWORD = os.environ.get("DASH_PASSWORD", "")  # set this when deployed; leads include contact details
RADIUS = 12000  # meters around each city centre
UA = "leadfinder/1.0 (personal outreach research)"

# (city, region, country, lat, lon). Add as many as you like.
CITIES = [
    ("Austin", "TX", "US", 30.2672, -97.7431), ("Columbus", "OH", "US", 39.9612, -82.9988),
    ("Tampa", "FL", "US", 27.9506, -82.4572), ("Denver", "CO", "US", 39.7392, -104.9903),
    ("Portland", "OR", "US", 45.5152, -122.6784), ("Atlanta", "GA", "US", 33.7490, -84.3880),
    ("Phoenix", "AZ", "US", 33.4484, -112.0740), ("Charlotte", "NC", "US", 35.2271, -80.8431),
    ("Toronto", "ON", "CA", 43.6532, -79.3832), ("Calgary", "AB", "CA", 51.0447, -114.0719),
    ("Halifax", "NS", "CA", 44.6488, -63.5752), ("Winnipeg", "MB", "CA", 49.8951, -97.1384),
    ("Ottawa", "ON", "CA", 45.4215, -75.6972), ("Vancouver", "BC", "CA", 49.2827, -123.1207),
]
# OSM tags that usually map to small businesses that need a website.
FILTERS = ['["craft"]', '["shop"~"hairdresser|beauty|florist|bakery|butcher|car_repair|clothes|gift|pet|bicycle|tailor"]',
           '["amenity"~"restaurant|cafe|dentist|veterinary|bar"]', '["office"~"lawyer|accountant|estate_agent|insurance"]',
           '["leisure"~"fitness_centre|yoga"]']

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
MAX_LEADS = int(os.environ.get("MAX_LEADS", "2000"))

def http_get(url, data=None, timeout=25, max_bytes=None):
    import gzip
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(max_bytes) if max_bytes else r.read()
        if raw.startswith(b"\x1f\x8b"):
            try: raw = gzip.decompress(raw)
            except Exception: pass
        return raw.decode("utf-8", "replace")

def overpass(lat, lon):
    parts = "".join(f"nwr(around:{RADIUS},{lat},{lon}){f}[name];" for f in FILTERS)
    q = f"[out:json][timeout:60];({parts});out center tags 250;"
    payload = urllib.parse.urlencode({"data": q}).encode()

    last_err = None
    for endpoint in OVERPASS_ENDPOINTS:
        for attempt in range(2):
            try:
                raw_json = http_get(endpoint, data=payload, timeout=75, max_bytes=None)
                data = json.loads(raw_json)
                return data.get("elements", [])
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code in (429, 502, 503, 504):
                    time.sleep(3 * (attempt + 1))
                    continue
                break
            except Exception as e:
                last_err = e
                time.sleep(2 * (attempt + 1))
                continue
    raise RuntimeError(f"All Overpass mirrors failed: {last_err}")

def inspect_site(url):
    """Return (need, reason, email). need is 'old' or 'has'."""
    try:
        html = http_get(url, timeout=6, max_bytes=400_000)
    except Exception:
        return "old", "the site did not load", ""
    reasons = []
    if not re.search(r'<meta[^>]+name=["\']viewport', html, re.I): reasons.append("it is not set up for phones")
    years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)[^0-9]{0,20}(20\d\d)", html, re.I)]
    if years and max(years) <= datetime.now().year - 3: reasons.append(f"the footer still says {max(years)}")
    if url.startswith("http://"): reasons.append("it has no HTTPS")
    m = re.search(r'mailto:([\w.+-]+@[\w-]+\.[\w.-]+)', html)
    return ("old", " and ".join(reasons), m.group(1) if m else "") if reasons else ("has", "", m.group(1) if m else "")

def to_lead(el, city, region, country):
    t = el.get("tags", {})
    name = t.get("name")
    if not name: return None
    site = t.get("website") or t.get("contact:website") or ""
    if site and not site.startswith("http"): site = "http://" + site
    a = t.get("addr:housenumber", "") + " " + t.get("addr:street", "")
    lead = {"id": f"{el['type']}{el['id']}", "name": name, "city": t.get("addr:city", city), "region": region, "country": country,
            "category": (t.get("craft") or t.get("shop") or t.get("amenity") or t.get("office") or t.get("leisure") or "").replace("_", " "),
            "phone": t.get("phone") or t.get("contact:phone") or "", "email": t.get("email") or t.get("contact:email") or "",
            "website": site, "address": a.strip(), "need": "none", "reason": "",
            "found_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": "OpenStreetMap"}
    if site:
        lead["need"], lead["reason"], found = inspect_site(site)
        lead["email"] = lead["email"] or found
    # Keep only businesses you could pitch: no site, or a weak one, and some way to reach them.
    if lead["need"] == "has": return None
    if not (lead["phone"] or lead["email"]): return None
    return lead

def load():
    try:
        with open(OUT, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return []

def load_status():
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return {}

def save_status(data):
    tmp = STATUS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, STATUS_FILE)

def cap_leads(leads, limit=MAX_LEADS):
    if len(leads) <= limit:
        return leads
    excess = len(leads) - limit
    st_map = load_status()
    # Drop oldest 'skip' leads first
    skip_leads = [l for l in leads if st_map.get(l["id"]) == "skip" or l.get("status") == "skip"]
    skip_leads.sort(key=lambda l: l.get("found_at", ""))
    drop_ids = set(l["id"] for l in skip_leads[:excess])
    # If still exceeding cap, drop oldest uncontacted leads before contacted/replied leads
    if len(drop_ids) < excess:
        remaining = [l for l in leads if l["id"] not in drop_ids]
        remaining.sort(key=lambda l: (1 if st_map.get(l["id"]) in ("contacted", "replied") or l.get("status") in ("contacted", "replied") else 0, l.get("found_at", "")))
        for l in remaining:
            if len(drop_ids) >= excess: break
            drop_ids.add(l["id"])
    return [l for l in leads if l["id"] not in drop_ids]

def save_leads(leads):
    leads = cap_leads(leads)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(leads, f, indent=1, ensure_ascii=False)
    os.replace(tmp, OUT)

def cycle(i):
    city, region, country, lat, lon = CITIES[i % len(CITIES)]
    now_str = time.strftime('%H:%M:%S')
    leads = load()
    try:
        els = overpass(lat, lon)
    except Exception as e:
        print(f"[{now_str}] {city}, {region}: failed ({e}), skipped - found 0, added 0, total {len(leads)}", flush=True)
        return

    found = len(els)
    seen = {l["id"] for l in leads}
    added = 0
    for el in els:
        if f"{el['type']}{el['id']}" in seen: continue
        l = to_lead(el, city, region, country)
        if l:
            leads.append(l)
            seen.add(l["id"])
            added += 1
            if added == 1 or added % 3 == 0:
                save_leads(leads)
        if added >= 40: break  # keep each cycle light on target sites

    save_leads(leads)
    print(f"[{now_str}] {city}, {region}: found {found}, added {added}, total {len(leads)}", flush=True)

def serve(port):
    import base64, hmac
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def authed(self):
            if not PASSWORD: return True
            h = self.headers.get("Authorization", "")
            try: pw = base64.b64decode(h.split(" ", 1)[1]).decode().split(":", 1)[1]
            except Exception: return False
            return hmac.compare_digest(pw.encode(), PASSWORD.encode())
        def send(self, code, body, ctype="text/plain", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items(): self.send_header(k, v)
            self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/healthz": return self.send(200, b"ok")
            if not self.authed():
                return self.send(401, b"Password required", extra={"WWW-Authenticate": 'Basic realm="Leads"'})
            if path in ("/", "/index.html"):
                with open(os.path.join(HERE, "index.html"), "rb") as f: return self.send(200, f.read(), "text/html; charset=utf-8")
            if path == "/leads.json":
                try:
                    with open(OUT, "rb") as f: return self.send(200, f.read(), "application/json; charset=utf-8")
                except FileNotFoundError: return self.send(200, b"[]", "application/json; charset=utf-8")
            if path == "/status.json":
                try:
                    with open(STATUS_FILE, "rb") as f: return self.send(200, f.read(), "application/json; charset=utf-8")
                except FileNotFoundError: return self.send(200, b"{}", "application/json; charset=utf-8")
            self.send(404, b"Not found")
        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if not self.authed():
                return self.send(401, b"Password required", extra={"WWW-Authenticate": 'Basic realm="Leads"'})
            if path in ("/status", "/status.json"):
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    st = load_status()
                    if isinstance(body, dict):
                        if "id" in body and "status" in body:
                            st[body["id"]] = body["status"]
                        else:
                            st.update(body)
                    save_status(st)
                    return self.send(200, b'{"ok":true}', "application/json; charset=utf-8")
                except Exception as e:
                    return self.send(400, json.dumps({"error": str(e)}).encode(), "application/json; charset=utf-8")
            self.send(404, b"Not found")
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"Dashboard on port {port}" + (" (password protected)" if PASSWORD else " (NO PASSWORD SET)"), flush=True)

if __name__ == "__main__":
    serve(int(os.environ.get("PORT", "8000")))
    i = 0
    while True:
        try: cycle(i)
        except Exception as e: print("cycle error:", e, flush=True)
        i += 1
        time.sleep(INTERVAL)
