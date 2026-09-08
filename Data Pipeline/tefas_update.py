"""
tefas_update.py — TEFAS fund price data updater (Turso cloud edition)

Keeps the `prices` table in your Turso cloud database current for all
TEFAS mutual funds: date, price (TRY), shares outstanding, investor
count, and AUM.

Behavior:
  - Empty database  → fetches full 5-year history (in 28-day API chunks)
  - Existing data    → fetches only from the last saved date to today
  - Already current  → prints "up to date" and exits, no duplicate rows

Connects to Turso via TURSO_DB_URL and TURSO_DB_TOKEN environment
variables — never hardcode these, and never commit them to git.

Data source: TEFAS public endpoint `fonGnlBlgSiraliGetir`.

Install: pip install requests libsql-experimental
Run:     python tefas_update.py
"""

import os
import time
import libsql_experimental as libsql
import requests
from datetime import date, datetime, timedelta

TURSO_URL   = os.environ["TURSO_DB_URL"]
TURSO_TOKEN = os.environ["TURSO_DB_TOKEN"]
LOCAL_SHADOW = "tefas_local.db"

YEARS       = 5
CHUNK_DAYS  = 28
MAX_RETRIES = 8
PAUSE       = 11
URL         = "https://www.tefas.gov.tr/api/funds/fonGnlBlgSiraliGetir"


def get_connection():
    con = libsql.connect(LOCAL_SHADOW, sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
    con.sync()
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
    con.sync()
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


def save(records):
    """Opens a fresh connection for each save — avoids the libSQL
    'stream not found' error that happens when reusing a connection
    across long-running operations."""
    con = libsql.connect(LOCAL_SHADOW, sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
    con.sync()

    rows = [
        (r["fonKodu"], r["tarih"], r["fonUnvan"], r["fiyat"],
         r.get("tedPaySayisi"), r.get("kisiSayisi"), r.get("portfoyBuyukluk"))
        for r in records
    ]
    for row in rows:
        con.execute("""
            INSERT OR IGNORE INTO prices (code, date, title, price, shares, investors, aum)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, row)
    con.commit()
    con.sync()
    con.close()
    return len(rows)


def fetch_range(con, start, end):
    total = 0
    cs = start
    while cs <= end:
        ce = min(cs + timedelta(days=CHUNK_DAYS), end)
        records, ok = fetch_chunk(cs.strftime("%Y%m%d"), ce.strftime("%Y%m%d"))
        if ok:
            n = save(records)
            total += n
            print(f"  {cs} → {ce}: {n} rows")
        else:
            print(f"  {cs} → {ce}: FAILED, run again to retry")
        cs = ce + timedelta(days=1)
        time.sleep(PAUSE)
    return total


# ── Main ──────────────────────────────────────────────────────────────────────

con   = get_connection()
con.sync()   # force a fresh pull from cloud right before reading
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
        check_con = libsql.connect(LOCAL_SHADOW, sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
        check_con.sync()
        newest = check_con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        check_con.close()
        print(f"prices: {total} rows added, latest now {newest}")