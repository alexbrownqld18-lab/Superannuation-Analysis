"""
crowding_risk.py — institutional crowding and concentration metrics.

APRA data gives asset-class-level allocations, not individual security
holdings.  Crowding at the asset-class level is still strategically
important: when every large RSE is simultaneously overweight domestic
equities, a forced deleveraging by one fund (e.g. due to a liquidity event
or member redemptions) can move the whole market.

Metrics implemented
-------------------
hhi(df)                  Herfindahl-Hirschman Index per asset class
overlap_matrix(df)       Pairwise Overlap Coefficient between funds
crowding_score(df)       Composite crowding rank per fund (0 = least, 1 = most)
peer_z_score(df)         Each fund's allocation z-score vs peer group
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Herfindahl-Hirschman Index
# ---------------------------------------------------------------------------

def hhi(df: pd.DataFrame, period: str | None = None) -> pd.DataFrame:
    """
    Compute the HHI for each asset class across all RSEs.

    HHI = Σ (s_i)² where s_i is fund i's share of the industry total in that
    asset class.  1/N = perfectly even; 1.0 = complete monopoly.

    Parameters
    ----------
    df : DataFrame
        Normalised APRA data with columns:
        rse_name, report_period, asset_class, value_aud_m
    period : str, optional
        Filter to a specific period (ISO date string).

    Returns
    -------
    DataFrame with columns: report_period, asset_class, hhi, n_funds,
                            leader, leader_share_pct
    """
    if period:
        df = df[df["report_period"].astype(str) == period]

    results = []
    for (prd, ac), grp in df.groupby(["report_period", "asset_class"]):
        total = grp["value_aud_m"].sum()
        if total <= 0:
            continue
        shares = grp["value_aud_m"] / total
        h = (shares ** 2).sum()
        leader_idx = grp["value_aud_m"].idxmax()
        leader = grp.loc[leader_idx, "rse_name"] if not grp.empty else ""
        leader_share = shares[leader_idx] * 100 if not grp.empty else float("nan")
        results.append({
            "report_period": prd,
            "asset_class": ac,
            "hhi": round(float(h), 4),
            "n_funds": len(grp),
            "leader": leader,
            "leader_share_pct": round(leader_share, 1),
        })

    return pd.DataFrame(results).sort_values(["report_period", "hhi"], ascending=[True, False])


# ---------------------------------------------------------------------------
# Pairwise Overlap Coefficient
# ---------------------------------------------------------------------------

def overlap_matrix(df: pd.DataFrame, period: str | None = None) -> pd.DataFrame:
    """
    Compute pairwise Overlap Coefficient (Szymkiewicz-Simpson) between funds.

    For asset-class-level data we treat allocation_pct vectors as proxies for
    portfolio composition.  Overlap = min(a_i, a_j).sum() / min(sum_i, sum_j).
    A value of 1.0 means the smaller fund's portfolio is entirely contained
    in the larger fund's.

    Returns a square DataFrame indexed by rse_name.
    """
    if period:
        df = df[df["report_period"].astype(str) == period]
    if df.empty:
        return pd.DataFrame()

    latest = df["report_period"].max() if period is None else period

    piv = (
        df[df["report_period"] == latest]
        .pivot_table(index="rse_name", columns="asset_class", values="allocation_pct", fill_value=0)
    )

    funds = piv.index.tolist()
    n = len(funds)
    mat = np.zeros((n, n))

    for i in range(n):
        for j in range(n):
            a = piv.iloc[i].values
            b = piv.iloc[j].values
            denom = min(a.sum(), b.sum())
            mat[i, j] = np.minimum(a, b).sum() / denom if denom > 0 else 0.0

    # Named index so reset_index() produces a 'rse_name' column downstream.
    named_idx = pd.Index(funds, name="rse_name")
    return pd.DataFrame(mat, index=named_idx, columns=named_idx).round(3)


# ---------------------------------------------------------------------------
# Peer z-score — how extreme is each fund's allocation vs peers?
# ---------------------------------------------------------------------------

def peer_z_score(df: pd.DataFrame, period: str | None = None) -> pd.DataFrame:
    """
    Compute each fund's allocation z-score relative to its peer group,
    by asset class.

    Returns a DataFrame with columns:
        rse_name, report_period, asset_class, allocation_pct,
        peer_mean_pct, peer_std_pct, z_score
    """
    if period:
        df = df[df["report_period"].astype(str) == period]
    if df.empty:
        return pd.DataFrame()

    # Compute peer stats via agg — avoids GroupBy.apply FutureWarning in pandas 2.x.
    stats = (
        df.groupby(["report_period", "asset_class"])["allocation_pct"]
        .agg(peer_mean_pct="mean", peer_std_pct="std")
        .reset_index()
    )
    result = df.merge(stats, on=["report_period", "asset_class"], how="left")
    result["z_score"] = np.where(
        result["peer_std_pct"] > 0,
        (result["allocation_pct"] - result["peer_mean_pct"]) / result["peer_std_pct"],
        0.0,
    )
    return (
        result
        .sort_values(["report_period", "z_score"], ascending=[True, False])
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Composite crowding score
# ---------------------------------------------------------------------------

def crowding_score(df: pd.DataFrame, period: str | None = None) -> pd.DataFrame:
    """
    Composite crowding score per fund.

    Definition: a fund is "crowded" if it has high overlap with peers AND
    its largest asset-class bets have high HHI (concentrated industry exposure).

    Score methodology (all normalised 0→1, equal weight):
    1. Mean pairwise overlap with all other funds
    2. Mean |z_score| across asset classes (how extreme are its bets?)
    3. Share of assets in the two most-crowded asset classes (by HHI)

    Returns DataFrame sorted descending by crowding_score.
    """
    if period:
        df = df[df["report_period"].astype(str) == period]
    if df.empty:
        return pd.DataFrame()

    # Component 1: mean pairwise overlap
    ov = overlap_matrix(df, period=period)
    np.fill_diagonal(ov.values, np.nan)
    c1 = ov.mean(axis=1).rename("mean_overlap")

    # Component 2: mean absolute z-score
    zs = peer_z_score(df, period=period)
    c2 = zs.groupby("rse_name")["z_score"].apply(lambda x: x.abs().mean()).rename("mean_abs_z")

    # Component 3: share in two most-crowded asset classes
    hhi_df = hhi(df, period=period)
    top2_ac = hhi_df.nlargest(2, "hhi")["asset_class"].tolist()
    top2_share = (
        df[df["asset_class"].isin(top2_ac)]
        .groupby("rse_name")["allocation_pct"]
        .sum()
        .rename("top2_crowded_alloc")
    )

    combined = pd.concat([c1, c2, top2_share], axis=1).dropna()
    for col in combined.columns:
        rng = combined[col].max() - combined[col].min()
        combined[col] = (combined[col] - combined[col].min()) / rng if rng > 0 else 0.0

    combined["crowding_score"] = combined.mean(axis=1)
    return (
        combined.reset_index()
        .sort_values("crowding_score", ascending=False)
        .reset_index(drop=True)
    )
