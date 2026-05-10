import os
import tempfile

from app.core import scorer, storage
from app.core.notifier_telegram import format_verdict_message
from app.models.vehicle import (
    AnalysisRequest, Comparable, FuelType, Origin, VATRegime, Vehicle,
)


def _comps():
    base = []
    for price, km in [(22500, 88000), (21000, 105000), (23500, 75000),
                      (22000, 92000), (24000, 70000)]:
        base.append(Comparable(source="coches.net", market="ES",
                               price_eur=price, km=km, year=2020))
    return base


def _request():
    v = Vehicle(make="BMW", model="Serie 3", version="320d", year=2020, km=95000,
                fuel=FuelType.DIESEL, power_cv=190, co2_wltp=145, euro_norm="6d",
                origin_country="DE", has_coc=True, has_service_book=True, previous_owners=2)
    return AnalysisRequest(vehicle=v, origin=Origin.EU_AUCTION,
                           purchase_price=14500, vat_regime=VATRegime.REBU, comparables=_comps())


def test_scenarios_present_and_ordered_by_price():
    verdict = scorer.analyze(_request())
    sc = verdict.scenarios
    assert len(sc) == 3
    names = [s["name"] for s in sc]
    assert names == ["quick", "recommended", "patient"]
    assert sc[0]["sale_price_eur"] <= sc[1]["sale_price_eur"] <= sc[2]["sale_price_eur"]


def test_annualized_roi_positive_for_profitable_case():
    verdict = scorer.analyze(_request())
    rec = next(s for s in verdict.scenarios if s["name"] == "recommended")
    if rec["margin_eur"] > 0:
        assert rec["annualized_roi_pct"] > 0


def test_summary_fields_present():
    verdict = scorer.analyze(_request())
    s = verdict.summary
    for key in ("vehicle", "verdict", "recommended_sale_eur", "expected_margin_eur",
                "expected_days_to_sell", "annualized_roi_pct", "max_bid_eur",
                "risk_score", "risk_label", "velocity"):
        assert key in s


def test_storage_save_and_list():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "test.sqlite3")
        verdict = scorer.analyze(_request())
        from dataclasses import asdict
        vd = asdict(verdict)
        # Convert market stats, etc - storage uses dicts; serialize what we have
        from app.main import _serialize
        vd_ser = _serialize(verdict)
        aid = storage.save_analysis(_request().model_dump(), vd_ser, db_path=db)
        assert aid > 0
        rows = storage.list_recent(db_path=db)
        assert len(rows) == 1
        assert rows[0]["make"] == "BMW"


def test_telegram_message_format_no_crash():
    verdict = scorer.analyze(_request())
    from app.main import _serialize
    vd = _serialize(verdict)
    msg = format_verdict_message(vd, source_url="https://example.com/lot/123")
    assert "Serie" in msg or "BMW" in msg
    assert "ROI" in msg or "Margen" in msg or "margen" in msg
