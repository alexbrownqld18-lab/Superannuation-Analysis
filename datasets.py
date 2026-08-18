"""
datasets.py — catalogue of APRA superannuation disclosure datasets.

Stores URL patterns, expected column schemas, and financial-year coverage
for each supported dataset.  Adding a new dataset means adding an entry here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

APRA_BASE = "https://www.apra.gov.au"


@dataclass
class DatasetSpec:
    """Specification for a single APRA dataset."""
    key: str
    description: str
    url_patterns: list[str]          # Tried in order; first 200 wins.
    release_months: list[int]        # Calendar months APRA typically releases.
    # Minimum year data is available.
    min_year: int = 2004
    # Column normalisation: raw name (lower) → canonical name.
    column_map: dict[str, str] = field(default_factory=dict)
    # Whether this dataset has quarterly granularity.
    has_quarter: bool = False


DATASETS: dict[str, DatasetSpec] = {
    "annual_fund_level": DatasetSpec(
        key="annual_fund_level",
        description="APRA Annual Fund-Level Superannuation Statistics — "
                    "asset allocation, member counts, returns by RSE.",
        url_patterns=[
            "/sites/default/files/{year}-{month:02d}/Annual-fund-level-superannuation-statistics-{fy}.xlsx",
            "/sites/default/files/{year}-{month:02d}/Annual%20fund-level%20superannuation%20statistics%20{fy}.xlsx",
            "/sites/default/files/{year}-{month:02d}/Annual-fund-level-superannuation-statistics-{fy}.zip",
        ],
        release_months=[3, 4, 2, 5],
        min_year=2004,
        column_map={
            "rse name": "rse_name",
            "fund name": "rse_name",
            "entity name": "rse_name",
            "abn": "abn",
            "total assets": "total_assets_aud_m",
            "member accounts": "member_count",
            "number of member accounts": "member_count",
        },
    ),

    "quarterly": DatasetSpec(
        key="quarterly",
        description="APRA Quarterly Superannuation Statistics — "
                    "higher-frequency fund-level data.",
        url_patterns=[
            "/sites/default/files/{year}-{month:02d}/Quarterly-superannuation-statistics-{qtr}-{year}.xlsx",
            "/sites/default/files/{year}-{month:02d}/Quarterly%20superannuation%20statistics%20{qtr}%20{year}.xlsx",
        ],
        release_months=[2, 3, 4, 5, 8, 11],
        min_year=2004,
        has_quarter=True,
        column_map={
            "rse name": "rse_name",
            "fund name": "rse_name",
            "abn": "abn",
        },
    ),

    "mysuper_heatmap": DatasetSpec(
        key="mysuper_heatmap",
        description="APRA MySuper Product Heatmap — performance and fee comparison "
                    "for default (MySuper) investment options.",
        url_patterns=[
            "/sites/default/files/{year}-{month:02d}/MySuper-product-heatmap-data-{year}.xlsx",
            "/sites/default/files/{year}-{month:02d}/MySuper%20product%20heatmap%20data%20{year}.xlsx",
        ],
        release_months=[8, 9, 7, 10],
        min_year=2019,
        column_map={
            "product name": "product_name",
            "fund name": "rse_name",
            "abn": "abn",
            "net return": "net_return_pct",
            "fees": "fee_pct",
        },
    ),
}


def list_datasets() -> list[dict]:
    """Return metadata for all supported datasets."""
    return [
        {
            "key": spec.key,
            "description": spec.description,
            "min_year": spec.min_year,
            "has_quarter": spec.has_quarter,
        }
        for spec in DATASETS.values()
    ]


def get_spec(dataset: str) -> DatasetSpec:
    if dataset not in DATASETS:
        raise ValueError(
            f"Unknown dataset '{dataset}'. "
            f"Valid options: {list(DATASETS.keys())}"
        )
    return DATASETS[dataset]
