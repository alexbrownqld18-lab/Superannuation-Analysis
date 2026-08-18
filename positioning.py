"""
positioning.py — institutional positioning analysis for Australian super funds.

Builds on the normalised APRA data to answer:
- How is industry positioning changing over time? (trend analysis)
- Which funds are most contrarian vs consensus? (deviation from mean)
- What are the aggregate industry flows implied by allocation changes? (delta analysis)
- Relevant concentration: ART and QIC positioning vs the broader system.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Funds of particular interest for institutional clients.
FOCUS_FUNDS = [
    "Australian Retirement Trust",  # ART — largest RSE
    "QIC",
    "UniSuper",
    "Aware Super",
    "HESTA",
    "Hostplus",
    "REST Super",
    "Cbus",
]


def industry_allocation_trend(df: pd.DataFrame) -> pd.DataFrame:
    """
    Industry-wide weighted-average allocation to each asset class over time.

    Weights by total_assets_aud_m so large funds receive proportional influence.
    Returns one row per (report_period, asset_class).
    """
    results = []
    for (period, ac), grp in df.groupby(["report_period", "asset_class"]):
        valid = grp.dropna(subset=["allocation_pct", "total_assets_aud_m"])
        if valid.empty:
            continue
        w = valid["total_assets_aud_m"]
        wa = np.average(valid["allocation_pct"], weights=w)
        simple = valid["allocation_pct"].mean()
        total_industry_aud_m = grp["value_aud_m"].sum()
        results.append({
            "report_period": period,
            "asset_class": ac,
            "weighted_avg_alloc_pct": round(wa, 2),
            "simple_avg_alloc_pct": round(simple, 2),
            "total_industry_value_aud_m": round(total_industry_aud_m, 0),
            "n_funds": len(valid),
        })

    return pd.DataFrame(results).sort_values(["asset_class", "report_period"])


def fund_vs_benchmark(
    df: pd.DataFrame,
    fund_name: str,
    period: Optional[str] = None,
) -> pd.DataFrame:
    """
    Compare a specific fund's allocations against the industry weighted average.

    Returns a DataFrame with columns:
        asset_class, fund_alloc_pct, industry_alloc_pct, active_tilt_pct
    Positive active_tilt = overweight vs peers.
    """
    if period:
        df = df[df["report_period"].astype(str) == period]

    trend = industry_allocation_trend(df)
    # Use the latest period available
    latest = df["report_period"].max()
    industry = trend[trend["report_period"] == latest][["asset_class", "weighted_avg_alloc_pct"]]

    fund_data = df[
        (df["rse_name"].str.contains(fund_name, case=False, na=False)) &
        (df["report_period"] == latest)
    ][["asset_class", "allocation_pct"]].rename(columns={"allocation_pct": "fund_alloc_pct"})

    if fund_data.empty:
        raise ValueError(f"Fund '{fund_name}' not found in the dataset.")

    merged = fund_data.merge(industry, on="asset_class", how="left")
    merged["active_tilt_pct"] = (
        merged["fund_alloc_pct"] - merged["weighted_avg_alloc_pct"]
    ).round(2)
    merged["fund_alloc_pct"] = merged["fund_alloc_pct"].round(2)
    merged["weighted_avg_alloc_pct"] = merged["weighted_avg_alloc_pct"].round(2)
    return merged.sort_values("active_tilt_pct", ascending=False)


def implied_flow_delta(df: pd.DataFrame) -> pd.DataFrame:
    """
    Estimate implied asset-class flows from period-over-period allocation changes.

    This is an approximation: true flows require knowing inflows, outflows, and
    market returns.  This gives a directional signal — the change in AUD exposure
    to each asset class — not an exact flow figure.

    Returns a DataFrame with columns:
        rse_name, asset_class, period_t, period_t1,
        value_aud_m_t, value_aud_m_t1, implied_delta_aud_m
    """
    periods = sorted(df["report_period"].unique())
    if len(periods) < 2:
        return pd.DataFrame()

    rows = []
    for i in range(len(periods) - 1):
        t0, t1 = periods[i], periods[i + 1]
        p0 = df[df["report_period"] == t0][["rse_name", "asset_class", "value_aud_m"]]
        p1 = df[df["report_period"] == t1][["rse_name", "asset_class", "value_aud_m"]]
        merged = p0.merge(p1, on=["rse_name", "asset_class"], suffixes=("_t", "_t1"), how="inner")
        merged["implied_delta_aud_m"] = merged["value_aud_m_t1"] - merged["value_aud_m_t"]
        merged["period_t"] = t0
        merged["period_t1"] = t1
        rows.append(merged)

    if not rows:
        return pd.DataFrame()

    out = pd.concat(rows, ignore_index=True)
    return out[[
        "rse_name", "asset_class", "period_t", "period_t1",
        "value_aud_m_t", "value_aud_m_t1", "implied_delta_aud_m",
    ]].sort_values(["period_t1", "implied_delta_aud_m"])


def art_qic_snapshot(df: pd.DataFrame, period: Optional[str] = None) -> dict[str, pd.DataFrame]:
    """
    Return positioning snapshots for ART and QIC specifically.

    Used by institutional clients who need to monitor these two funds.
    """
    if period:
        df = df[df["report_period"].astype(str) == period]
    latest = df["report_period"].max()
    snaps = {}
    for fund in ("Australian Retirement Trust", "QIC"):
        data = df[
            (df["rse_name"].str.contains(fund, case=False, na=False)) &
            (df["report_period"] == latest)
        ]
        if not data.empty:
            snaps[fund] = data[["asset_class", "allocation_pct", "value_aud_m"]].sort_values(
                "allocation_pct", ascending=False
            )
    return snaps
