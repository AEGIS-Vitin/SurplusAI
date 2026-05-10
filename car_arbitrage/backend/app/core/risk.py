"""Risk score combinado (0-100) con desglose por factor."""
from __future__ import annotations

from dataclasses import dataclass

from app.models.vehicle import Origin, Vehicle


@dataclass
class RiskScore:
    score: int                 # 0 = sin riesgo, 100 = máximo riesgo
    label: str                 # "Bajo" / "Medio" / "Alto" / "Crítico"
    factors: dict[str, int]
    notes: list[str]


def compute_risk(v: Vehicle, origin: Origin, expected_days: float, has_market_sample: bool) -> RiskScore:
    factors: dict[str, int] = {}
    notes: list[str] = []

    # Homologación: extra-UE alto, UE sin COC medio
    if origin == Origin.EXTRA_EU:
        factors["homologation"] = 25
        notes.append("Origen extra-UE: requiere homologación individual; verificar Euro 6d.")
    elif not v.has_coc:
        factors["homologation"] = 8
    else:
        factors["homologation"] = 0

    # Rollback: km bajo y edad alta
    if v.km < 30_000 and v.age_years > 5:
        factors["mileage_rollback"] = 20
        notes.append("Km muy bajo para edad: alta sospecha de rollback. Pedir CarVertical/Autodna.")
    elif v.km < 50_000 and v.age_years > 7:
        factors["mileage_rollback"] = 10
    else:
        factors["mileage_rollback"] = 0

    # Daños
    dd = (v.declared_damages or "").lower()
    if "estructur" in dd:
        factors["structural_damage"] = 35
        notes.append("Daño estructural declarado: prácticamente invendible o gran descuento.")
    elif "siniestr" in dd or "accident" in dd:
        factors["structural_damage"] = 18
    elif dd and "cosmétic" not in dd and "sin" not in dd:
        factors["structural_damage"] = 6
    else:
        factors["structural_damage"] = 0

    # Propietarios
    po = v.previous_owners or 0
    if po >= 5:
        factors["many_owners"] = 12
    elif po >= 4:
        factors["many_owners"] = 6
    else:
        factors["many_owners"] = 0

    # Sin libro mantenimiento
    factors["no_service_book"] = 0 if v.has_service_book else 8

    # Liquidez (días estimados)
    if expected_days >= 90:
        factors["low_liquidity"] = 12
        notes.append("Modelo poco líquido (>90 días): cuidado con coste capital.")
    elif expected_days >= 60:
        factors["low_liquidity"] = 6
    else:
        factors["low_liquidity"] = 0

    # Datos insuficientes de mercado
    factors["insufficient_market_data"] = 0 if has_market_sample else 15
    if not has_market_sample:
        notes.append("Sin comparables suficientes: el precio fair es estimado, alta incertidumbre.")

    # Edad extrema (motor/electrónica caras)
    if v.age_years >= 12 and v.km > 200_000:
        factors["age_mileage"] = 10
    else:
        factors["age_mileage"] = 0

    score = min(100, sum(factors.values()))

    if score >= 60:
        label = "Crítico"
    elif score >= 35:
        label = "Alto"
    elif score >= 15:
        label = "Medio"
    else:
        label = "Bajo"

    return RiskScore(score=score, label=label, factors=factors, notes=notes)
