"""IEDMT — Impuesto Especial sobre Determinados Medios de Transporte (España).

Base = valor fiscal Hacienda × coeficiente de depreciación por antigüedad.
Tipo según emisiones CO2 WLTP. BEV exento (0%). Canarias tipos reducidos.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.models.vehicle import FuelType, Vehicle

DEPRECIATION_TABLE = [
    (1, 1.00),
    (2, 0.84),
    (3, 0.67),
    (4, 0.56),
    (5, 0.47),
    (6, 0.39),
    (7, 0.34),
    (8, 0.28),
    (9, 0.24),
    (10, 0.19),
    (11, 0.17),
    (12, 0.13),
]
DEPRECIATION_FLOOR = 0.10


def depreciation_coef(age_years: int) -> float:
    for cap, coef in DEPRECIATION_TABLE:
        if age_years < cap:
            return coef
    return DEPRECIATION_FLOOR


def iedmt_rate(co2_g_km: Optional[float], canary: bool = False) -> float:
    """Tipo IEDMT según CO2 WLTP. None → asume tramo más alto (penaliza)."""
    if co2_g_km is None:
        co2_g_km = 200.0
    if canary:
        if co2_g_km < 120:
            return 0.0
        if co2_g_km < 160:
            return 0.0375
        if co2_g_km < 200:
            return 0.0875
        return 0.1375
    if co2_g_km < 120:
        return 0.0
    if co2_g_km < 160:
        return 0.0475
    if co2_g_km < 200:
        return 0.0975
    return 0.1475


@dataclass
class IEDMTResult:
    rate: float
    base_eur: float
    tax_eur: float
    exemption_reason: Optional[str] = None
    notes: list[str] = None


def compute_iedmt(
    vehicle: Vehicle,
    fiscal_value_new_eur: float,
    canary: bool = False,
    historic_vehicle: bool = False,
    large_family_bonus: bool = False,
    disability_exempt: bool = False,
    ceuta_melilla: bool = False,
) -> IEDMTResult:
    notes: list[str] = []

    if ceuta_melilla:
        return IEDMTResult(0.0, 0.0, 0.0, "Ceuta/Melilla exento", notes)
    if disability_exempt:
        return IEDMTResult(0.0, 0.0, 0.0, "Discapacidad ≥33% (modelo 06)", notes)
    if historic_vehicle and vehicle.age_years >= 30:
        return IEDMTResult(0.0, 0.0, 0.0, "Vehículo histórico >30 años", notes)
    if vehicle.fuel == FuelType.BEV:
        return IEDMTResult(0.0, 0.0, 0.0, "Vehículo eléctrico (BEV) tipo 0%", notes)

    co2 = vehicle.co2_effective
    if co2 is None:
        notes.append("Sin CO2 WLTP/NEDC: se asume 200 g/km (tipo máximo).")
    rate = iedmt_rate(co2, canary=canary)

    coef = depreciation_coef(vehicle.age_years)
    base = fiscal_value_new_eur * coef
    notes.append(f"Coef depreciación {vehicle.age_years} años: {coef:.2f}")

    tax = base * rate
    if large_family_bonus:
        tax *= 0.5
        notes.append("Bonificación 50% familia numerosa aplicada.")

    return IEDMTResult(rate=rate, base_eur=base, tax_eur=tax, notes=notes)
