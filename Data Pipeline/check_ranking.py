import os
import libsql

TURSO_URL   = os.environ["TURSO_DB_URL"]
TURSO_TOKEN = os.environ["TURSO_DB_TOKEN"]

con = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)

# Average K-ratio across COMPLETED years only, require at least 2 such years
rows = con.execute("""
    SELECT code, AVG(k_ratio) as avg_k, COUNT(*) as n_years
    FROM fund_yearly_kratio
    WHERE is_partial_year = 0
    GROUP BY code
    HAVING COUNT(*) >= 2
    ORDER BY avg_k DESC
    LIMIT 15
""").fetchall()

print("=== TOP 15 by average K-ratio across completed years (2+ years required) ===")
for code, avg_k, n_years in rows:
    # also fetch current year status for context
    current = con.execute("""
        SELECT k_ratio, annual_return_pct, is_partial_year
        FROM fund_yearly_kratio WHERE code = ? AND is_partial_year = 1
    """, (code,)).fetchone()
    current_str = f"2026 so far: K={current[0]}, {current[1]}%" if current else "2026: no data yet"
    print(f"{code}: avg_K={avg_k:.2f} ({n_years} completed years) | {current_str}")

con.close()
