"""
export_kratio.py — Exports the fund consistency ranking (K-Ratio) as
JSON for the website's scrollable table.

Ranks funds by their AVERAGE K-Ratio across COMPLETED years only
(2+ completed years required) — this is the main, trustworthy score.
The current (in-progress) year is shown separately as a "still on
track?" flag, never blended into the ranking itself — this is what
lets the table catch a fund like IIH: strong historical average, but
currently declining, clearly visible rather than averaged away.

Install: pip install libsql
Run:     python export_kratio.py --output ../docs/kratio.json
"""

import os
import json
import argparse
import libsql

TURSO_URL   = os.environ["TURSO_DB_URL"]
TURSO_TOKEN = os.environ["TURSO_DB_TOKEN"]

parser = argparse.ArgumentParser()
parser.add_argument("--output", default="../docs/kratio.json")
args = parser.parse_args()

con = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)

# Main ranking: average K-ratio across completed years, 2+ years required
ranked = con.execute("""
    SELECT code, AVG(k_ratio) as avg_k, COUNT(*) as n_years
    FROM fund_yearly_kratio
    WHERE is_partial_year = 0
    GROUP BY code
    HAVING COUNT(*) >= 2
    ORDER BY avg_k DESC
""").fetchall()

# Get a title per fund code (most recent title on file)
titles = dict(con.execute("""
    SELECT code, title FROM prices
    WHERE title IS NOT NULL
    GROUP BY code
    HAVING date = MAX(date)
""").fetchall())

# Get all completed-year data per fund, for the year-by-year detail
year_data = {}
for row in con.execute("""
    SELECT code, year, k_ratio, annual_return_pct, is_partial_year
    FROM fund_yearly_kratio ORDER BY code, year
""").fetchall():
    code, year, k_ratio, annual_return_pct, is_partial = row
    year_data.setdefault(code, []).append({
        "year": year,
        "k_ratio": round(k_ratio, 2) if k_ratio is not None else None,
        "return_pct": annual_return_pct,
        "is_partial": bool(is_partial),
    })

con.close()

results = []
for code, avg_k, n_years in ranked:
    current = next((y for y in year_data.get(code, []) if y["is_partial"]), None)
    results.append({
        "code": code,
        "title": (titles.get(code) or "")[:60],
        "avg_k_ratio": round(avg_k, 2),
        "completed_years": n_years,
        "current_year": current,
        "years": year_data.get(code, []),
    })

with open(args.output, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"Wrote {args.output} — {len(results)} funds")
