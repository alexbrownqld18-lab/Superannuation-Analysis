"""
client.py — APRAClient: the single public interface for apra-client.

Usage
-----
    from apra_client import APRAClient

    client = APRAClient()
    df = client.fetch("annual_fund_level", year=2024)
    df = client.fetch("quarterly", year=2024, quarter=2)
    print(client.datasets())
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import date as dt_date
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
import pandas as pd

from .datasets import APRA_BASE, DatasetSpec, get_spec, list_datasets
from .parser import APRAParser

logger = logging.getLogger(__name__)

QUARTER_LABELS = {1: "March", 2: "June", 3: "September", 4: "December"}


def _fy_label(year: int) -> str:
    return f"{year - 1}-{str(year)[-2:]}"


class APRAClient:
    """
    Fetch and normalise APRA superannuation disclosure data.

    Parameters
    ----------
    cache_dir : Path or str, optional
        Directory for caching downloaded files.  Pass ``None`` to disable caching.
    timeout : int
        HTTP request timeout in seconds.
    user_agent : str
        Identifies this client to APRA's servers.  Please set this to something
        that identifies your project.
    """

    def __init__(
        self,
        cache_dir: Optional[Path | str] = Path(".apra_cache"),
        timeout: int = 120,
        user_agent: str = "apra-client/0.1 (https://pypi.org/project/apra-client/)",
    ):
        self._cache_dir = Path(cache_dir) if cache_dir else None
        if self._cache_dir:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent
        self._parser = APRAParser()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(
        self,
        dataset: str,
        year: int,
        quarter: Optional[int] = None,
        cache: bool = True,
    ) -> pd.DataFrame:
        """
        Fetch and return an APRA dataset as a tidy pandas DataFrame.

        Parameters
        ----------
        dataset : str
            Dataset key.  Call ``client.datasets()`` to see available keys.
        year : int
            Calendar year of the release.  For annual data, this is the
            financial year end — e.g. ``2024`` returns the FY2023-24 data.
        quarter : int, optional
            Quarter number (1–4) for quarterly datasets.
        cache : bool
            If True (default), save downloads to disk and reuse them.

        Returns
        -------
        pd.DataFrame

        Raises
        ------
        ValueError
            If the dataset key is unknown or parameters are invalid.
        requests.HTTPError
            If APRA's server returns an error for all tried URL patterns.
        """
        spec = get_spec(dataset)

        if dataset == "quarterly" and quarter not in (1, 2, 3, 4):
            raise ValueError("quarter must be 1–4 for quarterly dataset")

        if year < spec.min_year:
            raise ValueError(
                f"{dataset} data is available from {spec.min_year}, not {year}."
            )

        # Try cache first.
        cached_path = self._cache_path(dataset, year, quarter)
        if cache and cached_path and cached_path.exists():
            logger.info("Cache hit: %s", cached_path)
            return self._parser.parse(cached_path, spec, year, quarter)

        # Download.
        raw_bytes = self._download(spec, year, quarter)

        # Write cache.
        if cache and cached_path:
            cached_path.write_bytes(raw_bytes)
            logger.info("Cached to: %s", cached_path)

        return self._parser.parse(raw_bytes, spec, year, quarter)

    def datasets(self) -> pd.DataFrame:
        """Return a DataFrame describing all supported datasets."""
        return pd.DataFrame(list_datasets())

    def available_years(self, dataset: str) -> list[int]:
        """Return years for which APRA data is likely available."""
        spec = get_spec(dataset)
        current = dt_date.today().year
        return list(range(spec.min_year, current))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _download(self, spec: DatasetSpec, year: int, quarter: Optional[int]) -> bytes:
        """Try each URL pattern until one returns 200."""
        errors = []
        for pattern in spec.url_patterns:
            for month in spec.release_months:
                url = self._build_url(pattern, year, month, quarter)
                try:
                    resp = self._session.get(url, timeout=self._timeout)
                    resp.raise_for_status()
                    logger.info("Downloaded from: %s (%d bytes)", url, len(resp.content))
                    return resp.content
                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 404:
                        errors.append(f"404: {url}")
                        continue
                    errors.append(f"{e.response.status_code if e.response else '?'}: {url}")
                    continue
                except requests.RequestException as e:
                    errors.append(f"error: {url}: {e}")
                    continue

        raise requests.HTTPError(
            f"Could not download {spec.key} year={year} quarter={quarter}.\n"
            "Check https://www.apra.gov.au/superannuation-statistics for current URLs.\n"
            "Tried:\n" + "\n".join(f"  {e}" for e in errors)
        )

    @staticmethod
    def _build_url(pattern: str, year: int, month: int, quarter: Optional[int]) -> str:
        fy = _fy_label(year)
        qtr = QUARTER_LABELS.get(quarter or 1, "")
        path = pattern.format(year=year, month=month, fy=fy, qtr=qtr)
        return urljoin(APRA_BASE, path)

    def _cache_path(
        self, dataset: str, year: int, quarter: Optional[int]
    ) -> Optional[Path]:
        if not self._cache_dir:
            return None
        fname = f"{dataset}_{year}" + (f"_Q{quarter}" if quarter else "") + ".xlsx"
        return self._cache_dir / fname
