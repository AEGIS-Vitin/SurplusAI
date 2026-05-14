"""Tipos de cambio. Por defecto valores cacheados; permite override."""
from __future__ import annotations

DEFAULT_RATES_TO_EUR = {
    "EUR": 1.0,
    "USD": 0.92,
    "AED": 0.25,
    "GBP": 1.17,
    "JPY": 0.0061,
    "CHF": 1.04,
}


def to_eur(amount: float, currency: str, override: float | None = None) -> float:
    if override is not None:
        return amount * override
    rate = DEFAULT_RATES_TO_EUR.get(currency.upper())
    if rate is None:
        raise ValueError(f"Unknown currency {currency}")
    return amount * rate
