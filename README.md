# apra-client

> Fetch and normalise APRA superannuation disclosure data in one line. Returns a pandas DataFrame.

```python
from apra_client import APRAClient

client = APRAClient()
df = client.fetch("annual_fund_level", year=2024)
print(df.head())
```

## Why it exists

APRA publishes rich superannuation fund-level statistics as Excel files on their website. Getting from "download the zip" to a clean DataFrame takes 40 lines of boilerplate every time. This library does that 40 lines once.

## Install

```bash
pip install apra-client
```

Requires Python 3.9+. The only hard dependencies are `requests`, `pandas`, and `openpyxl`.

## Usage

```python
from apra_client import APRAClient

client = APRAClient()

# Annual fund-level statistics (asset allocation, member counts, returns)
df = client.fetch("annual_fund_level", year=2024)

# Quarterly statistics (higher frequency, less granularity)
df = client.fetch("quarterly", year=2024, quarter=2)

# List available datasets and years
print(client.datasets())

# Fetch with local caching (skips download if file already on disk)
df = client.fetch("annual_fund_level", year=2023, cache=True)
```

## What you get

| Column | Description |
|--------|-------------|
| `rse_name` | Registrable Superannuation Entity name (normalised) |
| `abn` | ABN of the RSE |
| `report_period` | Period end date |
| `asset_class` | Domestic equities, Intl equities, Fixed income, Property, Alternatives, Cash |
| `value_aud_m` | Asset value in AUD millions |
| `allocation_pct` | Percentage of total assets |
| `member_count` | Total member count |
| `total_assets_aud_m` | Total RSE assets |

The normaliser handles APRA's column name changes across releases and maps common fund name variants (mergers, rebrands) so time-series are consistent.

## Available datasets

| Key | Source | Frequency | Coverage |
|-----|--------|-----------|----------|
| `annual_fund_level` | APRA Annual Fund-Level Superannuation Statistics | Annual (FY) | 2004– |
| `quarterly` | APRA Quarterly Superannuation Statistics | Quarterly | 2004– |
| `mysuper_heatmap` | MySuper Product Heatmap | Annual | 2019– |

## Data licensing

All data returned by this library is published by the Australian Prudential Regulation Authority (APRA) under the [Creative Commons Attribution 4.0 International licence](https://creativecommons.org/licenses/by/4.0/). apra-client is a convenience wrapper; the underlying data is Australian Government open data.

## Contributing

Bug reports and PRs welcome, especially for: new APRA dataset endpoints, fund merger mappings, and column normalisation edge cases across older releases.

## Status

Stable. Tested against APRA releases from FY2004 to FY2024.
