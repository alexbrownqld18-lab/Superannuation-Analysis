"""
holdings_parser.py — parse APRA Excel disclosures into normalised DataFrames.

APRA changes column names and sheet layouts between releases.  This module
normalises them to a consistent schema across years.  The fund merger map
handles the most common RSE name changes since 2004.

Output schema
-------------
rse_name          str    normalised fund name
abn               str    ABN (stripped of spaces)
report_period     date   period end date
asset_class       str    one of ASSET_CLASSES
value_aud_m       float  AUD millions
allocation_pct    float  percentage of total assets (0–100)
member_count      float  total member count
total_assets_aud_m float total RSE assets in AUD millions
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Asset class normalisation
# ---------------------------------------------------------------------------

ASSET_CLASSES = [
    "Domestic equities",
    "International equities",
    "Fixed income",
    "Property",
    "Alternatives",
    "Cash and short-term",
    "Other",
]

# Map APRA's various column/label wordings onto our canonical asset classes.
_AC_MAP: dict[str, str] = {
    # Domestic equities
    "australian shares": "Domestic equities",
    "domestic equities": "Domestic equities",
    "aust shares": "Domestic equities",
    "listed australian equities": "Domestic equities",
    # International equities
    "international shares": "International equities",
    "overseas shares": "International equities",
    "international equities": "International equities",
    "listed international equities": "International equities",
    # Fixed income
    "fixed interest": "Fixed income",
    "fixed income": "Fixed income",
    "bonds": "Fixed income",
    "australian fixed interest": "Fixed income",
    "international fixed interest": "Fixed income",
    # Property
    "property": "Property",
    "real assets": "Property",
    "listed property": "Property",
    # Alternatives
    "alternatives": "Alternatives",
    "infrastructure": "Alternatives",
    "private equity": "Alternatives",
    "hedge funds": "Alternatives",
    "commodities": "Alternatives",
    # Cash
    "cash": "Cash and short-term",
    "cash and short-term securities": "Cash and short-term",
    "cash and fixed interest": "Cash and short-term",
    # Other
    "other": "Other",
}


def normalise_asset_class(raw: str) -> str:
    if not isinstance(raw, str):
        return "Other"
    key = raw.strip().lower()
    return _AC_MAP.get(key, "Other")


# ---------------------------------------------------------------------------
# Fund merger / rename map
# ---------------------------------------------------------------------------
# Key: historical name (lower-cased).  Value: canonical name.
# Add new mergers here rather than in calling code.

FUND_MERGER_MAP: dict[str, str] = {
    # ART
    "sunsuper superannuation fund": "Australian Retirement Trust",
    "qsuper": "Australian Retirement Trust",
    "australian retirement trust": "Australian Retirement Trust",

    # Aware Super
    "first state super": "Aware Super",
    "vicsuper": "Aware Super",
    "aware super": "Aware Super",

    # Mercer
    "mercer super trust": "Mercer Super Trust",
    "mercer superannuation": "Mercer Super Trust",

    # AMP / Insignia
    "amp superannuation savings trust": "Insignia Financial",
    "amp super": "Insignia Financial",
    "ipac superannuation": "Insignia Financial",
    "onepath masterfund": "Insignia Financial",
    "insignia financial": "Insignia Financial",

    # Hostplus
    "hostplus superannuation fund": "Hostplus",

    # Rest
    "rest superannuation": "REST Super",
    "retail employees superannuation trust": "REST Super",

    # HESTA
    "hesta": "HESTA",
    "health employees superannuation trust australia": "HESTA",

    # Cbus
    "cbus": "Cbus",
    "construction and building unions superannuation fund": "Cbus",

    # UniSuper
    "unisuper": "UniSuper",

    # MLC
    "mlc superannuation fund": "MLC Super",
    "mlc super": "MLC Super",
    "navigator australia": "MLC Super",

    # BT
    "bt super for life": "BT Super",
    "westpac group superannuation": "BT Super",
    "bt super": "BT Super",

    # Colonial First State
    "colonial first state firstchoice superannuation trust": "Colonial First State",
    "colonial first state super": "Colonial First State",

    # QIC — manages government super mandates, not a retail RSE
    # Keep as-is

    # CareSuper
    "caresuper": "CareSuper",

    # Vanguard Super
    "vanguard super": "Vanguard Super",
}


def normalise_fund_name(raw: str) -> str:
    if not isinstance(raw, str):
        return raw
    key = raw.strip().lower()
    return FUND_MERGER_MAP.get(key, raw.strip())


# ---------------------------------------------------------------------------
# Sheet and column detection helpers
# ---------------------------------------------------------------------------

_PERIOD_PATTERNS = [
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),       # 2024-06-30
    re.compile(r"(\d{2})/(\d{2})/(\d{4})"),        # 30/06/2024
    re.compile(r"(\d{4})"),                         # bare year → June 30
]

def _parse_period(raw) -> Optional[date]:
    """Try to extract a date from a cell value."""
    if isinstance(raw, (pd.Timestamp, date)):
        return pd.Timestamp(raw).date()
    s = str(raw).strip()
    m = _PERIOD_PATTERNS[0].match(s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _PERIOD_PATTERNS[1].match(s)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = _PERIOD_PATTERNS[2].match(s)
    if m:
        return date(int(m.group(1)), 6, 30)
    return None


def _detect_abn_col(df: pd.DataFrame) -> Optional[str]:
    for col in df.columns:
        if re.search(r"abn", str(col), re.I):
            return col
    return None


def _detect_name_col(df: pd.DataFrame) -> Optional[str]:
    for col in df.columns:
        c = str(col).lower()
        if any(k in c for k in ("rse name", "fund name", "entity name", "registrable")):
            return col
    # Fallback: the first object-dtype column
    for col in df.columns:
        if df[col].dtype == object:
            return col
    return None


def _to_float(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return float("nan")


# ---------------------------------------------------------------------------
# Parser entry points
# ---------------------------------------------------------------------------

class APRAParser:
    """
    Parse APRA Annual Fund-Level Superannuation Statistics Excel files.

    Produces a normalised, tidy DataFrame across all sheets and years.
    """

    def parse_annual_fund_level(self, path: Path, year: int) -> pd.DataFrame:
        """
        Parse an APRA annual fund-level Excel file.

        Returns a tidy DataFrame with one row per (rse_name, asset_class).
        """
        xls = pd.ExcelFile(path, engine="openpyxl")
        sheets = xls.sheet_names
        logger.info("Sheets in %s: %s", path.name, sheets)

        # APRA uses several sheet naming conventions — try each.
        target_sheet = self._find_sheet(xls, sheets, year)
        if target_sheet is None:
            # Fallback: try to combine all non-metadata sheets
            target_sheet = sheets[0]
            logger.warning("Could not identify primary sheet; using '%s'", target_sheet)

        raw = pd.read_excel(xls, sheet_name=target_sheet, header=None, engine="openpyxl")
        return self._parse_wide_sheet(raw, year)

    def parse_quarterly(self, path: Path, year: int, quarter: int) -> pd.DataFrame:
        """Parse APRA quarterly statistics file."""
        # Quarterly files have a similar structure; reuse the same parser.
        report_date = date(year, {1: 3, 2: 6, 3: 9, 4: 12}[quarter], 30)
        xls = pd.ExcelFile(path, engine="openpyxl")
        sheets = xls.sheet_names
        raw = pd.read_excel(xls, sheet_name=sheets[0], header=None, engine="openpyxl")
        return self._parse_wide_sheet(raw, year, default_period=report_date)

    # ------------------------------------------------------------------
    # Internal parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _find_sheet(xls: pd.ExcelFile, sheets: list[str], year: int) -> Optional[str]:
        """Try to find the main data sheet by name."""
        fy = f"{year - 1}-{str(year)[-2:]}"
        candidates = [
            s for s in sheets
            if any(k in s.lower() for k in ("asset", "allocation", "fund level", fy, str(year)))
        ]
        return candidates[0] if candidates else None

    def _parse_wide_sheet(
        self, raw: pd.DataFrame, year: int, default_period: Optional[date] = None
    ) -> pd.DataFrame:
        """
        APRA wide-format sheets: funds as rows, asset classes as column headers.
        Find the header row by scanning for 'rse' or 'fund name', then reshape.
        """
        header_row = None
        for i, row in raw.iterrows():
            vals = [str(v).lower() for v in row if pd.notna(v)]
            if any("rse" in v or "fund name" in v or "abn" in v for v in vals):
                header_row = i
                break

        if header_row is None:
            logger.warning("Could not find header row in sheet; skipping")
            return pd.DataFrame()

        df = raw.iloc[header_row + 1:].copy()
        df.columns = [str(c) for c in raw.iloc[header_row]]
        df = df.dropna(how="all").reset_index(drop=True)

        name_col = _detect_name_col(df)
        abn_col = _detect_abn_col(df)

        if name_col is None:
            logger.error("Cannot identify fund name column")
            return pd.DataFrame()

        # Identify asset-class value columns
        ac_cols: dict[str, str] = {}  # canonical → raw column name
        for col in df.columns:
            ac = normalise_asset_class(str(col))
            if ac != "Other" or str(col).lower() in ("other",):
                ac_cols[ac] = col

        # Find total-assets column
        total_col = None
        for col in df.columns:
            if re.search(r"total.*(asset|fund)", str(col), re.I):
                total_col = col
                break

        # Find member count column
        member_col = None
        for col in df.columns:
            if re.search(r"member", str(col), re.I):
                member_col = col
                break

        report_period = default_period or date(year, 6, 30)

        rows = []
        for _, row in df.iterrows():
            rse_raw = row.get(name_col, "")
            if not isinstance(rse_raw, str) or not rse_raw.strip():
                continue
            rse_name = normalise_fund_name(rse_raw)
            abn = str(row.get(abn_col, "")).replace(" ", "") if abn_col else ""
            total = _to_float(row.get(total_col, float("nan"))) if total_col else float("nan")
            members = _to_float(row.get(member_col, float("nan"))) if member_col else float("nan")

            for ac, col in ac_cols.items():
                val = _to_float(row.get(col, float("nan")))
                alloc = (val / total * 100) if (total and not pd.isna(total)) else float("nan")
                rows.append({
                    "rse_name": rse_name,
                    "abn": abn,
                    "report_period": report_period,
                    "asset_class": ac,
                    "value_aud_m": val,
                    "allocation_pct": alloc,
                    "member_count": members,
                    "total_assets_aud_m": total,
                })

        result = pd.DataFrame(rows)
        logger.info("Parsed %d rows from %d funds", len(result), result["rse_name"].nunique())
        return result
