"""Rotación teórica por segmento/marca: días estimados hasta vender.

Tabla de rotación media (días) basada en patrones reales del mercado
español de segunda mano. Distribución LogNormal con sigma del 0.4 sobre
el log de la mediana — captura cola larga (algunos coches venden lentos).

Velocity score: 1 = muy rápido (<25 días), 5 = muy lento (>90 días).
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np

from app.models.vehicle import FuelType, Vehicle


SEGMENT_DAYS = {
    "premium_german": 35,        # BMW/Mercedes/Audi <50k €
    "premium_german_high": 55,   # premium >50k € (M, AMG, RS)
    "premium_other": 45,         # Volvo, Lexus, Jaguar, Land Rover
    "exotic": 90,                # Porsche, Maserati, Ferrari, Lambo, Aston
    "suv_large": 50,             # X5/Q7/GLE/Cayenne y rivales
    "suv_compact": 30,           # Tiguan, Tucson, CR-V, Ateca
    "compact_mainstream": 25,    # Golf, Focus, Astra, Mégane, Civic
    "sedan_mainstream": 35,      # Octavia, Insignia, Passat, A4
    "city": 22,                  # Polo, Ibiza, Yaris, Corsa
    "ev_premium": 50,            # Tesla, EQE, ID, e-tron
    "ev_compact": 45,            # ID.3, MG4, Born, Megane E-Tech
    "phev": 55,                  # más lento por desconfianza batería
    "mpv_van": 45,               # Sharan, Galaxy, V-class
    "pickup": 40,                # Hilux, Ranger, L200
    "youngtimer": 75,            # 15-25 años pero deseable
    "classic": 120,              # >25 años, mercado de coleccionista
}

PREMIUM_GERMAN = {"bmw", "mercedes", "mercedes-benz", "audi"}
PREMIUM_OTHER = {"volvo", "lexus", "jaguar", "land rover", "range rover", "infiniti", "acura", "genesis"}
EXOTIC = {"porsche", "maserati", "ferrari", "lamborghini", "aston martin", "bentley", "rolls-royce", "mclaren"}
PICKUP = {"hilux", "ranger", "l200", "amarok", "navara", "d-max", "frontier"}
SUV_LARGE_HINTS = {"x5", "x6", "x7", "q7", "q8", "gle", "gls", "cayenne", "rx", "lx",
                   "land cruiser", "patrol", "range rover", "discovery", "touareg"}
SUV_COMPACT_HINTS = {"tiguan", "tucson", "sportage", "qashqai", "kuga", "cr-v", "rav4",
                     "ateca", "kadjar", "captur", "hr-v", "yaris cross", "x1", "x3", "q3", "q5"}
CITY_HINTS = {"polo", "ibiza", "yaris", "corsa", "208", "clio", "fiesta", "i10", "i20",
              "fabia", "panda", "up!", "fox", "twingo", "aygo", "c1", "108"}
COMPACT_HINTS = {"golf", "focus", "astra", "megane", "civic", "leon", "i30", "mazda3",
                 "auris", "corolla", "308", "1 series", "a3", "a-class"}


def _has_any(text: str, words: set) -> bool:
    t = text.lower()
    return any(w in t for w in words)


def classify_segment(v: Vehicle) -> str:
    make = v.make.lower().strip()
    model_full = f"{v.model} {v.version or ''}".lower()

    # Histórico/youngtimer
    if v.age_years >= 25:
        return "classic"
    if v.age_years >= 15:
        return "youngtimer"

    # EV / PHEV
    if v.fuel == FuelType.BEV:
        return "ev_premium" if make in PREMIUM_GERMAN | PREMIUM_OTHER | EXOTIC | {"tesla"} else "ev_compact"
    if v.fuel == FuelType.PHEV:
        return "phev"

    # Exotic
    if make in EXOTIC:
        return "exotic"

    # Pickup
    if _has_any(model_full, PICKUP):
        return "pickup"

    # SUVs
    if _has_any(model_full, SUV_LARGE_HINTS):
        return "suv_large"
    if _has_any(model_full, SUV_COMPACT_HINTS):
        return "suv_compact"

    # Premium
    if make in PREMIUM_GERMAN:
        # M/AMG/RS/S badges → high
        if any(b in model_full for b in [" m3", " m4", " m5", " m8", "amg", " rs", " s3", " s4", " s5", " s6", " s8"]):
            return "premium_german_high"
        return "premium_german"
    if make in PREMIUM_OTHER:
        return "premium_other"

    # City vs compact vs sedan
    if _has_any(model_full, CITY_HINTS):
        return "city"
    if _has_any(model_full, COMPACT_HINTS):
        return "compact_mainstream"
    return "sedan_mainstream"


@dataclass
class RotationEstimate:
    segment: str
    median_days: float
    mean_days: float
    p25_days: float
    p75_days: float
    p90_days: float
    velocity_score: int   # 1..5
    velocity_label: str
    prob_sell_within_30d: float
    prob_sell_within_60d: float
    prob_sell_within_90d: float
    notes: list[str]


def _velocity(median_days: float) -> tuple[int, str]:
    if median_days <= 25:
        return 1, "Muy rápida"
    if median_days <= 35:
        return 2, "Rápida"
    if median_days <= 50:
        return 3, "Normal"
    if median_days <= 75:
        return 4, "Lenta"
    return 5, "Muy lenta"


def estimate_rotation(v: Vehicle, sigma: float = 0.4, override_days: float | None = None) -> RotationEstimate:
    segment = classify_segment(v)
    median = override_days if override_days is not None else SEGMENT_DAYS[segment]
    mu = np.log(median)

    rng = np.random.default_rng(7)
    samples = rng.lognormal(mean=mu, sigma=sigma, size=20000)

    p25, p50, p75, p90 = np.percentile(samples, [25, 50, 75, 90])
    score, label = _velocity(float(p50))

    notes = [f"Segmento detectado: {segment} (mediana {median} días)."]
    if v.km > 200_000:
        notes.append("Km muy alto: rotación posiblemente más lenta de lo estimado.")
    if v.previous_owners and v.previous_owners >= 4:
        notes.append("Muchos propietarios: castigar -10% velocidad estimada.")

    return RotationEstimate(
        segment=segment,
        median_days=float(p50),
        mean_days=float(samples.mean()),
        p25_days=float(p25),
        p75_days=float(p75),
        p90_days=float(p90),
        velocity_score=score,
        velocity_label=label,
        prob_sell_within_30d=float((samples <= 30).mean()),
        prob_sell_within_60d=float((samples <= 60).mean()),
        prob_sell_within_90d=float((samples <= 90).mean()),
        notes=notes,
    )
