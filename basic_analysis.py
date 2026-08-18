#!/usr/bin/env python3
"""
basic_analysis.py — end-to-end example: fetch APRA data, compute crowding.

Run from the project root:
    python examples/basic_analysis.py
"""

import sys
import logging
from pathlib import Path

# Allow running from the project root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))

from superannuation_holdings import APRAFetcher, APRAParser, crowding_risk, positioning

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main():
    fetcher = APRAFetcher(cache_dir="data/raw/apra")
    parser = APRAParser()

    # Fetch the most recent annual release.
    print("Fetching APRA Annual Fund-Level Superannuation Statistics (2024)...")
    try:
        result = fetcher.fetch("annual_fund_level", year=2024, force_refresh=False)
    except FileNotFoundError as e:
        print(f"\nCould not download: {e}")
        print("Check https://www.apra.gov.au/annual-fund-level-superannuation-statistics")
        print("for the current URL and update apra_fetcher.py accordingly.")
        sys.exit(1)

    print(f"  Source: {result.source_url}")
    print(f"  Size:   {result.file_size_bytes / 1024:.1f} KB")
    print(f"  SHA256: {result.sha256[:16]}...")
    print(f"  Cached: {result.from_cache}")

    # Parse into a normalised DataFrame.
    print("\nParsing...")
    df = parser.parse_annual_fund_level(result.local_path, year=2024)
    print(f"  {len(df)} rows, {df['rse_name'].nunique()} funds, {df['asset_class'].nunique()} asset classes")
    print()
    print(df.head(10).to_string(index=False))

    # Industry positioning trend.
    print("\n--- Industry weighted-average allocation ---")
    trend = positioning.industry_allocation_trend(df)
    print(trend.to_string(index=False))

    # HHI by asset class.
    print("\n--- Concentration (HHI) by asset class ---")
    hhi = crowding_risk.hhi(df)
    print(hhi.to_string(index=False))

    # Crowding scores.
    print("\n--- Fund crowding scores (top 10) ---")
    scores = crowding_risk.crowding_score(df)
    print(scores.head(10).to_string(index=False))

    # ART vs peers.
    print("\n--- ART active tilts vs industry ---")
    try:
        art = positioning.fund_vs_benchmark(df, "Australian Retirement Trust")
        print(art.to_string(index=False))
    except ValueError as e:
        print(f"  {e}")


if __name__ == "__main__":
    main()
