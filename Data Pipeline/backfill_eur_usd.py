"""
backfill_eur_usd.py — One-time backfill: fills price_eur and price_usd
for all existing rows in `prices` (fast, batched version).

RESUMABLE: only processes rows where price_eur IS NULL and price > 0.
Safe to stop and re-run — always picks up exactly where it left off.

SPEED FIX (v2): the original version ran one UPDATE per row — each one
a separate network round-trip to Turso, which at ~400 rows/sec would
have taken over a day for the full 1.7M rows. This version instead:
  1. Computes price_eur/price_usd for a batch of rows locally
  2. Sends the WHOLE batch to Turso in a single multi-row INSERT into
     a temporary table (one round-trip for the whole batch)
  3. Runs one UPDATE...FROM statement to apply that batch to `prices`
     in a single round-trip, joining on (code, date)
  4. Clears the temp table and moves to the next batch
This turns ~5000 round-trips per batch into ~3, which should be
roughly a 500-1000x reduction in network overhead.

Install: pip install pandas libsql
Run:     python backfill_eur_usd.py
         (re-run as many times as needed until it reports "Nothing left to do")
"""

import os
import time
import pandas as pd
import libsql

TURSO_URL   = os.environ["TURSO_DB_URL"]
TURSO_TOKEN = os.environ["TURSO_DB_TOKEN"]
BATCH_SIZE  = 200   # rows per INSERT batch — kept modest to stay under
                    # any per-statement parameter limits (200 rows x 4
                    # params = 800 params per INSERT, safely under typical limits)

con = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)

# ── Step 1: ensure columns and temp table exist ─────────────────────────────

existing_cols = [row[1] for row in con.execute("PRAGMA table_info(prices)").fetchall()]
if "price_eur" not in existing_cols:
    con.execute("ALTER TABLE prices ADD COLUMN price_eur REAL")
if "price_usd" not in existing_cols:
    con.execute("ALTER TABLE prices ADD COLUMN price_usd REAL")
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

# ── Step 4: write back in fast batches using upsert (no temp table needed) ──
# INSERT ... ON CONFLICT DO UPDATE: since every (code, date) already exists
# (these are all pre-existing rows), the INSERT part never actually inserts —
# it always hits the PRIMARY KEY conflict and runs the UPDATE instead, only
# touching price_eur/price_usd, leaving every other column untouched.

rows_to_write = list(zip(
    merged["code"].tolist(),
    merged["date"].tolist(),
    merged["price_eur"].tolist(),
    merged["price_usd"].tolist(),
))

total_batches = (len(rows_to_write) + BATCH_SIZE - 1) // BATCH_SIZE
print(f"\nWriting {len(rows_to_write)} rows in {total_batches} batches of {BATCH_SIZE}...")

start_time = time.time()
for batch_num, i in enumerate(range(0, len(rows_to_write), BATCH_SIZE), 1):
    batch = rows_to_write[i:i + BATCH_SIZE]

    placeholders = ",".join(["(?,?,?,?)"] * len(batch))
    flat_params = [v for row in batch for v in row]

    con.execute(f"""
        INSERT INTO prices (code, date, price_eur, price_usd)
        VALUES {placeholders}
        ON CONFLICT(code, date) DO UPDATE SET
            price_eur = excluded.price_eur,
            price_usd = excluded.price_usd
    """, flat_params)
    con.commit()

    if batch_num % 20 == 0 or batch_num == total_batches:
        done = min(i + BATCH_SIZE, len(rows_to_write))
        elapsed = time.time() - start_time
        rate = done / elapsed if elapsed > 0 else 0
        print(f"  batch {batch_num}/{total_batches} — {done}/{len(rows_to_write)} rows"
              f" ({rate:.0f} rows/sec)")

# ── Step 5: verify ───────────────────────────────────────────────────────────

check = con.execute("SELECT COUNT(*), COUNT(price_eur) FROM prices").fetchone()
print(f"\nTotal rows: {check[0]}, with price_eur: {check[1]}")

remaining_after = con.execute("""
    SELECT COUNT(*) FROM prices WHERE price_eur IS NULL AND price > 0
""").fetchone()[0]
print(f"Still remaining: {remaining_after}")

con.close()
print("\nBatch complete. Re-run this script if rows still remain.")
