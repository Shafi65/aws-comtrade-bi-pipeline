"""
Day 0 - UN Comtrade data-coverage verification.

GOAL: Before we build ANY AWS infrastructure, prove the data exists at the
shape we need. This script pulls tiny test slices and reports coverage so we
can decide (a) monthly vs annual frequency and (b) reporter vs mirror data.

Run:  python scripts/verify_coverage.py
Needs a .env file (copied from .env.example) with COMTRADE_API_KEY set.
"""

import os
import sys
import time
from collections import defaultdict

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Part 1 - Load the API key from the git-ignored .env (never hard-coded).
# ---------------------------------------------------------------------------
load_dotenv()
API_KEY = os.getenv("COMTRADE_API_KEY")
if not API_KEY or API_KEY == "your_primary_key_here":
    sys.exit(
        "ERROR: COMTRADE_API_KEY not set.\n"
        "  1) cp .env.example .env\n"
        "  2) paste your Comtrade primary key into .env\n"
        "  3) re-run this script."
    )

# ---------------------------------------------------------------------------
# Config - the small test slice defined by the Day 0 gate.
# ---------------------------------------------------------------------------
BASE_URL = "https://comtradeapi.un.org/data/v1/get"  # /{type}/{freq}/{classification}
BANGLADESH = 50          # reporterCode for Bangladesh
WORLD = 0                # partnerCode 0 = "World" (all partners combined)
YEARS = range(2018, 2025)  # 2018..2024 inclusive

# Mirror partners: big exporters that report their trade WITH Bangladesh.
MIRROR_PARTNERS = {156: "China", 699: "India", 842: "USA"}


def comtrade_get(freq, flow, cmd, reporter, partner, periods):
    """One raw HTTP call to Comtrade v1. Returns the list of data records.

    freq     : 'M' monthly or 'A' annual
    flow     : 'M' imports or 'X' exports
    cmd      : HS commodity code as string, e.g. '52'
    reporter : reporter country code (who is reporting)
    partner  : partner country code (0 = World)
    periods  : list of period strings, e.g. ['201801','201802', ...]
    """
    url = f"{BASE_URL}/C/{freq}/HS"          # C = commodities, HS classification
    params = {
        "reporterCode": reporter,
        "flowCode": flow,
        "cmdCode": cmd,
        "partnerCode": partner,
        "period": ",".join(periods),
    }
    headers = {"Ocp-Apim-Subscription-Key": API_KEY}  # key travels in header, not URL

    # Show the call (minus the secret) so we SEE what the API receives.
    printable = "&".join(f"{k}={v}" for k, v in params.items())
    print(f"    GET {url}?{printable[:90]}...")

    resp = requests.get(url, params=params, headers=headers, timeout=60)
    if resp.status_code == 429:
        print("    rate-limited (429) - waiting 20s and retrying once...")
        time.sleep(20)
        resp = requests.get(url, params=params, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json().get("data", []) or []


def months_of(year):
    """Return the 12 monthly period strings for a year, e.g. '201801'..'201812'."""
    return [f"{year}{m:02d}" for m in range(1, 13)]


def coverage_by_year(records):
    """Given API records, return {year: set(months present)} from the 'period' field."""
    seen = defaultdict(set)
    for r in records:
        period = str(r.get("period", ""))        # e.g. '201803'
        if len(period) == 6:
            seen[period[:4]].add(period[4:])       # year -> {month}
    return seen


def print_coverage_table(title, seen_by_year):
    """Pretty-print months-present-per-year (0..12)."""
    print(f"\n  {title}")
    for year in YEARS:
        got = sorted(seen_by_year.get(str(year), set()))
        bar = "".join("#" if f"{m:02d}" in got else "." for m in range(1, 13))
        print(f"    {year}: [{bar}] {len(got):2d}/12 months")


# ---------------------------------------------------------------------------
# Part 3 - the three checks.
# ---------------------------------------------------------------------------
def check_reporter():
    print("\n=== CHECK A: Bangladesh as REPORTER (monthly) ===")
    print("  Imports of cotton (HS 52):")
    imp = []
    for y in YEARS:
        imp += comtrade_get("M", "M", "52", BANGLADESH, WORLD, months_of(y))
        time.sleep(1)  # be gentle on the free-tier rate limit
    print_coverage_table("BD imports HS52 (monthly):", coverage_by_year(imp))

    print("\n  Exports of knit apparel (HS 61):")
    exp = []
    for y in YEARS:
        exp += comtrade_get("M", "X", "61", BANGLADESH, WORLD, months_of(y))
        time.sleep(1)
    print_coverage_table("BD exports HS61 (monthly):", coverage_by_year(exp))
    return imp, exp


def check_mirror():
    print("\n=== CHECK B: MIRROR view - partners reporting exports TO Bangladesh ===")
    all_mirror = []
    for code, name in MIRROR_PARTNERS.items():
        print(f"\n  {name} ({code}) exporting cotton (HS 52) to Bangladesh:")
        recs = []
        for y in YEARS:
            recs += comtrade_get("M", "X", "52", code, BANGLADESH, months_of(y))
            time.sleep(1)
        print_coverage_table(f"{name} -> BD cotton (monthly):", coverage_by_year(recs))
        all_mirror += recs
    return all_mirror


def check_annual_fallback():
    print("\n=== CHECK C: ANNUAL fallback (is annual more complete than monthly?) ===")
    years = [str(y) for y in YEARS]
    recs = comtrade_get("A", "M", "52", BANGLADESH, WORLD, years)
    present = sorted({str(r.get("period")) for r in recs})
    print(f"  BD annual imports HS52 - years returned: {present}")
    return recs


def main():
    print("UN Comtrade coverage verification (Bangladesh, 2018-2024)")
    print("=" * 60)
    imp, exp = check_reporter()
    mirror = check_mirror()
    annual = check_annual_fallback()

    # ---- Part 4: plain-English verdict for the decision gate ----
    print("\n" + "=" * 60)
    print("VERDICT (for our Day 0 decision gate):")
    print(f"  reporter monthly records: imports={len(imp)}, exports={len(exp)}")
    print(f"  mirror monthly records  : {len(mirror)}")
    print(f"  annual records          : {len(annual)}")
    print("\n  -> If reporter monthly coverage is sparse but annual is complete,")
    print("     we choose ANNUAL. If reporter months are missing but mirror months")
    print("     are present, we lean on MIRROR data and document it as a limitation.")
    print("  Bring these numbers back to the chat - we decide together.")


if __name__ == "__main__":
    main()
