"""Pricer: estadísticas y regresión robusta sobre comparables.

Devuelve P25/P50/P75, std, y un precio justo ajustado al km y año del coche
objetivo mediante regresión Huber sobre los comparables del mercado dado.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from sklearn.linear_model import HuberRegressor

from app.models.vehicle import Comparable, Vehicle


@dataclass
class MarketStats:
    market: str
    n: int
    p25: float
    p50: float
    p75: float
    mean: float
    std: float
    fair_price: float
    notes: list[str]


def _filter(comps: Sequence[Comparable], market: str) -> list[Comparable]:
    return [
        c for c in comps
        if c.market == market and not c.accident and c.price_eur > 0 and c.km >= 0
    ]


def market_stats(
    comps: Sequence[Comparable],
    target: Vehicle,
    market: str,
    min_n: int = 5,
) -> MarketStats | None:
    sample = _filter(comps, market)
    notes: list[str] = []
    if len(sample) < min_n:
        return None
    prices = np.array([c.price_eur for c in sample], dtype=float)
    kms = np.array([c.km for c in sample], dtype=float)
    years = np.array([c.year for c in sample], dtype=float)

    p25, p50, p75 = np.percentile(prices, [25, 50, 75])

    fair = float(p50)
    if len(sample) >= 8:
        try:
            X = np.column_stack([kms, years])
            model = HuberRegressor(max_iter=200).fit(X, prices)
            fair = float(model.predict(np.array([[target.km, target.year]]))[0])
            fair = float(np.clip(fair, p25 * 0.85, p75 * 1.15))
            notes.append("Fair price ajustado por regresión Huber (km, año).")
        except Exception as e:
            notes.append(f"Regresión falló, fair=P50: {e}")
    else:
        notes.append("n<8: fair price = mediana sin regresión.")

    return MarketStats(
        market=market,
        n=len(sample),
        p25=float(p25),
        p50=float(p50),
        p75=float(p75),
        mean=float(prices.mean()),
        std=float(prices.std()),
        fair_price=fair,
        notes=notes,
    )
