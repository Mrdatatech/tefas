"""
check_backfill_progress.py — Quick diagnostic: how far did the EUR/USD
backfill actually get? Connects directly to Turso and reports counts.

Install: pip install libsql
Run:     python check_backfill_progress.py
"""

import os
import libsql

TURSO_URL   = os.environ["TURSO_DB_URL"]
TURSO_TOKEN = os.environ["TURSO_DB_TOKEN"]

con = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)

total = con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
with_eur = con.execute("SELECT COUNT(*) FROM prices WHERE price_eur IS NOT NULL").fetchone()[0]
with_price = con.execute("SELECT COUNT(*) FROM prices WHERE price > 0").fetchone()[0]

print(f"Total rows in prices table: {total}")
print(f"Rows with a real price (>0): {with_price}")
print(f"Rows with price_eur already filled: {with_eur}")
print(f"Rows still needing conversion: {with_price - with_eur}")

last_converted = con.execute("""
    SELECT MAX(date) FROM prices WHERE price_eur IS NOT NULL
""").fetchone()[0]
print(f"\nMost recent date with price_eur filled: {last_converted}")

first_missing = con.execute("""
    SELECT MIN(date) FROM prices WHERE price_eur IS NULL AND price > 0
""").fetchone()[0]
print(f"Earliest date still missing price_eur: {first_missing}")

con.close()
