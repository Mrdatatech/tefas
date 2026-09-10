"""
fx_update.py — Exchange rate (FX) data updater (Turso remote-connection edition)

Keeps the `fx` table in your Turso cloud database current with daily
EUR/TRY and USD/TRY rates from the European Central Bank.

Uses a REMOTE connection (the `libsql` package, database=<url>) — no
local shadow file, no sync_url, no .sync(). One connection is opened
once and reused for the whole script run; every query goes straight
to Turso over the network and reads/writes only the exact rows
involved. See tefas_update.py's docstring for why this replaced the
old embedded-replica pattern (it was silently re-syncing the entire
database on every run in ephemeral environments like GitHub Actions).

Only genuinely new ECB rows are sent (filtered locally before ever
touching the network), written in one transaction.

Install: pip install requests pandas libsql
Run:     python fx_update.py
"""

import io
import os
import zipfile
import requests
import pandas as pd
import libsql

TURSO_URL   = os.environ["TURSO_DB_URL"]
TURSO_TOKEN = os.environ["TURSO_DB_TOKEN"]


def get_connection():
    con = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
    con.execute("""
        CREATE TABLE IF NOT EXISTS fx (
            date     TEXT PRIMARY KEY,
            eur_try  REAL,
            usd_try  REAL
        )
    """)
    con.commit()
    return con


# ── One connection for the whole run ────────────────────────────────────────

con = get_connection()

before = con.execute("SELECT COUNT(*) FROM fx").fetchone()[0]
last_row = con.execute("SELECT MAX(date) FROM fx").fetchone()
last_date = last_row[0] if last_row else None

print(f"fx: {before} rows already stored, latest {last_date}")

# ── Download ECB rates ───────────────────────────────────────────────────────

print("Downloading ECB exchange rates...")
r = requests.get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip", timeout=30)
z = zipfile.ZipFile(io.BytesIO(r.content))
ecb = pd.read_csv(z.open(z.namelist()[0]))
ecb = ecb[["Date", "TRY", "USD"]].dropna()
ecb["Date"] = pd.to_datetime(ecb["Date"]).dt.strftime("%Y-%m-%d")
ecb["usd_try"] = ecb["TRY"] / ecb["USD"]
ecb = ecb.rename(columns={"Date": "date", "TRY": "eur_try"})

# ── Filter to ONLY genuinely new rows before touching the database ─────────

if last_date:
    new_rows = ecb[ecb["date"] > last_date]
else:
    new_rows = ecb

print(f"New rows to add: {len(new_rows)}")

# ── Write, all in one transaction, same connection ──────────────────────────

if len(new_rows) > 0:
    con.execute("BEGIN")
    for _, row in new_rows.iterrows():
        con.execute(
            "INSERT OR IGNORE INTO fx (date, eur_try, usd_try) VALUES (?, ?, ?)",
            (row["date"], row["eur_try"], row["usd_try"])
        )
    con.commit()

# ── Verify, same connection ──────────────────────────────────────────────────

after = con.execute("SELECT COUNT(*) FROM fx").fetchone()[0]
last_after = con.execute("SELECT MAX(date) FROM fx").fetchone()[0]
con.close()

added = after - before
if added == 0:
    print(f"fx: up to date (latest {last_date})")
else:
    print(f"fx: {added} rows added, latest now {last_after}")