"""autoscout24 (.es y .de). Mismo motor, dos dominios."""
from __future__ import annotations

import re
from typing import Optional

from selectolax.parser import HTMLParser

from app.scrapers.base import BaseScraper, Listing


class AutoScout24Scraper(BaseScraper):
    name = "autoscout24"

    def __init__(self, country: str = "es", **kw):
        self.country = country.lower()
        self.base_url = f"https://www.autoscout24.{self.country}"
        self.market = country.upper()
        super().__init__(**kw)

    async def search(self, query: dict) -> list[Listing]:
        make = query.get("make", "").lower().replace(" ", "-")
        model = query.get("model", "").lower().replace(" ", "-")
        path = f"/lst/{make}/{model}" if make and model else "/lst"
        params = {"sort": "standard", "desc": "0"}
        if query.get("year_from"):
            params["fregfrom"] = query["year_from"]
        if query.get("km_max"):
            params["kmto"] = query["km_max"]
        url = self.base_url + path
        try:
            resp = await self.fetch(url, params=params)
        except Exception as e:
            return [Listing(
                source=self.name + "." + self.country, url=url, make=make, model=model,
                version=None, year=None, km=None, price_eur=None, fuel=None,
                transmission=None, location=self.market, raw={"error": str(e)},
            )]
        return self._parse(resp.text, query)

    def _parse(self, html: str, query: dict) -> list[Listing]:
        tree = HTMLParser(html)
        results: list[Listing] = []
        for card in tree.css("article, [data-testid='listing-summary']"):
            title_node = card.css_first("h2, h3, [class*='title']")
            price_node = card.css_first("[class*='price'], [data-testid*='regular-price']")
            if not title_node or not price_node:
                continue
            title = title_node.text(strip=True)
            price = self._parse_price_eur(price_node.text(strip=True))
            blob = card.text()
            href = card.css_first("a")
            link = (href.attributes.get("href") if href else "") or ""
            if link and not link.startswith("http"):
                link = self.base_url + link
            results.append(Listing(
                source=f"autoscout24.{self.country}",
                url=link,
                make=query.get("make", ""),
                model=query.get("model", ""),
                version=title,
                year=self._extract_year(blob),
                km=self._extract_km(blob),
                price_eur=price,
                fuel=None,
                transmission=None,
                location=self.market,
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
        m = re.search(r"\b(19[8-9]\d|20[0-3]\d)\b", text)
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
