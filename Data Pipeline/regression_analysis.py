"""
regression_analysis.py — Computes the Kestner K-Ratio per fund, per
calendar year, to find funds that grew EUR-consistently (not just
profitably, but SMOOTHLY and reliably).

WHAT IS THE K-RATIO
A standard, established statistic (Kestner, 1996, revised 2003) that
combines "how much did it grow" with "how reliably did it grow" into
one number. It's calculated from monthly EUR prices:
  1. Compute each month's return, take log(1 + return), cumulative-sum
     these to build a smooth "log equity curve"
  2. Fit a straight line (regression) through that curve over time
  3. K = slope / (standard_error_of_slope * sqrt(number_of_months))
A high positive K-Ratio = steady, dependable growth. A low or negative
one = flat, declining, or erratic (even if it ended up profitable).

YEAR RULES (see project notes for the reasoning)
  - Completed years (before the current year): a fund is only scored
    for a year if it existed for the ENTIRE year (Jan-Dec) — this
    keeps every fund's yearly comparison equal-length and fair.
  - Current year: scored if it has at least MIN_MONTHS_CURRENT_YEAR
    months of data so far, and flagged is_partial_year = 1 so the
    website can label it "in progress" rather than a final verdict.

Results are stored in a new `fund_yearly_kratio` table — computed
periodically (not on every page load), read cheaply by the website.

Install: pip install libsql
Run:     python regression_analysis.py
"""

import os
import math
from datetime import date
from collections import defaultdict
import libsql

TURSO_URL   = os.environ["TURSO_DB_URL"]
TURSO_TOKEN = os.environ["TURSO_DB_TOKEN"]

MIN_MONTHS_CURRENT_YEAR = 3   # need at least this many months to score the in-progress year


def get_connection():
    con = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
    con.execute("""
        CREATE TABLE IF NOT EXISTS fund_yearly_kratio (
            code             TEXT,
            year             INTEGER,
            k_ratio          REAL,
            annual_return_pct REAL,
            months_used      INTEGER,
            is_partial_year  INTEGER,
            PRIMARY KEY (code, year)
        )
    """)
    con.commit()
    return con


def month_end_prices(con):
    """Pull one price_eur per fund per month — the LAST trading day
    TEFAS has data for in that month. Scoped to only what's needed:
    code, date, price_eur — not the whole prices table. Excludes
    Serbest (unrestricted) and Özel (private) funds, which can't be
    bought by a regular retail investor."""
    rows = con.execute("""
        SELECT code, date, price_eur
        FROM prices
        WHERE price_eur IS NOT NULL
          AND UPPER(title) NOT LIKE '%SERBEST%'
          AND UPPER(title) NOT LIKE '%ÖZEL%'
        ORDER BY code, date
    """).fetchall()

    # Keep only the last row seen per (code, year-month)
    last_per_month = {}
    for code, d, price_eur in rows:
        year_month = d[:7]  # "YYYY-MM"
        last_per_month[(code, year_month)] = (d, price_eur)

    by_fund = defaultdict(list)
    for (code, year_month), (d, price_eur) in last_per_month.items():
        by_fund[code].append((year_month, price_eur))

    for code in by_fund:
        by_fund[code].sort(key=lambda x: x[0])

    return by_fund


def compute_kratio(monthly_prices):
    """monthly_prices: list of (year_month, price_eur), sorted, all in
    ONE calendar year, already validated to have enough months.
    Returns (k_ratio, annual_return_pct) or None if not computable."""
    n = len(monthly_prices)
    if n < 2:
        return None

    # Monthly returns -> log(1+return) -> cumulative sum (the "equity curve")
    log_returns = []
    for i in range(1, n):
        prev_price = monthly_prices[i - 1][1]
        curr_price = monthly_prices[i][1]
        if prev_price <= 0 or curr_price <= 0:
            return None
        ret = (curr_price / prev_price) - 1
        log_returns.append(math.log(1 + ret))

    curve = []
    running = 0.0
    for lr in log_returns:
        running += lr
        curve.append(running)

    m = len(curve)  # number of return periods
    if m < 2:
        return None

    # OLS regression of curve against time index (1..m)
    t = list(range(1, m + 1))
    t_mean = sum(t) / m
    c_mean = sum(curve) / m

    num = sum((t[i] - t_mean) * (curve[i] - c_mean) for i in range(m))
    den = sum((t[i] - t_mean) ** 2 for i in range(m))
    if den == 0:
        return None
    slope = num / den
    intercept = c_mean - slope * t_mean

    # Standard error of the slope
    residuals = [curve[i] - (intercept + slope * t[i]) for i in range(m)]
    if m <= 2:
        return None
    residual_ss = sum(r ** 2 for r in residuals)
    residual_std_err = math.sqrt(residual_ss / (m - 2))
    se_slope = residual_std_err / math.sqrt(den) if den > 0 else None
    if not se_slope or se_slope == 0:
        return None

    k_ratio = slope / (se_slope * math.sqrt(m))

    # Annualized return, for display: total growth over the months, annualized
    first_price = monthly_prices[0][1]
    last_price = monthly_prices[-1][1]
    years_span = n / 12
    annual_return_pct = ((last_price / first_price) ** (1 / years_span) - 1) * 100 if years_span > 0 else None

    return round(k_ratio, 3), round(annual_return_pct, 1) if annual_return_pct is not None else None


# ── Main ──────────────────────────────────────────────────────────────────────

con = get_connection()
current_year = date.today().year

print("Loading month-end EUR prices...")
by_fund = month_end_prices(con)
print(f"  {len(by_fund)} funds with EUR price history")

results = []
for code, monthly in by_fund.items():
    by_year = defaultdict(list)
    for year_month, price_eur in monthly:
        year = int(year_month[:4])
        by_year[year].append((year_month, price_eur))

    for year, months_in_year in by_year.items():
        is_partial = 1 if year == current_year else 0

        if is_partial:
            if len(months_in_year) < MIN_MONTHS_CURRENT_YEAR:
                continue
        else:
            # Completed year: require it to look like a full year (~11-12 months)
            if len(months_in_year) < 11:
                continue

        outcome = compute_kratio(months_in_year)
        if outcome is None:
            continue
        k_ratio, annual_return_pct = outcome

        results.append((code, year, k_ratio, annual_return_pct, len(months_in_year), is_partial))

print(f"\nComputed {len(results)} fund-year scores")

print("Writing to fund_yearly_kratio...")
con.execute("BEGIN")
for row in results:
    con.execute("""
        INSERT INTO fund_yearly_kratio (code, year, k_ratio, annual_return_pct, months_used, is_partial_year)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(code, year) DO UPDATE SET
            k_ratio = excluded.k_ratio,
            annual_return_pct = excluded.annual_return_pct,
            months_used = excluded.months_used,
            is_partial_year = excluded.is_partial_year
    """, row)
con.commit()

con.close()
print("Done!")
