"""
backfill_eur_usd.py — One-time backfill: adds price_eur and price_usd
columns to the `prices` table and fills them for all existing rows.

RESUMABLE: on each run, only processes rows where price_eur IS NULL
and price > 0 (i.e. rows not yet converted). Safe to stop and re-run
at any point — it always picks up exactly where it left off, never
redoing work already done. This matters because the full backfill can
take longer than GitHub Actions' job time limits on a single run.

Logic:
  1. Add price_eur / price_usd columns if they don't exist yet
  2. Find only the rows still needing conversion (price_eur IS NULL,
     price > 0) — skips both already-done rows AND pre-launch
     zero-price rows (which stay NULL forever, by design)
  3. Load fx, forward-fill onto every date (proven pattern)
  4. Compute price_eur / price_usd for the remaining rows only
  5. Write updates in batches inside explicit transactions, one
     reused remote connection (no embedded replica, no .sync())

Install: pip install pandas libsql
Run:     python backfill_eur_usd.py
         (re-run as many times as needed until it reports "Nothing left to do")
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

# ── Step 2: find only the rows still needing conversion ─────────────────────

print("Finding rows still needing conversion...")
remaining_rows = con.execute("""
    SELECT code, date, price FROM prices
    WHERE price_eur IS NULL AND price > 0
""").fetchall()

if not remaining_rows:
    print("Nothing left to do — all rows already converted.")
    con.close()
    exit()

print(f"  {len(remaining_rows)} rows remaining")

# ── Step 3: load fx, forward-fill onto every date ───────────────────────────

print("Loading fx...")
fx_rows = con.execute("SELECT date, eur_try, usd_try FROM fx").fetchall()
fx = pd.DataFrame(fx_rows, columns=["date", "eur_try", "usd_try"])

remaining_df = pd.DataFrame(remaining_rows, columns=["code", "date", "price"])

all_dates = pd.date_range(remaining_df["date"].min(), remaining_df["date"].max(), freq="D").strftime("%Y-%m-%d")
fx_ff = fx.set_index("date").reindex(all_dates).ffill().reset_index()
fx_ff.columns = ["date", "eur_try", "usd_try"]

merged = remaining_df.merge(fx_ff, on="date", how="left")
merged["price_eur"] = (merged["price"] / merged["eur_try"]).round(6)
merged["price_usd"] = (merged["price"] / merged["usd_try"]).round(6)

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
    done = min(i + BATCH_SIZE, len(updates))
    print(f"  {done}/{len(updates)} rows updated")

# ── Step 5: verify ───────────────────────────────────────────────────────────

check = con.execute("""
    SELECT COUNT(*), COUNT(price_eur), COUNT(price_usd) FROM prices
""").fetchone()
print(f"\nTotal rows: {check[0]}, with price_eur: {check[1]}, with price_usd: {check[2]}")

remaining_after = con.execute("""
    SELECT COUNT(*) FROM prices WHERE price_eur IS NULL AND price > 0
""").fetchone()[0]
print(f"Still remaining (will need another run): {remaining_after}")

con.close()
print("\nBatch complete. Re-run this script if rows still remain.")
