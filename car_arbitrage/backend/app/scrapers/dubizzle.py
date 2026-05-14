"""Dubizzle Motors (UAE). Listings públicos sin login.

Nota: Dubizzle se rebrandeó como dubizzle.com / dubicars en EAU. La estructura
HTML cambia con frecuencia. Este scraper apunta a la web pública y devuelve
listings con precio en AED → conversión a EUR vía core.fx.
"""
from __future__ import annotations

import re
from typing import Optional

from selectolax.parser import HTMLParser

from app.core import fx
from app.scrapers.base import BaseScraper, Listing


class DubizzleScraper(BaseScraper):
    name = "dubizzle"
    base_url = "https://www.dubizzle.com"

    async def search(self, query: dict) -> list[Listing]:
        make = query.get("make", "").lower().replace(" ", "-")
        model = query.get("model", "").lower().replace(" ", "-")
        path = f"/motors/used-cars/{make}/{model}/" if make and model else "/motors/used-cars/"
        url = self.base_url + path

        try:
            resp = await self.fetch(url)
        except Exception as e:
            return [Listing(
                source=self.name, url=url, make=query.get("make", ""),
                model=query.get("model", ""), version=None, year=None,
                km=None, price_eur=None, fuel=None, transmission=None,
                location=None, raw={"error": str(e)},
            )]

        return self._parse_list_page(resp.text, url, query)

    def _parse_list_page(self, html: str, url: str, query: dict) -> list[Listing]:
        tree = HTMLParser(html)
        results: list[Listing] = []
        for card in tree.css("article, li[data-testid*='listing'], div[class*='listing']"):
            title_node = card.css_first("h2, h3, a[title]")
            price_node = card.css_first("[class*='price'], [data-testid*='price']")
            if not title_node or not price_node:
                continue
            title = title_node.text(strip=True)
            price_aed = self._parse_price_aed(price_node.text(strip=True))
            year = self._extract_year(title)
            km = self._extract_km(card.text())
            href = card.css_first("a")
            link = (href.attributes.get("href") if href else "") or ""
            if link and not link.startswith("http"):
                link = self.base_url + link

            results.append(Listing(
                source=self.name,
                url=link or url,
                make=query.get("make", ""),
                model=query.get("model", ""),
                version=title,
                year=year,
                km=km,
                price_eur=fx.to_eur(price_aed, "AED") if price_aed else None,
                fuel=None,
                transmission=None,
                location="UAE",
                raw={"title": title, "price_aed": price_aed},
            ))
        return results

    @staticmethod
    def _parse_price_aed(text: str) -> Optional[float]:
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
        m = re.search(r"([\d,\.]+)\s*(km|kilo)", text, re.I)
        if not m:
            return None
        try:
            return int(re.sub(r"[^\d]", "", m.group(1)))
        except ValueError:
            return None
