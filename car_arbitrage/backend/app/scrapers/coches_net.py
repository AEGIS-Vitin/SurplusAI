"""coches.net — España. Para precio de venta esperado."""
from __future__ import annotations
import re
from typing import Optional

from selectolax.parser import HTMLParser

from app.scrapers.base import BaseScraper, Listing


class CochesNetScraper(BaseScraper):
    name = "coches.net"
    base_url = "https://www.coches.net"

    async def search(self, query: dict) -> list[Listing]:
        make = query.get("make", "").lower().replace(" ", "-")
        model = query.get("model", "").lower().replace(" ", "-")
        path = f"/{make}-{model}/segundamano/" if make and model else "/segundamano/"
        url = self.base_url + path
        params = {}
        if query.get("year_from"):
            params["YearFrom"] = query["year_from"]
        if query.get("km_max"):
            params["KmTo"] = query["km_max"]

        try:
            resp = await self.fetch(url, params=params)
        except Exception as e:
            return [Listing(
                source=self.name, url=url, make=make, model=model, version=None,
                year=None, km=None, price_eur=None, fuel=None, transmission=None,
                location="ES", raw={"error": str(e)},
            )]
        return self._parse(resp.text, query)

    def _parse(self, html: str, query: dict) -> list[Listing]:
        tree = HTMLParser(html)
        results: list[Listing] = []
        for card in tree.css("article, div.mt-CardAd, [data-test='ad-card']"):
            title_node = card.css_first("h3, h2, .mt-CardAd-titleText")
            price_node = card.css_first("[class*='price'], strong, .mt-CardAd-price")
            if not title_node or not price_node:
                continue
            title = title_node.text(strip=True)
            price = self._parse_price_eur(price_node.text(strip=True))
            blob = card.text()
            year = self._extract_year(blob)
            km = self._extract_km(blob)
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
                fuel=None,
                transmission=None,
                location="ES",
                raw={"title": title},
            ))
        return results

    @staticmethod
    def _parse_price_eur(text: str) -> Optional[float]:
        digits = re.sub(r"[^\d]", "", text)
        if not digits:
            return None
        try:
            return float(digits)
        except ValueError:
            return None

    @staticmethod
    def _extract_year(text: str) -> Optional[int]:
        m = re.search(r"\b(19[8-9]\d|20[0-3]\d)\b", text)
        return int(m.group(1)) if m else None

    @staticmethod
    def _extract_km(text: str) -> Optional[int]:
        m = re.search(r"([\d\.]+)\s*km", text, re.I)
        if not m:
            return None
        try:
            return int(re.sub(r"[^\d]", "", m.group(1)))
        except ValueError:
            return None
