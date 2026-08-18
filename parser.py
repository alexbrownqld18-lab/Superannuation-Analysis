"""
parser.py — normalise raw APRA Excel files into clean DataFrames.

Each APRA release may have slightly different sheet names and column headers.
This module abstracts those differences.

Output schema (annual_fund_level)
----------------------------------
rse_name            str
abn                 str
report_period       date
asset_class         str    (one of ASSET_CLASSES, or "Other")
value_aud_m         float
allocation_pct      float  (0–100)
member_count        float
total_assets_aud_m  float

For other datasets the schema follows their natural structure,
normalised through the column_map in datasets.py.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Optional

import pandas as pd

from .datasets import DatasetSpec

logger = logging.getLogger(__name__)

ASSET_CLASSES = [
    "Domestic equities",
    "International equities",
    "Fixed income",
    "Property",
    "Alternatives",
    "Cash and short-term",
    "Other",
]

_AC_MAP: dict[str, str] = {
    "australian shares": "Domestic equities",
    "domestic equities": "Domestic equities",
    "aust shares": "Domestic equities",
    "listed australian equities": "Domestic equities",
    "international shares": "International equities",
    "overseas shares": "International equities",
    "international equities": "International equities",
    "listed international equities": "International equities",
    "fixed interest": "Fixed income",
    "fixed income": "Fixed income",
    "bonds": "Fixed income",
    "australian fixed interest": "Fixed income",
    "international fixed interest": "Fixed income",
    "property": "Property",
    "listed property": "Property",
    "real assets": "Property",
    "alternatives": "Alternatives",
    "infrastructure": "Alternatives",
    "private equity": "Alternatives",
    "hedge funds": "Alternatives",
    "commodities": "Alternatives",
    "cash": "Cash and short-term",
    "cash and short-term securities": "Cash and short-term",
    "other": "Other",
}

# Fund merger / rename map — keep consistent time-series across mergers.
FUND_MERGER_MAP: dict[str, str] = {
    "sunsuper superannuation fund": "Australian Retirement Trust",
    "qsuper": "Australian Retirement Trust",
    "first state super": "Aware Super",
    "vicsuper": "Aware Super",
    "amp superannuation savings trust": "Insignia Financial",
    "amp super": "Insignia Financial",
    "onepath masterfund": "Insignia Financial",
    "hostplus superannuation fund": "Hostplus",
    "rest superannuation": "REST Super",
    "retail employees superannuation trust": "REST Super",
    "health employees superannuation trust australia": "HESTA",
    "construction and building unions superannuation fund": "Cbus",
    "bt super for life": "BT Super",
    "westpac group superannuation": "BT Super",
    "colonial first state firstchoice superannuation trust": "Colonial First State",
    "mlc superannuation fund": "MLC Super",
}


def _ac(raw: str) -> str:
    return _AC_MAP.get(raw.strip().lower(), "Other")


def _fund(raw: str) -> str:
    if not isinstance(raw, str):
        return str(raw)
    return FUND_MERGER_MAP.get(raw.strip().lower(), raw.strip())


def _to_float(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return float("nan")


class APRAParser:
    """Parse a raw APRA Excel file (bytes or path) into a tidy DataFrame."""

    def parse(
        self,
        source: bytes | Path,
        spec: DatasetSpec,
        year: int,
        quarter: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Parse an APRA disclosure file.

        Parameters
        ----------
        source : bytes or Path
            Raw file bytes or path to the file.
        spec : DatasetSpec
            Dataset specification from datasets.DATASETS.
        year : int
        quarter : int, optional

        Returns
        -------
        pd.DataFrame  — normalised, tidy
        """
        if isinstance(source, Path):
            source = source.read_bytes()

        xls = pd.ExcelFile(BytesIO(source), engine="openpyxl")
        sheets = xls.sheet_names
        logger.debug("Sheets: %s", sheets)

        if spec.key == "annual_fund_level":
            return self._parse_annual(xls, sheets, year)
        elif spec.key == "quarterly":
            return self._parse_quarterly(xls, sheets, year, quarter or 4)
        else:
            return self._parse_generic(xls, sheets, spec)

    # ------------------------------------------------------------------
    # Annual fund-level
    # ------------------------------------------------------------------

    def _parse_annual(self, xls, sheets: list[str], year: int) -> pd.DataFrame:
        target = self._best_sheet(sheets, year)
        raw = pd.read_excel(xls, sheet_name=target, header=None, engine="openpyxl")
        return self._wide_to_tidy(raw, period=date(year, 6, 30))

    def _parse_quarterly(self, xls, sheets: list[str], year: int, quarter: int) -> pd.DataFrame:
        month = {1: 3, 2: 6, 3: 9, 4: 12}[quarter]
        period_end = date(year, month, 28 if month == 2 else 30)
        target = sheets[0]
        raw = pd.read_excel(xls, sheet_name=target, header=None, engine="openpyxl")
        return self._wide_to_tidy(raw, period=period_end)

    def _parse_generic(self, xls, sheets: list[str], spec: DatasetSpec) -> pd.DataFrame:
        raw = pd.read_excel(xls, sheet_name=sheets[0], engine="openpyxl")
        raw.columns = [
            spec.column_map.get(str(c).lower().strip(), str(c).strip())
            for c in raw.columns
        ]
        return raw

    @staticmethod
    def _best_sheet(sheets: list[str], year: int) -> str:
        fy = f"{year - 1}-{str(year)[-2:]}"
        for s in sheets:
            if any(k in s.lower() for k in ("asset", "allocation", fy, str(year))):
                return s
        return sheets[0]

    def _wide_to_tidy(self, raw: pd.DataFrame, period: date) -> pd.DataFrame:
        """Detect header row, then reshape wide → tidy."""
        header_row = None
        for i, row in raw.iterrows():
            vals = [str(v).lower() for v in row if pd.notna(v)]
            if any("rse" in v or "fund name" in v or "abn" in v for v in vals):
                header_row = i
                break

        if header_row is None:
            logger.warning("Header row not found; returning empty DataFrame")
            return pd.DataFrame()

        df = raw.iloc[header_row + 1:].copy()
        df.columns = [str(c) for c in raw.iloc[header_row]]
        df = df.dropna(how="all").reset_index(drop=True)

        # Identify key columns
        name_col = next(
            (c for c in df.columns if re.search(r"rse name|fund name|entity name", c, re.I)),
            next((c for c in df.columns if df[c].dtype == object), None),
        )
        abn_col = next((c for c in df.columns if re.search(r"\babn\b", c, re.I)), None)
        total_col = next((c for c in df.columns if re.search(r"total.*(asset|fund)", c, re.I)), None)
        member_col = next((c for c in df.columns if re.search(r"member", c, re.I)), None)

        # Map asset-class columns
        ac_cols: dict[str, str] = {}
        for col in df.columns:
            ac = _ac(col)
            if ac != "Other" or col.lower().strip() == "other":
                ac_cols[ac] = col

        rows = []
        for _, row in df.iterrows():
            rse_raw = row.get(name_col) if name_col else None
            if not isinstance(rse_raw, str) or not rse_raw.strip():
                continue
            rse_name = _fund(rse_raw)
            abn = str(row.get(abn_col, "")).replace(" ", "") if abn_col else ""
            total = _to_float(row.get(total_col)) if total_col else float("nan")
            members = _to_float(row.get(member_col)) if member_col else float("nan")

            for ac, col in ac_cols.items():
                val = _to_float(row.get(col))
                alloc = (val / total * 100) if total and not pd.isna(total) else float("nan")
                rows.append({
                    "rse_name": rse_name,
                    "abn": abn,
                    "report_period": period,
                    "asset_class": ac,
                    "value_aud_m": val,
                    "allocation_pct": alloc,
                    "member_count": members,
                    "total_assets_aud_m": total,
                })

        return pd.DataFrame(rows)
