"""Smoke test del flujo completo end-to-end."""
from app.core import scorer
from app.models.vehicle import (
    AnalysisRequest,
    Comparable,
    FuelType,
    Origin,
    VATRegime,
    Vehicle,
)


def _comps():
    base = []
    for price, km in [(22500, 88000), (21000, 105000), (23500, 75000),
                      (22000, 92000), (24000, 70000)]:
        base.append(Comparable(source="coches.net", market="ES", price_eur=price, km=km, year=2020))
    for price, km in [(19500, 88000), (18900, 96000), (20800, 78000), (19200, 92000)]:
        base.append(Comparable(source="mobile.de", market="DE", price_eur=price, km=km, year=2020))
    return base


def test_bmw_320d_subasta_alemana():
    v = Vehicle(
        make="BMW", model="Serie 3", version="320d", year=2020, km=95000,
        fuel=FuelType.DIESEL, power_cv=190, co2_wltp=145, euro_norm="6d",
        origin_country="DE", has_coc=True, has_service_book=True, previous_owners=2,
    )
    req = AnalysisRequest(
        vehicle=v, origin=Origin.EU_AUCTION, purchase_price=14500,
        vat_regime=VATRegime.REBU, comparables=_comps(),
    )
    verdict = scorer.analyze(req)
    assert verdict.cost_total_eur > 14500
    assert verdict.expected_sale_eur > 0
    assert verdict.market_stats_es is not None
    assert verdict.market_stats_es.n == 5
    assert verdict.label.startswith(("🟢", "🟡", "🔴", "⚫"))
    assert "n" in verdict.monte_carlo


def test_dubai_extra_eu_includes_aduanas():
    v = Vehicle(
        make="Toyota", model="Land Cruiser", year=2021, km=45000,
        fuel=FuelType.GASOLINE, power_cv=309, co2_wltp=250, euro_norm="6d",
        origin_country="AE", has_coc=False, has_service_book=True,
    )
    req = AnalysisRequest(
        vehicle=v, origin=Origin.EXTRA_EU,
        purchase_price=180000, purchase_currency="AED", fx_rate_to_eur=0.25,
        vat_regime=VATRegime.IMPORT_EXTRA_EU,
        comparables=[
            Comparable(source="coches.net", market="ES", price_eur=68000, km=42000, year=2021),
            Comparable(source="coches.net", market="ES", price_eur=72000, km=38000, year=2021),
            Comparable(source="coches.net", market="ES", price_eur=70000, km=50000, year=2020),
            Comparable(source="autoscout24.es", market="ES", price_eur=69500, km=44000, year=2021),
            Comparable(source="autoscout24.es", market="ES", price_eur=71000, km=40000, year=2021),
        ],
    )
    verdict = scorer.analyze(req)
    assert verdict.customs_detail is not None
    assert verdict.customs_detail["duty"] > 0
    assert verdict.cost_breakdown.homologation_risk_provision > 0
