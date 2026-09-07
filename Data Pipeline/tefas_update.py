"""
TEFAS Update — handles both cold start and daily top-up.
  - Empty table  → fetches full 5-year history (28-day chunks)
  - Existing data → fetches only from latest date to today
Prints "up to date" if nothing is needed.

Install: pip install requests
Run:     python tefas_update.py
"""

import time
import sqlite3
import requests
from datetime import date, datetime, timedelta
import os

DB_FILE     = "tefas.db"
YEARS       = 5
CHUNK_DAYS  = 28
MAX_RETRIES = 8
PAUSE       = 11
URL         = "https://www.tefas.gov.tr/api/funds/fonGnlBlgSiraliGetir"


def get_connection():
    con = sqlite3.connect(DB_FILE)
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
    rows = [
        (r["fonKodu"], r["tarih"], r["fonUnvan"], r["fiyat"],
         r.get("tedPaySayisi"), r.get("kisiSayisi"), r.get("portfoyBuyukluk"))
        for r in records
    ]
    con.executemany("""
        INSERT OR IGNORE INTO prices (code, date, title, price, shares, investors, aum)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, rows)
    con.commit()
    return len(rows)


def fetch_range(con, start, end):
    """Fetch [start, end] in 28-day chunks. Returns total rows saved."""
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

last = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]

if last is None:
    # Cold start — full 5-year history
    start = today - timedelta(days=YEARS * 365)
    print(f"prices: empty table — fetching full history {start} → {today}")
    total = fetch_range(con, start, today)
    print(f"prices: done, {total} rows added")
else:
    # Daily top-up
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

