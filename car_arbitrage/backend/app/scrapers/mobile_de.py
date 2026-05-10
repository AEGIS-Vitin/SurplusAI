"""mobile.de — Alemania. Para uso comparable.

Selectores aproximados; mobile.de cambia con frecuencia. Si hay endpoint
API privado mejor usar httpx con headers correctos. Este scraper devuelve
best-effort sobre la página HTML.
"""
from __future__ import annotations

import re
from typing import Optional

from selectolax.parser import HTMLParser

from app.scrapers.base import BaseScraper, Listing


class MobileDeScraper(BaseScraper):
    name = "mobile.de"
    base_url = "https://www.mobile.de"

    async def search(self, query: dict) -> list[Listing]:
        make = query.get("make", "")
        model = query.get("model", "")
        params = {
            "isSearchRequest": "true",
            "makeModelVariant1.makeId": make,
            "makeModelVariant1.modelDescription": model,
        }
        if query.get("year_from"):
            params["minFirstRegistrationDate"] = f"{query['year_from']}-01-01"
        if query.get("year_to"):
            params["maxFirstRegistrationDate"] = f"{query['year_to']}-12-31"
        if query.get("km_max"):
            params["maxMileage"] = query["km_max"]

        url = self.base_url + "/fahrzeuge/search.html"
        try:
            resp = await self.fetch(url, params=params)
        except Exception as e:
            return [Listing(
                source=self.name, url=url, make=make, model=model, version=None,
                year=None, km=None, price_eur=None, fuel=None, transmission=None,
                location=None, raw={"error": str(e)},
            )]

        return self._parse(resp.text, query)

    def _parse(self, html: str, query: dict) -> list[Listing]:
        tree = HTMLParser(html)
        results: list[Listing] = []
        for card in tree.css("[data-testid='result-item'], article, div.cBox-body--vehicleListing"):
            title_node = card.css_first("h3, [data-testid*='title']")
            price_node = card.css_first("[data-testid*='price'], .h3")
            if not title_node or not price_node:
                continue
            title = title_node.text(strip=True)
            price = self._parse_price_eur(price_node.text(strip=True))
            text_blob = card.text()
            year = self._extract_year(text_blob)
            km = self._extract_km(text_blob)
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
                year=year,
                km=km,
                price_eur=price,
                fuel=self._extract_fuel(text_blob),
                transmission=self._extract_transmission(text_blob),
                location="DE",
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
        m = re.search(r"\bEZ\s*(\d{2})/(\d{4})", text) or re.search(r"\b(20[0-3]\d)\b", text)
        if m:
            try:
                return int(m.group(2)) if m.lastindex and m.lastindex >= 2 else int(m.group(1))
            except (ValueError, IndexError):
                return None
        return None

    @staticmethod
    def _extract_km(text: str) -> Optional[int]:
        m = re.search(r"([\d\.\s]+)\s*km", text)
        if not m:
            return None
        try:
            return int(re.sub(r"[^\d]", "", m.group(1)))
        except ValueError:
            return None

    @staticmethod
    def _extract_fuel(text: str) -> Optional[str]:
        t = text.lower()
        for token, val in (
            ("benzin", "gasoline"), ("diesel", "diesel"), ("elektro", "bev"),
            ("hybrid", "hev"), ("erdgas", "cng"), ("autogas", "lpg"),
        ):
            if token in t:
                return val
        return None

    @staticmethod
    def _extract_transmission(text: str) -> Optional[str]:
        t = text.lower()
        if "automatik" in t:
            return "automatic"
        if "schaltgetriebe" in t or "manuell" in t:
            return "manual"
        return None
