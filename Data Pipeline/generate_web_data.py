"""
generate_web_data.py — Computes daily top movers and writes data.json
for the webpage to display (Turso remote-connection edition).

Uses a REMOTE connection (the `libsql` package, database=<url>) — no
local shadow file, no sync_url, no .sync(). One connection is opened
once and reused for the whole script run. See tefas_update.py's
docstring for why this replaced the old embedded-replica pattern.

Finds the two most recent dates in the database, compares every fund's
investor count and AUM between them, and outputs:
  - top_aum_increases: sorted by ABSOLUTE TL change (real money moved),
    each item also carries change_pct (percentage change relative to
    its own prior-day AUM) so the webpage can size a bar by intensity
    while keeping the list order tied to actual money flow.
  - top_investor_increases: sorted by absolute investor count change.

Excludes Serbest (unrestricted) and Özel (private) funds — these can't
be bought by a regular retail investor, so they shouldn't occupy a
leaderboard slot regardless of how big their move is.

Install: pip install libsql
Run:     python generate_web_data.py [--output path/to/data.json]
"""

import os
import json
import argparse
import libsql

TURSO_URL   = os.environ["TURSO_DB_URL"]
TURSO_TOKEN = os.environ["TURSO_DB_TOKEN"]

parser = argparse.ArgumentParser()
parser.add_argument("--output", default="data.json", help="Path to write the JSON output")
args = parser.parse_args()
OUTPUT_FILE = args.output

# Fund types that can't be bought by a regular retail investor
EXCLUDE_TERMS = ["SERBEST", "ÖZEL"]


con = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)

dates = con.execute("SELECT DISTINCT date FROM prices ORDER BY date DESC LIMIT 2").fetchall()
if len(dates) < 2:
    raise RuntimeError("Not enough data to compare two days")

today_date, yesterday_date = dates[0][0], dates[1][0]
print(f"Comparing {yesterday_date} → {today_date}")

rows = con.execute("""
    SELECT code, title, date, investors, aum
    FROM prices
    WHERE date IN (?, ?)
""", (today_date, yesterday_date)).fetchall()
con.close()

by_code = {}
for code, title, date, investors, aum in rows:
    if any(term in title.upper() for term in EXCLUDE_TERMS):
        continue
    by_code.setdefault(code, {})[date] = {
        "title": title, "investors": investors, "aum": aum
    }

investor_changes = []
aum_changes = []

for code, days in by_code.items():
    if today_date not in days or yesterday_date not in days:
        continue
    today = days[today_date]
    yest = days[yesterday_date]
    if today["investors"] is None or yest["investors"] is None:
        continue

    inv_change = today["investors"] - yest["investors"]
    today_aum = today["aum"] or 0
    yest_aum = yest["aum"] or 0
    aum_change = today_aum - yest_aum
    aum_change_pct = (aum_change / yest_aum * 100) if yest_aum > 0 else 0

    investor_changes.append({
        "code": code, "title": today["title"],
        "investors_now": today["investors"], "change": inv_change
    })
    aum_changes.append({
        "code": code, "title": today["title"],
        "aum_now_M": round(today_aum / 1e6, 1),
        "change_M": round(aum_change / 1e6, 1),
        "change_pct": round(aum_change_pct, 1),
        "investors_now": today["investors"],
    })

top_aum = sorted(aum_changes, key=lambda x: x["change_M"], reverse=True)[:10]
top_investors = sorted(investor_changes, key=lambda x: x["change"], reverse=True)[:10]

output = {
    "date": today_date,
    "compared_to": yesterday_date,
    "top_aum_increases": top_aum,
    "top_investor_increases": top_investors,
}

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"Wrote {OUTPUT_FILE}")