"""
fx_update.py — Exchange rate (FX) data updater (Turso cloud edition, fast)

Only inserts rows that are genuinely new (filtered locally before ever
touching the network), and writes them inside one explicit transaction
instead of one round-trip per row. On a normal day this means sending
0-3 rows instead of the full 5,500+ row ECB history.

Install: pip install requests pandas libsql-experimental
Run:     python fx_update.py
"""

import io
import os
import zipfile
import requests
import pandas as pd
import libsql_experimental as libsql

TURSO_URL    = os.environ["TURSO_DB_URL"]
TURSO_TOKEN  = os.environ["TURSO_DB_TOKEN"]
LOCAL_SHADOW = "fx_local.db"


def fresh_connection():
    con = libsql.connect(LOCAL_SHADOW, sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
    con.sync()
    con.execute("""
        CREATE TABLE IF NOT EXISTS fx (
            date     TEXT PRIMARY KEY,
            eur_try  REAL,
            usd_try  REAL
        )
    """)
    con.commit()
    con.sync()
    return con


# ── Step 1: check what we already have ──────────────────────────────────────

con = fresh_connection()
before = con.execute("SELECT COUNT(*) FROM fx").fetchone()[0]
last_row = con.execute("SELECT MAX(date) FROM fx").fetchone()
last_date = last_row[0] if last_row else None
con.close()

print(f"fx: {before} rows already stored, latest {last_date}")

# ── Step 2: download ECB rates ──────────────────────────────────────────────

print("Downloading ECB exchange rates...")
r = requests.get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip", timeout=30)
z = zipfile.ZipFile(io.BytesIO(r.content))
ecb = pd.read_csv(z.open(z.namelist()[0]))
ecb = ecb[["Date", "TRY", "USD"]].dropna()
ecb["Date"] = pd.to_datetime(ecb["Date"]).dt.strftime("%Y-%m-%d")
ecb["usd_try"] = ecb["TRY"] / ecb["USD"]
ecb = ecb.rename(columns={"Date": "date", "TRY": "eur_try"})

# ── Step 3: filter to ONLY genuinely new rows before touching the network ──

if last_date:
    new_rows = ecb[ecb["date"] > last_date]
else:
    new_rows = ecb  # empty table, need everything

print(f"New rows to add: {len(new_rows)}")

# ── Step 4: write, all in one transaction ───────────────────────────────────

if len(new_rows) > 0:
    con = fresh_connection()
    con.execute("BEGIN")
    for _, row in new_rows.iterrows():
        con.execute(
            "INSERT OR IGNORE INTO fx (date, eur_try, usd_try) VALUES (?, ?, ?)",
            (row["date"], row["eur_try"], row["usd_try"])
        )
    con.commit()
    con.sync()
    con.close()

# ── Step 5: verify ───────────────────────────────────────────────────────────

con = fresh_connection()
after = con.execute("SELECT COUNT(*) FROM fx").fetchone()[0]
last_after = con.execute("SELECT MAX(date) FROM fx").fetchone()[0]
con.close()

added = after - before
if added == 0:
    print(f"fx: up to date (latest {last_date})")
else:
    print(f"fx: {added} rows added, latest now {last_after}")