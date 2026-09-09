"""
generate_web_data.py — Computes daily top movers and writes data.json
for the webpage to display.

Finds the two most recent dates in the database, compares every fund's
investor count and AUM between them, and outputs the top 10 increases
in each category as a JSON file.

Install: pip install libsql-experimental
Run:     python generate_web_data.py
"""

import os
import json
import libsql_experimental as libsql
import argparse

TURSO_URL    = os.environ["TURSO_DB_URL"]
TURSO_TOKEN  = os.environ["TURSO_DB_TOKEN"]
LOCAL_SHADOW = "web_data_local.db"

parser = argparse.ArgumentParser()
parser.add_argument("--output", default="data.json", help="Path to write the JSON output")
args = parser.parse_args()
OUTPUT_FILE = args.output


def fresh_connection():
    con = libsql.connect(LOCAL_SHADOW, sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
    con.sync()
    return con


con = fresh_connection()

# Find the two most recent dates with data
dates = con.execute("SELECT DISTINCT date FROM prices ORDER BY date DESC LIMIT 2").fetchall()
if len(dates) < 2:
    raise RuntimeError("Not enough data to compare two days")

today_date, yesterday_date = dates[0][0], dates[1][0]
print(f"Comparing {yesterday_date} → {today_date}")

# Pull both days' data in one go
rows = con.execute("""
    SELECT code, title, date, investors, aum
    FROM prices
    WHERE date IN (?, ?)
""", (today_date, yesterday_date)).fetchall()
con.close()

# Organize by fund code
by_code = {}
for code, title, date, investors, aum in rows:
    by_code.setdefault(code, {})[date] = {
        "title": title, "investors": investors, "aum": aum
    }

# Compute changes
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
    aum_change = (today["aum"] or 0) - (yest["aum"] or 0)

    investor_changes.append({
        "code": code, "title": today["title"],
        "investors_now": today["investors"], "change": inv_change
    })
    aum_changes.append({
        "code": code, "title": today["title"],
        "aum_now_M": round((today["aum"] or 0) / 1e6, 1),
        "change_M": round(aum_change / 1e6, 1)
    })

top_investors = sorted(investor_changes, key=lambda x: x["change"], reverse=True)[:10]
top_aum = sorted(aum_changes, key=lambda x: x["change_M"], reverse=True)[:10]

output = {
    "date": today_date,
    "compared_to": yesterday_date,
    "top_investor_increases": top_investors,
    "top_aum_increases": top_aum,
}

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"Wrote {OUTPUT_FILE}")
print(json.dumps(output, indent=2, ensure_ascii=False)[:1000])