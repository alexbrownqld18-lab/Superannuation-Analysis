# superannuation-holdings

> APRA disclosure data pipeline for institutional positioning and crowding-risk analysis of Australian superannuation funds.

**Data source:** [APRA Annual Fund-Level Superannuation Statistics](https://www.apra.gov.au/annual-fund-level-superannuation-statistics) — Australian Government, public domain, no licensing exposure.

## What it does

Fetches APRA's publicly released superannuation fund statistics, normalises the Excel disclosures into clean DataFrames, and computes cross-fund positioning metrics and crowding-risk scores. Designed to answer questions like: which asset classes are the most crowded across the major RSEs? Which funds are most overweight domestic equities relative to their peers? Where is systemic concentration risk building?

Directly applicable to ART (Australian Retirement Trust), QIC, and other institutional investors who need to understand how their peers are positioned.

## Why it was built

APRA releases rich fund-level data four times a year that most practitioners load into Excel and never query systematically. This library treats that data as a time-series, normalises across releases, and computes crowding and overlap metrics that are otherwise done by hand.

## How it works

- **Data:** APRA Annual Fund-Level Superannuation Statistics (publicly released Excel files). Asset allocation is reported at the level of domestic equities, international equities, fixed income, property, alternatives, and cash — not individual securities. That is both the limitation and the point: crowding at the asset-class level is the systemic risk that matters for large RSEs.
- **Processing:** The hard part is reconciling APRA's changing Excel layouts across years and normalising fund names, which change with mergers (AMP → Insignia, Sunsuper+QSuper → ART, etc.). The merger map in `holdings_parser.py` handles the most common cases.
- **Output:** Tidy DataFrames ready for analysis, plus a `CrowdingReport` object with HHI by asset class, fund-to-peer overlap coefficients, and a ranked "crowding score" per fund.

## Stack

- Python 3.11
- pandas, openpyxl (Excel parsing)
- requests (APRA file downloads)
- scipy (overlap and concentration metrics)
- matplotlib / seaborn (optional, for report charts)

## Running it locally

```bash
git clone https://github.com/alexbrownqld18-lab/superannuation-holdings
cd superannuation-holdings

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Download the latest APRA release and run analysis
python examples/basic_analysis.py
```

APRA releases annual fund-level data each year, usually February–April for the prior financial year. The fetcher caches downloads in `data/raw/` to avoid repeated requests to the APRA server.

## What's not in this repo

Individual security holdings are not in APRA's public disclosures and are not here. Proprietary fund manager research, client data, and API keys are excluded. If you need security-level holdings you'll need ASIC's substantial shareholder notices (>5% positions only) or a data vendor.

## Data licensing

All data fetched by this library is published by APRA under the [Creative Commons Attribution 4.0 International licence](https://creativecommons.org/licenses/by/4.0/). Attribution: Australian Prudential Regulation Authority (APRA).

## Relevant to

- ART (Australian Retirement Trust) — largest RSE by assets post-merger
- QIC — Queensland government-owned fund manager with super mandates
- Any institution doing peer-positioning or systemic-risk analysis across the Australian super system

## Status

Actively developed. Fund merger map is manually maintained — PRs welcome for recent mergers.
