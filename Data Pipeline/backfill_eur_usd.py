"""
backfill_eur_usd.py — One-time backfill: adds price_eur and price_usd
columns to the `prices` table and fills them for all existing rows.

Run ONCE. After this, tefas_update.py computes these columns for new
rows as they're written each day, so this script never needs to run
again (unless the columns are dropped and need rebuilding).

Logic:
  1. Add price_eur / price_usd columns (NULL by default)
  2. Load prices + fx, forward-fill fx onto every date (same proven
     pattern used throughout this project — patches ECB holiday gaps)
  3. Compute price_eur = price / eur_try, price_usd = price / usd_try
     — skipped (left NULL) for rows where price is 0 or missing
     (pre-launch fund rows with no real price yet)
  4. Write updates in batches inside explicit transactions, using ONE
     reused remote connection (no embedded replica, no .sync() —
     see tefas_update.py's docstring for why that matters)

Install: pip install pandas libsql
Run:     python backfill_eur_usd.py
"""

import os
import pandas as pd
import libsql

TURSO_URL   = os.environ["TURSO_DB_URL"]
TURSO_TOKEN = os.environ["TURSO_DB_TOKEN"]
BATCH_SIZE  = 5000

con = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)

# ── Step 1: add columns if they don't already exist ─────────────────────────

existing_cols = [row[1] for row in con.execute("PRAGMA table_info(prices)").fetchall()]
if "price_eur" not in existing_cols:
    con.execute("ALTER TABLE prices ADD COLUMN price_eur REAL")
    print("Added price_eur column")
if "price_usd" not in existing_cols:
    con.execute("ALTER TABLE prices ADD COLUMN price_usd REAL")
    print("Added price_usd column")
con.commit()

# ── Step 2: load prices + fx ─────────────────────────────────────────────────

print("Loading prices...")
price_rows = con.execute("SELECT code, date, price FROM prices").fetchall()
print(f"  {len(price_rows)} rows")

print("Loading fx...")
fx_rows = con.execute("SELECT date, eur_try, usd_try FROM fx").fetchall()
fx = pd.DataFrame(fx_rows, columns=["date", "eur_try", "usd_try"])
print(f"  {len(fx_rows)} rows")

# ── Step 3: forward-fill fx onto every calendar day, compute conversions ────

prices_df = pd.DataFrame(price_rows, columns=["code", "date", "price"])

all_dates = pd.date_range(prices_df["date"].min(), prices_df["date"].max(), freq="D").strftime("%Y-%m-%d")
fx_ff = fx.set_index("date").reindex(all_dates).ffill().reset_index()
fx_ff.columns = ["date", "eur_try", "usd_try"]

merged = prices_df.merge(fx_ff, on="date", how="left")

# Only compute where price is real (not 0/missing) — else leave NULL
valid = merged["price"] > 0
merged["price_eur"] = None
merged["price_usd"] = None
merged.loc[valid, "price_eur"] = (merged.loc[valid, "price"] / merged.loc[valid, "eur_try"]).round(6)
merged.loc[valid, "price_usd"] = (merged.loc[valid, "price"] / merged.loc[valid, "usd_try"]).round(6)

print(f"Rows with real price (will get EUR/USD): {valid.sum()}")
print(f"Rows left NULL (pre-launch/zero price): {(~valid).sum()}")

# ── Step 4: write back in batches ────────────────────────────────────────────

updates = list(zip(
    merged["price_eur"].tolist(),
    merged["price_usd"].tolist(),
    merged["code"].tolist(),
    merged["date"].tolist(),
))

print(f"\nWriting {len(updates)} updates in batches of {BATCH_SIZE}...")
for i in range(0, len(updates), BATCH_SIZE):
    batch = updates[i:i + BATCH_SIZE]
    con.execute("BEGIN")
    for price_eur, price_usd, code, date in batch:
        con.execute(
            "UPDATE prices SET price_eur = ?, price_usd = ? WHERE code = ? AND date = ?",
            (price_eur, price_usd, code, date)
        )
    con.commit()
    print(f"  {min(i + BATCH_SIZE, len(updates))}/{len(updates)} rows updated")

# ── Step 5: verify ───────────────────────────────────────────────────────────

check = con.execute("""
    SELECT COUNT(*), COUNT(price_eur), COUNT(price_usd) FROM prices
""").fetchone()
print(f"\nVerification — total rows: {check[0]}, with price_eur: {check[1]}, with price_usd: {check[2]}")

sample = con.execute("""
    SELECT code, date, price, price_eur, price_usd FROM prices
    WHERE price > 0 ORDER BY date LIMIT 3
""").fetchall()
print("\nSample rows:")
for row in sample:
    print(f"  {row}")

con.close()
print("\nDone!")
