"""Homologación y matriculación.

UE con COC: ficha técnica reducida ITV.
Extra-UE: homologación individual obligatoria + adaptaciones (luces, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass

EU_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
}

ITV_TASA_TRAFICO = 99.77
ITV_FICHA_REDUCIDA = 150.0
ITV_FICHA_COMPLETA = 250.0
PLATES = 25.0


@dataclass
class HomologationCost:
    total_eur: float
    breakdown: dict
    risk_provision_eur: float
    notes: list[str]


def estimate_homologation(
    origin_iso: str,
    has_coc: bool,
    declared_value_eur: float,
    is_premium: bool = False,
    is_us_spec: bool = False,
    gestoria_eur: float = 350.0,
) -> HomologationCost:
    notes: list[str] = []
    breakdown: dict = {
        "tasa_trafico_9050": ITV_TASA_TRAFICO,
        "gestoria": gestoria_eur,
        "placas": PLATES,
    }
    risk_provision = 0.0

    if origin_iso in EU_COUNTRIES:
        if has_coc:
            breakdown["itv_ficha_reducida"] = ITV_FICHA_REDUCIDA
        else:
            breakdown["itv_ficha_reducida"] = ITV_FICHA_REDUCIDA
            breakdown["coc_request"] = 200.0
            notes.append("Sin COC: solicitar al fabricante (50-300€).")
    else:
        # Extra-UE: homologación individual obligatoria
        base_homol = 1500.0 if not is_premium else 2500.0
        breakdown["homologacion_individual"] = base_homol
        breakdown["itv_ficha_completa"] = ITV_FICHA_COMPLETA

        # Adaptaciones específicas
        adaptations = 0.0
        if is_us_spec:
            adaptations += 1500  # faros DOT→E, intermitentes ámbar, mph→kmh
            notes.append("Spec USA: faros marcado E, intermitentes ámbar, velocímetro km/h.")
        else:
            adaptations += 500  # GCC/AE: principalmente faros + antiniebla trasera
            notes.append("Spec GCC/AE: marcado E faros, antiniebla trasera, posibles luces.")
        breakdown["adaptaciones"] = adaptations

        # Provisión de riesgo: 15% del valor declarado por si no pasa homologación
        risk_provision = declared_value_eur * 0.15
        notes.append(
            f"Riesgo homologación extra-UE: provisión 15% ({risk_provision:,.0f} €). "
            "Verificar emisiones Euro 6d antes de comprar."
        )

    total = sum(breakdown.values())
    return HomologationCost(
        total_eur=total,
        breakdown=breakdown,
        risk_provision_eur=risk_provision,
        notes=notes,
    )
