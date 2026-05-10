"""Estimador de coste de reacondicionado por km, edad, segmento."""
from __future__ import annotations
from dataclasses import dataclass

from app.models.vehicle import FuelType, Vehicle


@dataclass
class ReconditioningEstimate:
    total_eur: float
    breakdown: dict
    notes: list[str]


def estimate_reconditioning(
    vehicle: Vehicle,
    is_premium: bool = False,
    cosmetic_state: str = "average",
) -> ReconditioningEstimate:
    notes: list[str] = []
    breakdown: dict = {}

    km = vehicle.km
    if km < 60_000:
        mech = 220.0
    elif km < 120_000:
        mech = 600.0
    else:
        mech = 1300.0
    if is_premium and km > 100_000:
        mech += 1000
        notes.append("Premium >100k: provisión cadenas/EGR/turbos.")
    breakdown["mecanica_preventiva"] = mech

    if vehicle.fuel == FuelType.DIESEL and km > 150_000:
        breakdown["dpf_adblue_provision"] = 800.0
        notes.append("Diesel >150k: provisión DPF/AdBlue.")

    if vehicle.fuel in (FuelType.HEV, FuelType.PHEV):
        breakdown["test_bateria_traccion"] = 100.0
        notes.append("Híbrido/PHEV: test SoH batería tracción.")

    breakdown["neumaticos"] = 450.0 if vehicle.age_years > 4 else 0.0
    breakdown["frenos"] = 320.0
    breakdown["distribucion"] = 600.0 if km > 110_000 else 0.0

    if cosmetic_state == "good":
        breakdown["estetica"] = 200.0
    elif cosmetic_state == "average":
        breakdown["estetica"] = 500.0
    else:
        breakdown["estetica"] = 950.0

    breakdown["documentacion_llaves"] = 80.0

    subtotal = sum(breakdown.values())
    buffer = subtotal * 0.15
    breakdown["buffer_imprevistos_15pct"] = buffer

    return ReconditioningEstimate(
        total_eur=subtotal + buffer,
        breakdown=breakdown,
        notes=notes,
    )
