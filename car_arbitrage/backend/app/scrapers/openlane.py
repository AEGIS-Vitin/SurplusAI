"""OpenLane B2B — REQUIERE login. El usuario aporta cookies de sesión vía
variable de entorno OPENLANE_COOKIE (formato 'k1=v1; k2=v2; ...').

ATENCIÓN: el ToS de OpenLane puede prohibir scraping automatizado. Uso
exclusivo del comprador autenticado, bajo su responsabilidad.
"""
from __future__ import annotations

import os
import re
from typing import Optional

from selectolax.parser import HTMLParser

from app.scrapers.base import BaseScraper, Listing


def _parse_cookie_string(s: str) -> dict:
    cookies = {}
    for part in s.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


class OpenLaneScraper(BaseScraper):
    name = "openlane"
    base_url = "https://www.openlane.eu"
    rate_limit_seconds = 4.0

    def __init__(self, cookie_string: Optional[str] = None, **kw):
        cookie_string = cookie_string or os.environ.get("OPENLANE_COOKIE", "")
        cookies = _parse_cookie_string(cookie_string) if cookie_string else None
        super().__init__(cookies=cookies, **kw)
        self._authenticated = bool(cookies)

    async def search(self, query: dict) -> list[Listing]:
        if not self._authenticated:
            return [Listing(
                source=self.name, url=self.base_url, make=query.get("make", ""),
                model=query.get("model", ""), version=None, year=None, km=None,
                price_eur=None, fuel=None, transmission=None, location="EU",
                raw={"error": "OPENLANE_COOKIE no configurada. Inicia sesión y exporta cookies."},
            )]

        url = f"{self.base_url}/en/buyers/cars/search"
        params = {
            "make": query.get("make", ""),
            "model": query.get("model", ""),
        }
        try:
            resp = await self.fetch(url, params=params)
        except Exception as e:
            return [Listing(
                source=self.name, url=url, make=query.get("make", ""),
                model=query.get("model", ""), version=None, year=None, km=None,
                price_eur=None, fuel=None, transmission=None, location="EU",
                raw={"error": str(e)},
            )]
        return self._parse(resp.text, query)

    def _parse(self, html: str, query: dict) -> list[Listing]:
        tree = HTMLParser(html)
        results: list[Listing] = []
        for card in tree.css("[class*='vehicle-card'], article.vehicle, li.lot-item"):
            title_node = card.css_first("h3, h2, .vehicle-title")
            price_node = card.css_first("[class*='price'], [class*='bid']")
            if not title_node:
                continue
            title = title_node.text(strip=True)
            price = self._parse_price_eur(price_node.text(strip=True)) if price_node else None
            blob = card.text()
            href = card.css_first("a")
            link = (href.attributes.get("href") if href else "") or ""
            if link and not link.startswith("http"):
                link = self.base_url + link
            results.append(Listing(
                source=self.name,
                url=link,
                make=query.get("make", ""),
                model=query.get("model", ""),
                version=title,
                year=self._extract_year(blob),
                km=self._extract_km(blob),
                price_eur=price,
                fuel=None,
                transmission=None,
                location=self._extract_country(blob),
                raw={"title": title},
            ))
        return results

    @staticmethod
    def _parse_price_eur(text: str) -> Optional[float]:
        digits = re.sub(r"[^\d]", "", text.split(",")[0])
        if not digits:
            return None
        try:
            return float(digits)
        except ValueError:
            return None

    @staticmethod
    def _extract_year(text: str) -> Optional[int]:
        m = re.search(r"\b(20[0-3]\d)\b", text)
        return int(m.group(1)) if m else None

    @staticmethod
    def _extract_km(text: str) -> Optional[int]:
        m = re.search(r"([\d\.\s,]+)\s*km", text, re.I)
        if not m:
            return None
        try:
            return int(re.sub(r"[^\d]", "", m.group(1)))
        except ValueError:
            return None

    @staticmethod
    def _extract_country(text: str) -> Optional[str]:
        m = re.search(r"\b(DE|FR|IT|NL|BE|ES|PT|PL|AT|CZ|SE|DK)\b", text)
        return m.group(1) if m else None
