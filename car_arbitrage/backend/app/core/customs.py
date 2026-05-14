"""Aduanas — importación extra-UE (Dubái, Japón, EE.UU., UK post-Brexit, etc.).

Base aduana = CIF = Precio + Flete + Seguro (todo en EUR).
- Arancel TARIC 8703 coches pasajeros: 10%
- IVA importación 21% sobre (CIF + Arancel)  [Canarias IGIC 7%]
- DUA / agente aduanas: 280-500€
"""
from __future__ import annotations

from dataclasses import dataclass

VAT_RATE_ES = 0.21
IGIC_RATE_CANARY = 0.07
DUTY_PASSENGER_CAR = 0.10
HISTORIC_DUTY = 0.0


@dataclass
class CustomsBreakdown:
    cif_eur: float
    duty_rate: float
    duty_eur: float
    vat_rate: float
    vat_eur: float
    dua_fee_eur: float
    inspection_fee_eur: float
    total_eur: float
    notes: list[str]


def compute_customs(
    purchase_eur: float,
    freight_eur: float,
    insurance_eur: float,
    canary: bool = False,
    historic: bool = False,
    dua_fee: float = 380.0,
    inspection_prob: float = 0.15,
    inspection_cost: float = 220.0,
) -> CustomsBreakdown:
    cif = purchase_eur + freight_eur + insurance_eur
    duty_rate = HISTORIC_DUTY if historic else DUTY_PASSENGER_CAR
    duty = cif * duty_rate

    vat_rate = IGIC_RATE_CANARY if canary else VAT_RATE_ES
    vat = (cif + duty) * vat_rate

    inspection_expected = inspection_cost * inspection_prob

    notes = [
        f"CIF (precio + flete + seguro): {cif:,.2f} €",
        f"Arancel TARIC {duty_rate*100:.1f}%: {duty:,.2f} €",
        f"{'IGIC' if canary else 'IVA importación'} {vat_rate*100:.1f}% sobre CIF+arancel: {vat:,.2f} €",
        f"DUA/agente aduanas: {dua_fee:,.2f} €",
        f"Inspección esperada (prob {inspection_prob*100:.0f}%): {inspection_expected:,.2f} €",
    ]
    if historic:
        notes.append("Vehículo histórico (>30 años): arancel 0% TARIC 9705.")

    total = duty + vat + dua_fee + inspection_expected
    return CustomsBreakdown(
        cif_eur=cif,
        duty_rate=duty_rate,
        duty_eur=duty,
        vat_rate=vat_rate,
        vat_eur=vat,
        dua_fee_eur=dua_fee,
        inspection_fee_eur=inspection_expected,
        total_eur=total,
        notes=notes,
    )
