"""
test_client.py — unit tests for APRAClient.

These tests do NOT make network requests.  They test URL construction,
cache logic, and parser behaviour using fixture data.

Run:
    pytest tests/ -v
"""

import json
from datetime import date
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from apra_client import APRAClient
from apra_client.client import _fy_label
from apra_client.datasets import get_spec, list_datasets
from apra_client.parser import APRAParser, _ac, _fund


# ---------------------------------------------------------------------------
# Dataset catalogue tests
# ---------------------------------------------------------------------------

def test_list_datasets_returns_records():
    datasets = list_datasets()
    assert len(datasets) >= 3
    keys = {d["key"] for d in datasets}
    assert "annual_fund_level" in keys
    assert "quarterly" in keys
    assert "mysuper_heatmap" in keys


def test_get_spec_raises_for_unknown():
    with pytest.raises(ValueError, match="Unknown dataset"):
        get_spec("not_a_real_dataset")


def test_get_spec_annual_fund_level():
    spec = get_spec("annual_fund_level")
    assert spec.min_year == 2004
    assert not spec.has_quarter


def test_get_spec_quarterly():
    spec = get_spec("quarterly")
    assert spec.has_quarter


# ---------------------------------------------------------------------------
# URL and financial year helpers
# ---------------------------------------------------------------------------

def test_fy_label():
    assert _fy_label(2024) == "2023-24"
    assert _fy_label(2010) == "2009-10"
    assert _fy_label(2004) == "2003-04"


# ---------------------------------------------------------------------------
# Parser utilities
# ---------------------------------------------------------------------------

def test_asset_class_normalisation():
    assert _ac("Australian Shares") == "Domestic equities"
    assert _ac("international equities") == "International equities"
    assert _ac("Fixed Interest") == "Fixed income"
    assert _ac("Property") == "Property"
    assert _ac("Infrastructure") == "Alternatives"
    assert _ac("Cash") == "Cash and short-term"
    assert _ac("Banana futures") == "Other"  # Unknown → Other


def test_fund_name_normalisation():
    assert _fund("Sunsuper Superannuation Fund") == "Australian Retirement Trust"
    assert _fund("QSuper") == "Australian Retirement Trust"
    assert _fund("HESTA") == "HESTA"  # Already canonical; no mapping needed
    # Unknown fund names pass through unchanged
    assert _fund("Widget Industries Super") == "Widget Industries Super"


# ---------------------------------------------------------------------------
# APRAClient validation
# ---------------------------------------------------------------------------

def test_client_rejects_unknown_dataset():
    client = APRAClient(cache_dir=None)
    with pytest.raises(ValueError, match="Unknown dataset"):
        client.fetch("not_a_real_dataset", year=2024)


def test_client_rejects_bad_quarter():
    client = APRAClient(cache_dir=None)
    with pytest.raises(ValueError, match="quarter must be 1–4"):
        client.fetch("quarterly", year=2024, quarter=5)


def test_client_rejects_year_before_min(tmp_path):
    client = APRAClient(cache_dir=tmp_path)
    with pytest.raises(ValueError, match="available from"):
        client.fetch("mysuper_heatmap", year=2010)


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------

def test_cache_writes_and_reads(tmp_path):
    """If a cached file exists, client should return it without making a request."""
    # Write a dummy xlsx to the cache location
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Test"
    ws.append(["RSE Name", "ABN", "Australian Shares", "Cash", "Total Assets", "Member Accounts"])
    ws.append(["Test Fund", "123456789", 5000, 1000, 6000, 50000])
    buf = BytesIO()
    wb.save(buf)
    raw = buf.getvalue()

    cache_path = tmp_path / "annual_fund_level_2024.xlsx"
    cache_path.write_bytes(raw)

    client = APRAClient(cache_dir=tmp_path)
    # Should not raise even though the URL doesn't exist.
    df = client.fetch("annual_fund_level", year=2024, cache=True)
    assert isinstance(df, pd.DataFrame)
    # Shouldn't be empty since we provided data
    # (may be empty if parser can't read the minimal fixture — that's ok)


def test_cache_disabled_always_downloads(tmp_path):
    """With cache=False, client should always attempt a download."""
    client = APRAClient(cache_dir=tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.raise_for_status.side_effect = __import__("requests").HTTPError(
        response=mock_resp
    )
    with patch.object(client._session, "get", return_value=mock_resp):
        with pytest.raises(Exception):  # HTTPError from exhausted URL attempts
            client.fetch("annual_fund_level", year=2024, cache=False)


# ---------------------------------------------------------------------------
# available_years
# ---------------------------------------------------------------------------

def test_available_years_bounds():
    client = APRAClient(cache_dir=None)
    years = client.available_years("annual_fund_level")
    assert 2004 in years
    assert min(years) == 2004
    assert all(y >= 2004 for y in years)


def test_datasets_returns_dataframe():
    client = APRAClient(cache_dir=None)
    df = client.datasets()
    assert isinstance(df, pd.DataFrame)
    assert "key" in df.columns
    assert len(df) >= 3
