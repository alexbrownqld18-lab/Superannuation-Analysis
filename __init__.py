"""
apra-client — fetch and normalise APRA superannuation disclosure data.

Quick start
-----------
    from apra_client import APRAClient

    client = APRAClient()
    df = client.fetch("annual_fund_level", year=2024)
    print(df.head())

Data source
-----------
All data returned by this library is published by the Australian Prudential
Regulation Authority (APRA) under the Creative Commons Attribution 4.0
International licence.  Attribution: Australian Prudential Regulation Authority.
"""

from .client import APRAClient
from .datasets import list_datasets, get_spec

__all__ = ["APRAClient", "list_datasets", "get_spec"]

__version__ = "0.1.0"
__author__ = "Auchenflower Capital"
__license__ = "MIT"
