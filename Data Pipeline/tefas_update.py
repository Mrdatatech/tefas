"""
tefas_update.py — TEFAS fund price data updater (Turso remote-connection edition)

Keeps the `prices` table in your Turso cloud database current for all
TEFAS mutual funds: date, price (TRY), shares outstanding, investor
count, and AUM.

IMPORTANT — connection mode:
This uses a REMOTE connection (the `libsql` package, connecting via
database=<url>) — NOT the embedded-replica mode we used previously.
The earlier version used libsql_experimental with sync_url + a local
shadow file, which on GitHub Actions' fresh, disposable machines meant
downloading the ENTIRE database from scratch on every single run just
to build a local replica. That silently burned through Turso's free
"bytes synced" and "rows read" quotas in days. The remote connection
mode sends each query straight to the cloud over HTTP and only ever
reads/writes the exact rows involved — no local file, no full-database
sync, no quota blowup. It also eliminates the "stream not found" and
stale-shadow-file bugs we hit under the old mode, since there's no
local replica state to go stale.

Behavior:
  - Empty database  → fetches full 5-year history (in 28-day API chunks)
  - Existing data    → fetches only from the last saved date to today
  - Already current  → prints "up to date" and exits, no duplicate rows

Connects to Turso via TURSO_DB_URL and TURSO_DB_TOKEN environment
variables — never hardcode these, and never commit them to git.

Data source: TEFAS public endpoint `fonGnlBlgSiraliGetir`.

Install: pip install requests libsql
Run:     python tefas_update.py
"""

import os
import time
import libsql
import requests
from datetime import date, datetime, timedelta

TURSO_URL   = os.environ["TURSO_DB_URL"]
TURSO_TOKEN = os.environ["TURSO_DB_TOKEN"]

YEARS       = 5
CHUNK_DAYS  = 28
MAX_RETRIES = 8
PAUSE       = 11
URL         = "https://www.tefas.gov.tr/api/funds/fonGnlBlgSiraliGetir"


def get_connection():
    """One remote connection, reused for the whole script run.
    No local file, no sync — every call goes straight to the cloud."""
    con = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
    con.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            code       TEXT,
            date       TEXT,
            title      TEXT,
            price      REAL,
            shares     REAL,
            investors  INTEGER,
            aum        REAL,
            PRIMARY KEY (code, date)
        )
    """)
    con.commit()
    return con


def fetch_chunk(start_str, end_str):
    payload = {
        "fonTipi": "YAT", "fonKodu": None, "aramaMetni": None,
        "fonTurKod": None, "fonGrubu": None, "sfonTurKod": None,
        "fonTurAciklama": None, "kurucuKod": None,
        "basTarih": start_str, "bitTarih": end_str,
        "basSira": 1, "bitSira": 100000, "dil": "TR"
    }
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(URL, json=payload, timeout=60)
            if r.status_code == 200:
                return (r.json().get("resultList") or [], True)
            wait = 10 * (attempt + 1)
            print(f"  HTTP {r.status_code}, wait {wait}s")
            time.sleep(wait)
        except Exception as e:
            wait = 10 * (attempt + 1)
            print(f"  retry {attempt+1}/{MAX_RETRIES} in {wait}s ({type(e).__name__})")
            time.sleep(wait)
    return ([], False)


def save(con, records):
    """Writes using the SAME connection passed in — no new connection,
    no sync, per chunk. Batched in one transaction."""
    if not records:
        return 0

    con.execute("BEGIN")
    for r in records:
        con.execute("""
            INSERT OR IGNORE INTO prices (code, date, title, price, shares, investors, aum)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (r["fonKodu"], r["tarih"], r["fonUnvan"], r["fiyat"],
              r.get("tedPaySayisi"), r.get("kisiSayisi"), r.get("portfoyBuyukluk")))
    con.commit()
    return len(records)


def fetch_range(con, start, end):
    total = 0
    cs = start
    while cs <= end:
        ce = min(cs + timedelta(days=CHUNK_DAYS), end)
        records, ok = fetch_chunk(cs.strftime("%Y%m%d"), ce.strftime("%Y%m%d"))
        if ok:
            n = save(con, records)
            total += n
            print(f"  {cs} → {ce}: {n} rows")
        else:
            print(f"  {cs} → {ce}: FAILED, run again to retry")
        cs = ce + timedelta(days=1)
        time.sleep(PAUSE)
    return total


# ── Main ──────────────────────────────────────────────────────────────────────

con   = get_connection()
today = date.today()

last = con.execute("SELECT MAX(date) FROM prices").fetchone()
last = last[0] if last else None

if last is None:
    start = today - timedelta(days=YEARS * 365)
    print(f"prices: empty table — fetching full history {start} → {today}")
    total = fetch_range(con, start, today)
    print(f"prices: done, {total} rows added")
else:
    last_date   = datetime.strptime(last, "%Y-%m-%d").date()
    fetch_start = last_date + timedelta(days=1)
    if fetch_start > today:
        print(f"prices: up to date (latest {last})")
    else:
        print(f"prices: updating {fetch_start} → {today}")
        total = fetch_range(con, fetch_start, today)
        newest = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        print(f"prices: {total} rows added, latest now {newest}")

con.close()