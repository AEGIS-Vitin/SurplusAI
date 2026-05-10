"""Scorer: orquesta todos los módulos y calcula el veredicto.

Devuelve coste total, escenarios de venta (rápida/recomendada/paciente),
ROI anualizado, NPV, risk score combinado, rotación teórica y Monte Carlo.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.core import customs, fx, homologation, iedmt, pricer, reconditioning, risk, rotation, transport, vat_regimes
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
class SaleScenario:
    name: str                    # "quick" / "recommended" / "patient"
    label: str                   # texto humano
    sale_price_eur: float
    days_to_sell: float
    margin_eur: float
    margin_pct: float
    margin_after_tax_eur: float
    annualized_roi_pct: float    # ROI anualizado por capital empleado
    npv_eur: float               # Beneficio descontado
    notes: list[str]


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
    rotation: Optional[dict] = None
    risk: Optional[dict] = None
    scenarios: list[dict] = field(default_factory=list)
    annualized_roi_pct: float = 0.0
    recommended_sale_eur: float = 0.0
    summary: dict = field(default_factory=dict)


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
    coef = max(0.10, iedmt.depreciation_coef(v.age_years))
    return target_sale / coef


def _build_scenario(
    name: str,
    label: str,
    sale_price: float,
    days_to_sell: float,
    fixed_costs: float,         # coste sin capital_cost (el capital_cost depende de los días)
    capital_employed: float,
    capital_cost_annual: float,
    income_tax_rate: float,
    discount_rate_annual: float = 0.08,
) -> SaleScenario:
    capital_cost = capital_employed * capital_cost_annual * (days_to_sell / 365)
    total_cost = fixed_costs + capital_cost
    margin = sale_price - total_cost
    margin_pct = margin / total_cost if total_cost > 0 else 0.0

    # ROI anualizado: rendimiento por euro de capital empleado, escalado a 365 días
    if capital_employed > 0 and days_to_sell > 0:
        roi_periodic = margin / capital_employed
        annualized = roi_periodic * (365 / days_to_sell)
    else:
        annualized = 0.0

    # NPV: descontar el ingreso de venta a la fecha de cobro
    discount_factor = 1 / ((1 + discount_rate_annual) ** (days_to_sell / 365))
    npv = (sale_price * discount_factor) - fixed_costs - capital_cost

    margin_after_tax = margin * (1 - income_tax_rate) if margin > 0 else margin

    return SaleScenario(
        name=name, label=label,
        sale_price_eur=sale_price,
        days_to_sell=days_to_sell,
        margin_eur=margin,
        margin_pct=margin_pct,
        margin_after_tax_eur=margin_after_tax,
        annualized_roi_pct=annualized,
        npv_eur=npv,
        notes=[],
    )


def analyze(req: AnalysisRequest) -> Verdict:
    v = req.vehicle
    flags = _flag_vehicle(v)
    notes: list[str] = []

    # 1. Adquisición en EUR
    purchase_eur = fx.to_eur(
        req.purchase_price, req.purchase_currency,
        req.fx_rate_to_eur if req.fx_rate_to_eur != 1.0 else None,
    )
    auction_fees = 0.0
    if req.origin == Origin.EU_AUCTION:
        auction_fees = (purchase_eur * req.auction_fee_pct + req.auction_flat_fee) * 1.21
    cost = CostBreakdown(purchase=purchase_eur, auction_fees=auction_fees)

    # 2. Transporte
    if req.transport_eur is not None:
        transport_cost = req.transport_eur
        transport_detail = {"override": req.transport_eur}
    else:
        if req.origin == Origin.EXTRA_EU:
            est = transport.estimate_extra_eu(
                origin_iso=v.origin_country, container=False, declared_value_eur=purchase_eur,
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
            freight_eur=transport_cost * 0.7,
            insurance_eur=purchase_eur * 0.015,
            canary=req.canary_islands,
            historic=v.age_years >= 30,
        )
        cost.customs = cb.total_eur
        customs_detail = {
            "cif": cb.cif_eur, "duty": cb.duty_eur, "vat": cb.vat_eur,
            "dua": cb.dua_fee_eur, "inspection": cb.inspection_fee_eur, "notes": cb.notes,
        }

    # 4. IEDMT
    target_sale_estimate = purchase_eur * 1.25
    fiscal_value = _fiscal_value_estimate(v, target_sale_estimate)
    iedmt_res = iedmt.compute_iedmt(
        vehicle=v, fiscal_value_new_eur=fiscal_value,
        canary=req.canary_islands, historic_vehicle=v.age_years >= 30,
    )
    cost.iedmt = iedmt_res.tax_eur
    iedmt_detail = {
        "rate": iedmt_res.rate, "base": iedmt_res.base_eur, "tax": iedmt_res.tax_eur,
        "exemption": iedmt_res.exemption_reason, "notes": iedmt_res.notes,
    }

    # 5. Homologación + matriculación
    is_us = v.origin_country == "US"
    hom = homologation.estimate_homologation(
        origin_iso=v.origin_country, has_coc=v.has_coc,
        declared_value_eur=purchase_eur,
        is_premium=_is_premium(v), is_us_spec=is_us,
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

    # 7. Comparables
    stats_es = pricer.market_stats(req.comparables, v, "ES")
    stats_de = pricer.market_stats(req.comparables, v, "DE")
    if stats_es is None:
        notes.append("Muestra ES <5 comparables: veredicto sin solidez estadística.")
        expected_sale = purchase_eur * 1.25
    else:
        expected_sale = stats_es.fair_price

    # 8. Rotación teórica
    rot = rotation.estimate_rotation(v, override_days=float(req.days_in_stock) if req.days_in_stock else None)
    rotation_detail = rot.__dict__.copy()

    # 9. Costes operativos y capital base (con días recomendados de rotación)
    operational = expected_sale * 0.025 + 30
    cost.operational = operational

    days_recommended = rot.median_days
    fixed_no_capital = (
        cost.purchase + cost.auction_fees + cost.transport + cost.customs
        + cost.iedmt + cost.homologation + cost.reconditioning
        + cost.operational + cost.homologation_risk_provision
    )
    capital_employed = fixed_no_capital
    capital_cost_recommended = capital_employed * req.capital_cost_annual * (days_recommended / 365)
    cost.capital_cost = capital_cost_recommended

    cost.total = fixed_no_capital + cost.capital_cost

    # 10. IVA según régimen
    if req.vat_regime == VATRegime.REBU:
        vat = vat_regimes.rebu_vat(expected_sale, cost.total)
        net_revenue = expected_sale - vat.net_vat_to_pay
    elif req.vat_regime == VATRegime.GENERAL:
        sale_net = expected_sale / 1.21
        deductible = (cost.transport + cost.reconditioning + cost.operational) * 0.21 / 1.21
        vat = vat_regimes.general_vat(sale_net, deductible)
        net_revenue = sale_net
        cost.total -= deductible
        fixed_no_capital -= deductible
    else:  # IMPORT_EXTRA_EU
        sale_net = expected_sale / 1.21
        vat_import_deductible = customs_detail["vat"] if customs_detail else 0.0
        vat = vat_regimes.general_vat(sale_net, vat_import_deductible)
        cost.total -= vat_import_deductible
        fixed_no_capital -= vat_import_deductible
        net_revenue = sale_net

    # 11. Escenarios de venta (acotados para que quick < recommended < patient)
    if stats_es:
        rec_price = stats_es.fair_price
        quick_price = min(stats_es.p25 * 1.05, rec_price * 0.96)
        patient_price = max(stats_es.p75, rec_price * 1.04)
    else:
        rec_price = expected_sale
        quick_price = expected_sale * 0.93
        patient_price = expected_sale * 1.07
    recommended_price = rec_price

    quick_days = max(15, rot.p25_days * 0.85)
    recommended_days = rot.median_days
    patient_days = rot.p75_days

    scenarios = [
        _build_scenario("quick", "Venta rápida (P25 × 1.05)",
                        quick_price, quick_days, fixed_no_capital, capital_employed,
                        req.capital_cost_annual, req.income_tax_rate),
        _build_scenario("recommended", "Recomendada (precio justo)",
                        recommended_price, recommended_days, fixed_no_capital, capital_employed,
                        req.capital_cost_annual, req.income_tax_rate),
        _build_scenario("patient", "Paciente (P75)",
                        patient_price, patient_days, fixed_no_capital, capital_employed,
                        req.capital_cost_annual, req.income_tax_rate),
    ]
    rec_scenario = scenarios[1]

    margin_eur = net_revenue - cost.total
    margin_pct = margin_eur / cost.total if cost.total > 0 else 0.0
    margin_after_tax = margin_eur * (1 - req.income_tax_rate) if margin_eur > 0 else margin_eur

    # 12. Monte Carlo con días variables
    mc = _monte_carlo(req, expected_sale, stats_es, fixed_no_capital, capital_employed, rot)

    # 13. Puja máxima
    max_bid = _max_bid(req, cost, expected_sale, stats_es)

    # 14. Risk score combinado
    risk_score = risk.compute_risk(v, req.origin, rot.median_days, has_market_sample=stats_es is not None)

    # 15. Veredicto combinando margen + riesgo
    if any(("estructur" in f.lower()) for f in flags):
        label = "⚫ VETO"
    elif risk_score.score >= 60:
        label = "⚫ VETO (riesgo crítico)"
    elif req.origin == Origin.EXTRA_EU and not v.euro_norm:
        label = "🟡 AMARILLO (Euro no verificada)"
        flags.append("Verificar Euro 6d antes de comprar (extra-UE).")
    elif margin_pct >= 0.12 and margin_eur >= 1500 and risk_score.score < 35:
        label = "🟢 VERDE"
    elif margin_pct >= 0.06 and risk_score.score < 50:
        label = "🟡 AMARILLO"
    else:
        label = "🔴 ROJO"

    summary = {
        "vehicle": f"{v.make} {v.model} {v.version or ''} {v.year} · {v.km:,} km".strip(),
        "verdict": label,
        "recommended_sale_eur": rec_scenario.sale_price_eur,
        "expected_margin_eur": rec_scenario.margin_eur,
        "expected_days_to_sell": rec_scenario.days_to_sell,
        "annualized_roi_pct": rec_scenario.annualized_roi_pct,
        "max_bid_eur": max_bid,
        "risk_score": risk_score.score,
        "risk_label": risk_score.label,
        "velocity": rot.velocity_label,
    }

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
        vat_detail={"regime": vat.regime, "charged": vat.vat_charged, "deductible": vat.vat_deductible,
                    "net_to_pay": vat.net_vat_to_pay, "notes": vat.notes},
        reconditioning_detail=recond_detail,
        homologation_detail=homologation_detail,
        transport_detail=transport_detail,
        rotation=rotation_detail,
        risk={"score": risk_score.score, "label": risk_score.label,
              "factors": risk_score.factors, "notes": risk_score.notes},
        scenarios=[s.__dict__ for s in scenarios],
        annualized_roi_pct=rec_scenario.annualized_roi_pct,
        recommended_sale_eur=rec_scenario.sale_price_eur,
        summary=summary,
    )


def _monte_carlo(req: AnalysisRequest, expected_sale: float, stats_es,
                 fixed_no_capital: float, capital_employed: float, rot, n: int = 1000) -> dict:
    rng = np.random.default_rng(42)
    sigma = stats_es.std if stats_es else expected_sale * 0.08
    sales = rng.normal(expected_sale, sigma, n)
    if stats_es:
        sales = np.clip(sales, stats_es.p25 * 0.95, stats_es.p75 * 1.15)

    # Días: LogNormal alrededor de la mediana del segmento
    mu = np.log(rot.median_days)
    days = rng.lognormal(mean=mu, sigma=0.4, size=n)
    capital_costs = capital_employed * req.capital_cost_annual * (days / 365)

    margins = sales - fixed_no_capital - capital_costs

    return {
        "n": n,
        "expected_margin_eur": float(margins.mean()),
        "std_margin_eur": float(margins.std()),
        "p5_margin_eur": float(np.percentile(margins, 5)),
        "p50_margin_eur": float(np.percentile(margins, 50)),
        "p95_margin_eur": float(np.percentile(margins, 95)),
        "prob_loss": float((margins < 0).mean()),
        "prob_margin_above_1500": float((margins >= 1500).mean()),
        "prob_margin_above_3000": float((margins >= 3000).mean()),
        "var95_eur": float(np.percentile(margins, 5)),
        "expected_days_to_sell": float(days.mean()),
        "p90_days_to_sell": float(np.percentile(days, 90)),
    }


def _max_bid(req: AnalysisRequest, cost: CostBreakdown, expected_sale: float, stats_es) -> float:
    floor_sale = stats_es.p25 if stats_es else expected_sale * 0.92
    target = floor_sale / (1 + req.target_margin_pct)
    fixed_costs = cost.total - cost.purchase - cost.auction_fees
    auction_factor = 1 + req.auction_fee_pct * 1.21
    max_bid = (target - fixed_costs - req.auction_flat_fee * 1.21) / auction_factor
    return max(0.0, max_bid)
