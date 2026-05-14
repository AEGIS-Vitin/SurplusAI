"""IVA: REBU, régimen general y autoliquidación intracomunitaria.

REBU (art. 135-139 Ley 37/1992): comerciante de bienes usados, base imponible
del IVA = margen (precio venta − precio compra IVA incluido). Sin IVA
deducible de gastos directos imputables al vehículo.

Régimen general: IVA 21% sobre venta. IVA soportado deducible.

Adquisición intracomunitaria con vendedor profesional UE IVA deducible:
factura sin IVA, autoliquidación en 303 (IVA soportado y repercutido se
compensan si derecho a deducción 100%).
"""
from __future__ import annotations

from dataclasses import dataclass

VAT_RATE_ES = 0.21


@dataclass
class VATBreakdown:
    regime: str
    vat_charged: float        # IVA repercutido al cliente final
    vat_deductible: float     # IVA soportado deducible
    net_vat_to_pay: float     # vat_charged − vat_deductible
    notes: list[str]


def rebu_vat(sale_price: float, total_purchase_cost_vat_incl: float) -> VATBreakdown:
    """REBU: IVA = margen × 21/121. IVA de gastos NO deducible (ya en coste)."""
    margin = max(0.0, sale_price - total_purchase_cost_vat_incl)
    vat = margin * (VAT_RATE_ES / (1 + VAT_RATE_ES))
    return VATBreakdown(
        regime="REBU",
        vat_charged=vat,
        vat_deductible=0.0,
        net_vat_to_pay=vat,
        notes=[
            f"Base IVA (margen): {margin:,.2f} €",
            "Factura SIN IVA al cliente (art. 135 Ley 37/1992).",
            "IVA soportado en gastos NO deducible (forma parte del coste).",
        ],
    )


def general_vat(sale_price_net: float, deductible_input_vat: float) -> VATBreakdown:
    """General: IVA 21% sobre precio neto, deduces IVA de gastos."""
    vat_out = sale_price_net * VAT_RATE_ES
    return VATBreakdown(
        regime="General",
        vat_charged=vat_out,
        vat_deductible=deductible_input_vat,
        net_vat_to_pay=vat_out - deductible_input_vat,
        notes=[
            f"IVA repercutido (21%): {vat_out:,.2f} €",
            f"IVA soportado deducible: {deductible_input_vat:,.2f} €",
        ],
    )


def intracomm_acquisition_vat(net_purchase_price: float) -> VATBreakdown:
    """Adquisición intracomunitaria profesional: autoliquidación 303.

    Devengado y soportado se compensan si derecho a deducción 100%.
    """
    self_vat = net_purchase_price * VAT_RATE_ES
    return VATBreakdown(
        regime="Intracomunitario (autoliquidación)",
        vat_charged=self_vat,
        vat_deductible=self_vat,
        net_vat_to_pay=0.0,
        notes=[
            "Modelo 303: IVA devengado y soportado se compensan.",
            "Requiere ROI/VIES alta del comprador y vendedor.",
        ],
    )
