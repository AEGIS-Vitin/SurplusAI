"""Transporte: tablas medias por origen → España península."""
from __future__ import annotations

from dataclasses import dataclass

EU_TRUCK_TABLE = {
    "DE": (600, 900),
    "FR": (400, 650),
    "IT": (500, 800),
    "NL": (700, 950),
    "BE": (700, 950),
    "PL": (850, 1100),
    "AT": (700, 950),
    "PT": (250, 400),
    "SE": (1100, 1500),
    "DK": (900, 1200),
    "CZ": (800, 1050),
    "CH": (700, 950),
}

EXTRA_EU_SHIPPING = {
    "AE": {"roro_usd": (1500, 2500), "container_usd": (3000, 4500), "transit_days": (18, 28)},
    "JP": {"roro_usd": (1800, 2800), "container_usd": (3500, 5500), "transit_days": (35, 50)},
    "US": {"roro_usd": (1300, 2200), "container_usd": (2800, 4200), "transit_days": (18, 30)},
    "GB": {"roro_usd": (500, 800), "container_usd": (1500, 2400), "transit_days": (3, 7)},
}

PORT_FEES_DESTINATION = (350, 600)


@dataclass
class TransportEstimate:
    mode: str
    cost_eur: float
    transit_days: float
    notes: list[str]


def estimate_eu_truck(origin_iso: str, mode: str = "mid") -> TransportEstimate:
    if origin_iso not in EU_TRUCK_TABLE:
        rng = (700, 950)
        notes = [f"Origen {origin_iso} no en tabla, usando media UE."]
    else:
        rng = EU_TRUCK_TABLE[origin_iso]
        notes = []
    cost = {"low": rng[0], "mid": (rng[0] + rng[1]) / 2, "high": rng[1]}[mode]
    return TransportEstimate(
        mode=f"camión porta-coches {mode}",
        cost_eur=cost,
        transit_days=4,
        notes=notes,
    )


def estimate_extra_eu(
    origin_iso: str,
    container: bool = False,
    fx_usd_eur: float = 0.92,
    insurance_pct_value: float = 0.015,
    declared_value_eur: float = 0.0,
    mode: str = "mid",
) -> TransportEstimate:
    cfg = EXTRA_EU_SHIPPING.get(origin_iso)
    if cfg is None:
        return TransportEstimate(
            mode="extra-UE (sin datos)",
            cost_eur=2500,
            transit_days=25,
            notes=[f"Origen {origin_iso} no parametrizado, estimación genérica."],
        )
    key = "container_usd" if container else "roro_usd"
    rng_usd = cfg[key]
    pick_usd = {"low": rng_usd[0], "mid": (rng_usd[0] + rng_usd[1]) / 2, "high": rng_usd[1]}[mode]
    shipping_eur = pick_usd * fx_usd_eur
    insurance_eur = declared_value_eur * insurance_pct_value
    port_fees = (PORT_FEES_DESTINATION[0] + PORT_FEES_DESTINATION[1]) / 2
    total = shipping_eur + insurance_eur + port_fees
    transit = (cfg["transit_days"][0] + cfg["transit_days"][1]) / 2
    notes = [
        f"Modo: {'contenedor' if container else 'RoRo'}, USD {pick_usd:,.0f} × {fx_usd_eur:.3f}",
        f"Seguro tránsito {insurance_pct_value*100:.1f}% sobre {declared_value_eur:,.0f} €: {insurance_eur:,.0f} €",
        f"Tasas portuarias destino + THC: {port_fees:,.0f} €",
    ]
    return TransportEstimate(
        mode="contenedor" if container else "RoRo",
        cost_eur=total,
        transit_days=transit,
        notes=notes,
    )
