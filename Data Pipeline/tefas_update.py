"""
tefas_update.py — TEFAS fund price data updater (Turso remote-connection edition)

Keeps the `prices` table in your Turso cloud database current for all
TEFAS mutual funds: date, price (TRY), shares outstanding, investor
count, AUM, and — as of this version — price_eur / price_usd computed
at write time.

Uses a REMOTE connection (the `libsql` package, database=<url>) — no
local shadow file, no sync_url, no .sync(). See earlier version's
docstring history for why (embedded-replica mode silently blew
through Turso's free quota on GitHub Actions' ephemeral machines).

EUR/USD CONVERSION AT WRITE TIME
Every new row gets price_eur and price_usd computed immediately,
using the `fx` table's rate for that date (or the most recent prior
date if that exact date is missing — the same forward-fill logic used
throughout this project to patch ECB holiday gaps). This means
fx_update.py MUST run before this script in the daily workflow, so
today's FX rate already exists when today's fund prices are written.

Behavior:
  - Empty database  → fetches full 5-year history (in 28-day API chunks)
  - Existing data    → fetches only from the last saved date to today
  - Already current  → prints "up to date" and exits, no duplicate rows

Install: pip install requests libsql
Run:     python tefas_update.py
"""

import os
import time
import bisect
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
            price_eur  REAL,
            price_usd  REAL,
            PRIMARY KEY (code, date)
        )
    """)
    con.commit()
    return con


def load_fx(con):
    """Load the fx table into a sorted list of dates + a lookup dict,
    so we can forward-fill: for any date, find the most recent fx
    date <= that date."""
    rows = con.execute("SELECT date, eur_try, usd_try FROM fx ORDER BY date").fetchall()
    dates_sorted = [r[0] for r in rows]
    lookup = {r[0]: (r[1], r[2]) for r in rows}
    return dates_sorted, lookup


def get_fx_rate(target_date, fx_dates_sorted, fx_lookup):
    """Find the fx rate for target_date, or the most recent prior date
    if that exact date is missing (forward-fill, e.g. ECB holidays)."""
    i = bisect.bisect_right(fx_dates_sorted, target_date)
    if i == 0:
        return (None, None)  # no fx data exists before this date at all
    nearest_date = fx_dates_sorted[i - 1]
    return fx_lookup[nearest_date]


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


def save(con, records, fx_dates_sorted, fx_lookup):
    """Writes using the SAME connection passed in, computing price_eur/
    price_usd for each record before insert. Batched in one transaction."""
    if not records:
        return 0

    con.execute("BEGIN")
    for r in records:
        price = r["fiyat"]
        rec_date = r["tarih"]
        eur_try, usd_try = get_fx_rate(rec_date, fx_dates_sorted, fx_lookup)

        price_eur = round(price / eur_try, 6) if (eur_try and price) else None
        price_usd = round(price / usd_try, 6) if (usd_try and price) else None

        con.execute("""
            INSERT INTO prices (code, date, title, price, shares, investors, aum, price_eur, price_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code, date) DO NOTHING
        """, (r["fonKodu"], rec_date, r["fonUnvan"], price,
              r.get("tedPaySayisi"), r.get("kisiSayisi"), r.get("portfoyBuyukluk"),
              price_eur, price_usd))
    con.commit()
    return len(records)


def fetch_range(con, start, end, fx_dates_sorted, fx_lookup):
    total = 0
    cs = start
    while cs <= end:
        ce = min(cs + timedelta(days=CHUNK_DAYS), end)
        records, ok = fetch_chunk(cs.strftime("%Y%m%d"), ce.strftime("%Y%m%d"))
        if ok:
            n = save(con, records, fx_dates_sorted, fx_lookup)
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

fx_dates_sorted, fx_lookup = load_fx(con)
print(f"Loaded {len(fx_dates_sorted)} fx dates for lookup")

last = con.execute("SELECT MAX(date) FROM prices").fetchone()
last = last[0] if last else None

if last is None:
    start = today - timedelta(days=YEARS * 365)
    print(f"prices: empty table — fetching full history {start} → {today}")
    total = fetch_range(con, start, today, fx_dates_sorted, fx_lookup)
    print(f"prices: done, {total} rows added")
else:
    last_date   = datetime.strptime(last, "%Y-%m-%d").date()
    fetch_start = last_date + timedelta(days=1)
    if fetch_start > today:
        print(f"prices: up to date (latest {last})")
    else:
        print(f"prices: updating {fetch_start} → {today}")
        total = fetch_range(con, fetch_start, today, fx_dates_sorted, fx_lookup)
        newest = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        print(f"prices: {total} rows added, latest now {newest}")

con.close()
