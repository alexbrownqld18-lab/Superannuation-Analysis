"""
apra_fetcher.py — download and cache APRA superannuation disclosure files.

APRA releases fund-level statistics as Excel files at predictable URLs.
This module fetches them, validates checksums, and caches locally so that
repeat analysis runs do not hammer the APRA server.

All data returned is Australian Government open data licensed under the
Creative Commons Attribution 4.0 International licence.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# APRA base URLs and dataset catalogue
# ---------------------------------------------------------------------------

APRA_BASE = "https://www.apra.gov.au"

# Known URL patterns for each dataset type.  APRA occasionally restructures
# these, so we try multiple path patterns and fall back gracefully.
DATASET_URL_PATTERNS = {
    "annual_fund_level": [
        "/sites/default/files/{year}-{month:02d}/Annual-fund-level-superannuation-statistics-{fy}.xlsx",
        "/sites/default/files/{year}-{month:02d}/Annual%20fund-level%20superannuation%20statistics%20{fy}.xlsx",
    ],
    "quarterly": [
        "/sites/default/files/{year}-{month:02d}/Quarterly-superannuation-statistics-{qtr}-{year}.xlsx",
        "/sites/default/files/{year}-{month:02d}/Quarterly%20superannuation%20statistics%20{qtr}%20{year}.xlsx",
    ],
    "mysuper_heatmap": [
        "/sites/default/files/{year}-{month:02d}/MySuper-product-heatmap-data-{year}.xlsx",
    ],
}

# Months in which APRA typically releases each dataset (try in order).
RELEASE_MONTHS = {
    "annual_fund_level": [3, 4, 2, 5],    # usually Feb–Apr
    "quarterly": [2, 3, 4, 5, 8, 11],     # ~2 months after quarter end
    "mysuper_heatmap": [8, 9, 7, 10],
}

# Financial year label format — APRA uses "2023-24" in filenames.
def _fy_label(year: int) -> str:
    """Return APRA financial-year label for a given end year, e.g. 2024 → '2023-24'."""
    return f"{year - 1}-{str(year)[-2:]}"

QUARTER_LABELS = {1: "March", 2: "June", 3: "September", 4: "December"}


@dataclass
class FetchResult:
    """A successfully fetched APRA file."""
    dataset: str
    local_path: Path
    source_url: str
    year: int
    quarter: Optional[int] = None
    file_size_bytes: int = 0
    sha256: str = ""
    from_cache: bool = False


class APRAFetcher:
    """
    Download and cache APRA superannuation disclosure Excel files.

    Parameters
    ----------
    cache_dir : str or Path
        Directory for cached downloads.  Created if it does not exist.
        Defaults to ``data/raw/apra`` relative to the current working directory.
    timeout : int
        Request timeout in seconds.
    retry_delay : float
        Seconds to wait between retry attempts.
    max_retries : int
        Number of download retries before giving up.
    user_agent : str
        HTTP User-Agent string sent to APRA.  Identify your project.
    """

    def __init__(
        self,
        cache_dir: str | Path = "data/raw/apra",
        timeout: int = 120,
        retry_delay: float = 3.0,
        max_retries: int = 3,
        user_agent: str = "superannuation-holdings/0.1 (github.com/alexbrownqld18-lab/superannuation-holdings)",
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.retry_delay = retry_delay
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, */*",
        })

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch(
        self,
        dataset: str,
        year: int,
        quarter: Optional[int] = None,
        force_refresh: bool = False,
    ) -> FetchResult:
        """
        Fetch a single APRA disclosure file.

        Parameters
        ----------
        dataset : str
            One of ``annual_fund_level``, ``quarterly``, ``mysuper_heatmap``.
        year : int
            Calendar year of the release (e.g. 2024 for the FY2023-24 annual data).
        quarter : int, optional
            1–4 for quarterly data.  Ignored for annual datasets.
        force_refresh : bool
            If True, re-download even if a cached copy exists.

        Returns
        -------
        FetchResult
        """
        if dataset not in DATASET_URL_PATTERNS:
            raise ValueError(f"Unknown dataset '{dataset}'. Valid: {list(DATASET_URL_PATTERNS)}")
        if dataset == "quarterly" and quarter not in (1, 2, 3, 4):
            raise ValueError("quarter must be 1–4 for quarterly dataset")

        cache_key = self._cache_filename(dataset, year, quarter)
        cached = self.cache_dir / cache_key

        if cached.exists() and not force_refresh:
            logger.info("Cache hit: %s", cached)
            return FetchResult(
                dataset=dataset,
                local_path=cached,
                source_url="(cached)",
                year=year,
                quarter=quarter,
                file_size_bytes=cached.stat().st_size,
                sha256=self._sha256(cached),
                from_cache=True,
            )

        url, result = self._try_download(dataset, year, quarter, cached)
        return result

    def available_years(self, dataset: str) -> list[int]:
        """
        Return a best-effort list of years for which APRA data is likely available.
        APRA annual data runs from approximately 2004.  Quarterly from 2004.
        """
        current_year = time.localtime().tm_year
        if dataset == "annual_fund_level":
            return list(range(2004, current_year))
        elif dataset == "quarterly":
            return list(range(2004, current_year))
        elif dataset == "mysuper_heatmap":
            return list(range(2019, current_year))
        return []

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _try_download(
        self, dataset: str, year: int, quarter: Optional[int], dest: Path
    ) -> tuple[str, FetchResult]:
        """Try each URL pattern and release month until one succeeds."""
        patterns = DATASET_URL_PATTERNS[dataset]
        months = RELEASE_MONTHS[dataset]
        errors = []

        for pattern in patterns:
            for month in months:
                url = self._build_url(pattern, dataset, year, month, quarter)
                try:
                    logger.debug("Trying: %s", url)
                    response = self._download_with_retry(url)
                    self._write_file(dest, response.content)
                    result = FetchResult(
                        dataset=dataset,
                        local_path=dest,
                        source_url=url,
                        year=year,
                        quarter=quarter,
                        file_size_bytes=dest.stat().st_size,
                        sha256=self._sha256(dest),
                        from_cache=False,
                    )
                    logger.info("Downloaded %s → %s (%d bytes)", url, dest, result.file_size_bytes)
                    return url, result
                except requests.HTTPError as e:
                    errors.append(f"{url}: {e}")
                    continue

        raise FileNotFoundError(
            f"Could not download {dataset} year={year} quarter={quarter}.\n"
            "Tried URLs:\n" + "\n".join(errors) + "\n\n"
            "APRA may not have released this period yet, or their URL format "
            "has changed.  Check https://www.apra.gov.au/superannuation-statistics"
        )

    def _build_url(
        self,
        pattern: str,
        dataset: str,
        year: int,
        month: int,
        quarter: Optional[int],
    ) -> str:
        fy = _fy_label(year)
        qtr = QUARTER_LABELS.get(quarter or 1, "")
        path = pattern.format(year=year, month=month, fy=fy, qtr=qtr)
        return urljoin(APRA_BASE, path)

    def _download_with_retry(self, url: str) -> requests.Response:
        last_error = None
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                resp.raise_for_status()
                return resp
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    raise  # URL does not exist; don't retry
                last_error = e
            except requests.RequestException as e:
                last_error = e
            if attempt < self.max_retries - 1:
                logger.warning("Attempt %d failed for %s: %s", attempt + 1, url, last_error)
                time.sleep(self.retry_delay * (attempt + 1))
        raise last_error  # type: ignore[misc]

    @staticmethod
    def _write_file(dest: Path, content: bytes) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _cache_filename(dataset: str, year: int, quarter: Optional[int]) -> str:
        if quarter:
            return f"{dataset}_{year}_Q{quarter}.xlsx"
        return f"{dataset}_{year}.xlsx"
