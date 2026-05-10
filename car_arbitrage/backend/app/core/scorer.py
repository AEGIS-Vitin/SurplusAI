"""Scorer: orquesta todos los módulos y calcula el veredicto.

Devuelve coste total puesto en venta, margen esperado, semáforo y un
Monte Carlo (1000 sims) sobre las variables principales.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.core import customs, fx, homologation, iedmt, pricer, reconditioning, transport, vat_regimes
from app.models.vehicle import (
    AnalysisRequest,
    Comparable,
    FuelType,
    Origin,
    VATRegime,
    Vehicle,
)


@dataclass
class CostBreakdown:
    purchase: float = 0.0
    auction_fees: float = 0.0
    transport: float = 0.0
    customs: float = 0.0
    iedmt: float = 0.0
    homologation: float = 0.0
    reconditioning: float = 0.0
    capital_cost: float = 0.0
    operational: float = 0.0
    homologation_risk_provision: float = 0.0
    total: float = 0.0
    detail: dict = field(default_factory=dict)


@dataclass
class Verdict:
    label: str          # 🟢 / 🟡 / 🔴 / ⚫
    margin_eur: float
    margin_pct: float
    margin_after_tax_eur: float
    expected_sale_eur: float
    cost_total_eur: float
    cost_breakdown: CostBreakdown
    market_stats_es: Optional[pricer.MarketStats]
    market_stats_de: Optional[pricer.MarketStats]
    monte_carlo: dict
    max_bid_eur: float
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    iedmt_detail: Optional[dict] = None
    customs_detail: Optional[dict] = None
    vat_detail: Optional[dict] = None
    reconditioning_detail: Optional[dict] = None
    homologation_detail: Optional[dict] = None
    transport_detail: Optional[dict] = None


def _flag_vehicle(v: Vehicle) -> list[str]:
    flags = []
    if v.km < 30_000 and v.age_years > 5:
        flags.append("Sospecha rollback: <30k km con >5 años.")
    if v.previous_owners and v.previous_owners > 4:
        flags.append(f"{v.previous_owners} propietarios anteriores.")
    if v.declared_damages and "estructur" in v.declared_damages.lower():
        flags.append("Daños estructurales declarados.")
    if not v.has_service_book:
        flags.append("Sin libro de mantenimiento.")
    return flags


def _is_premium(v: Vehicle) -> bool:
    return v.make.lower() in {
        "bmw", "mercedes-benz", "mercedes", "audi", "porsche", "lexus",
        "land rover", "range rover", "jaguar", "volvo", "tesla", "maserati",
        "bentley", "ferrari", "lamborghini", "aston martin",
    }


def _fiscal_value_estimate(v: Vehicle, target_sale: float) -> float:
    """Aproximación del valor fiscal de Hacienda 'a nuevo'.

    En la realidad se usa la Orden HFP anual (precios medios del BOE).
    Aquí estimamos: precio venta actual / coef depreciación (suelo razonable).
    """
    coef = max(0.10, iedmt.depreciation_coef(v.age_years))
    return target_sale / coef


def analyze(req: AnalysisRequest) -> Verdict:
    v = req.vehicle
    flags = _flag_vehicle(v)
    notes: list[str] = []

    # 1. Adquisición en EUR
    purchase_eur = fx.to_eur(req.purchase_price, req.purchase_currency, req.fx_rate_to_eur if req.fx_rate_to_eur != 1.0 else None)
    auction_fees = 0.0
    if req.origin in (Origin.EU_AUCTION,):
        auction_fees = purchase_eur * req.auction_fee_pct + req.auction_flat_fee
        auction_fees *= 1 + 0.21  # IVA sobre comisión
    cost = CostBreakdown(purchase=purchase_eur, auction_fees=auction_fees)

    # 2. Transporte
    if req.transport_eur is not None:
        transport_cost = req.transport_eur
        transport_detail = {"override": req.transport_eur}
    else:
        if req.origin == Origin.EXTRA_EU:
            est = transport.estimate_extra_eu(
                origin_iso=v.origin_country,
                container=False,
                declared_value_eur=purchase_eur,
            )
        else:
            est = transport.estimate_eu_truck(v.origin_country)
        transport_cost = est.cost_eur
        transport_detail = {"mode": est.mode, "transit_days": est.transit_days, "notes": est.notes}
    cost.transport = transport_cost

    # 3. Aduanas si extra-UE
    customs_detail: Optional[dict] = None
    if req.origin == Origin.EXTRA_EU:
        cb = customs.compute_customs(
            purchase_eur=purchase_eur,
            freight_eur=transport_cost * 0.7,  # aproximación: 70% del transporte es flete internacional
            insurance_eur=purchase_eur * 0.015,
            canary=req.canary_islands,
            historic=v.age_years >= 30,
        )
        cost.customs = cb.total_eur
        customs_detail = {
            "cif": cb.cif_eur, "duty": cb.duty_eur, "vat": cb.vat_eur,
            "dua": cb.dua_fee_eur, "inspection": cb.inspection_fee_eur,
            "notes": cb.notes,
        }

    # 4. IEDMT
    target_sale_estimate = purchase_eur * 1.25  # placeholder hasta saber comparables
    fiscal_value = _fiscal_value_estimate(v, target_sale_estimate)
    iedmt_res = iedmt.compute_iedmt(
        vehicle=v,
        fiscal_value_new_eur=fiscal_value,
        canary=req.canary_islands,
        historic_vehicle=v.age_years >= 30,
    )
    cost.iedmt = iedmt_res.tax_eur
    iedmt_detail = {
        "rate": iedmt_res.rate, "base": iedmt_res.base_eur, "tax": iedmt_res.tax_eur,
        "exemption": iedmt_res.exemption_reason, "notes": iedmt_res.notes,
    }

    # 5. Homologación + matriculación
    is_us = v.origin_country == "US"
    hom = homologation.estimate_homologation(
        origin_iso=v.origin_country,
        has_coc=v.has_coc,
        declared_value_eur=purchase_eur,
        is_premium=_is_premium(v),
        is_us_spec=is_us,
    )
    cost.homologation = hom.total_eur
    cost.homologation_risk_provision = hom.risk_provision_eur
    homologation_detail = {"breakdown": hom.breakdown, "risk_provision": hom.risk_provision_eur, "notes": hom.notes}

    # 6. Reacondicionado
    if req.reconditioning_eur is not None:
        cost.reconditioning = req.reconditioning_eur
        recond_detail = {"override": req.reconditioning_eur}
    else:
        rc = reconditioning.estimate_reconditioning(v, is_premium=_is_premium(v))
        cost.reconditioning = rc.total_eur
        recond_detail = {"breakdown": rc.breakdown, "notes": rc.notes}

    # 7. Comparables y precio de venta esperado
    stats_es = pricer.market_stats(req.comparables, v, "ES")
    stats_de = pricer.market_stats(req.comparables, v, "DE")

    if stats_es is None:
        notes.append("Muestra ES <5 comparables: veredicto sin solidez estadística.")
        expected_sale = purchase_eur * 1.25
    else:
        expected_sale = stats_es.fair_price

    # 8. Coste capital y operativos
    capital_cost = (purchase_eur + auction_fees + transport_cost + cost.customs +
                    cost.iedmt + cost.homologation + cost.reconditioning) * \
                   req.capital_cost_annual * (req.days_in_stock / 365)
    cost.capital_cost = capital_cost
    operational = expected_sale * 0.025 + 30  # publicación + garantía + seguro stock
    cost.operational = operational

    # 9. Total parcial sin IVA
    cost.total = (
        cost.purchase + cost.auction_fees + cost.transport + cost.customs
        + cost.iedmt + cost.homologation + cost.reconditioning
        + cost.capital_cost + cost.operational + cost.homologation_risk_provision
    )

    # 10. IVA según régimen
    if req.vat_regime == VATRegime.REBU:
        vat = vat_regimes.rebu_vat(expected_sale, cost.total)
        # En REBU el IVA repercutido reduce el ingreso neto
        net_revenue = expected_sale - vat.net_vat_to_pay
    elif req.vat_regime == VATRegime.GENERAL:
        # Asumimos precio IVA incluido para venta a particular
        sale_net = expected_sale / 1.21
        deductible = (cost.transport + cost.reconditioning + cost.operational) * 0.21 / 1.21
        vat = vat_regimes.general_vat(sale_net, deductible)
        net_revenue = sale_net  # ingreso neto de IVA
        # Ajustar coste retirando IVA deducible que se recupera
        cost.total -= deductible
    else:  # IMPORT_EXTRA_EU: IVA importación ya pagado en aduanas. Venta general.
        sale_net = expected_sale / 1.21
        deductible = 0.0  # IVA importación ya está dentro de cost.customs y se deduce contra IVA repercutido en venta
        vat_import_deductible = customs_detail["vat"] if customs_detail else 0.0
        vat = vat_regimes.general_vat(sale_net, deductible + vat_import_deductible)
        cost.total -= vat_import_deductible
        net_revenue = sale_net

    margin_eur = net_revenue - cost.total
    margin_pct = margin_eur / cost.total if cost.total > 0 else 0.0
    margin_after_tax = margin_eur * (1 - req.income_tax_rate) if margin_eur > 0 else margin_eur

    # 11. Monte Carlo
    mc = _monte_carlo(req, expected_sale, stats_es, cost.total)

    # 12. Puja máxima recomendada
    max_bid = _max_bid(req, cost, expected_sale, stats_es)

    # 13. Veredicto
    if any(("estructur" in f.lower()) for f in flags):
        label = "⚫ VETO"
    elif req.origin == Origin.EXTRA_EU and not v.euro_norm:
        label = "🟡 AMARILLO (norma Euro no verificada)"
        flags.append("Verificar Euro 6d antes de comprar (extra-UE).")
    elif margin_pct >= 0.12 and margin_eur >= 1500:
        label = "🟢 VERDE"
    elif margin_pct >= 0.06:
        label = "🟡 AMARILLO"
    else:
        label = "🔴 ROJO"

    return Verdict(
        label=label,
        margin_eur=margin_eur,
        margin_pct=margin_pct,
        margin_after_tax_eur=margin_after_tax,
        expected_sale_eur=expected_sale,
        cost_total_eur=cost.total,
        cost_breakdown=cost,
        market_stats_es=stats_es,
        market_stats_de=stats_de,
        monte_carlo=mc,
        max_bid_eur=max_bid,
        flags=flags,
        notes=notes,
        iedmt_detail=iedmt_detail,
        customs_detail=customs_detail,
        vat_detail={"regime": vat.regime, "charged": vat.vat_charged, "deductible": vat.vat_deductible, "net_to_pay": vat.net_vat_to_pay, "notes": vat.notes},
        reconditioning_detail=recond_detail,
        homologation_detail=homologation_detail,
        transport_detail=transport_detail,
    )


def _monte_carlo(req: AnalysisRequest, expected_sale: float, stats_es, cost_total: float, n: int = 1000) -> dict:
    rng = np.random.default_rng(42)
    sigma = stats_es.std if stats_es else expected_sale * 0.08
    sales = rng.normal(expected_sale, sigma, n)
    if stats_es:
        sales = np.clip(sales, stats_es.p25 * 0.95, stats_es.p75 * 1.15)
    days = rng.lognormal(mean=np.log(req.days_in_stock), sigma=0.4, size=n)
    capital_factor = days / 365 * req.capital_cost_annual
    capital_var = cost_total * capital_factor - cost_total * (req.days_in_stock / 365 * req.capital_cost_annual)
    margins = sales - cost_total - capital_var

    return {
        "n": n,
        "expected_margin_eur": float(margins.mean()),
        "std_margin_eur": float(margins.std()),
        "p5_margin_eur": float(np.percentile(margins, 5)),
        "p50_margin_eur": float(np.percentile(margins, 50)),
        "p95_margin_eur": float(np.percentile(margins, 95)),
        "prob_loss": float((margins < 0).mean()),
        "var95_eur": float(np.percentile(margins, 5)),  # peor 5%
    }


def _max_bid(req: AnalysisRequest, cost: CostBreakdown, expected_sale: float, stats_es) -> float:
    """Precio máximo de adjudicación que mantiene margen objetivo en P25 venta."""
    floor_sale = stats_es.p25 if stats_es else expected_sale * 0.92
    target = floor_sale / (1 + req.target_margin_pct)
    fixed_costs = cost.total - cost.purchase - cost.auction_fees
    auction_factor = 1 + req.auction_fee_pct * 1.21
    max_bid = (target - fixed_costs - req.auction_flat_fee * 1.21) / auction_factor
    return max(0.0, max_bid)
