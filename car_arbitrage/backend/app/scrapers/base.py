"""Base scraper: fetch educado, parsing común, rate-limit, cache simple.

AVISO: hacer scraping de portales puede violar sus ToS. El usuario es
responsable de cumplir robots.txt y los términos de servicio. Este código
incluye rate-limit y backoff por defecto y NO se usa en CI.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
)


@dataclass
class Listing:
    source: str
    url: str
    make: str
    model: str
    version: Optional[str]
    year: Optional[int]
    km: Optional[int]
    price_eur: Optional[float]
    fuel: Optional[str]
    transmission: Optional[str]
    location: Optional[str]
    raw: dict = field(default_factory=dict)


class BaseScraper:
    name: str = "base"
    base_url: str = ""
    rate_limit_seconds: float = 3.0

    def __init__(self, timeout: float = 20.0, cookies: Optional[dict] = None):
        self._client = httpx.AsyncClient(
            headers={"User-Agent": DEFAULT_UA, "Accept-Language": "es-ES,en;q=0.8"},
            timeout=timeout,
            cookies=cookies or {},
            follow_redirects=True,
        )
        self._last_call = 0.0

    async def _throttle(self):
        elapsed = time.time() - self._last_call
        if elapsed < self.rate_limit_seconds:
            await asyncio.sleep(self.rate_limit_seconds - elapsed)
        self._last_call = time.time()

    async def fetch(self, url: str, **kwargs) -> httpx.Response:
        await self._throttle()
        for attempt in range(4):
            try:
                resp = await self._client.get(url, **kwargs)
                if resp.status_code == 429:
                    await asyncio.sleep(2 ** attempt * 5)
                    continue
                resp.raise_for_status()
                return resp
            except httpx.HTTPError:
                if attempt == 3:
                    raise
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError("unreachable")

    async def close(self):
        await self._client.aclose()

    async def search(self, query: dict) -> list[Listing]:
        raise NotImplementedError
