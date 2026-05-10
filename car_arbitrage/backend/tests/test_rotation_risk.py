from app.core import rotation, risk
from app.models.vehicle import FuelType, Origin, Vehicle


def _v(**kw):
    base = dict(make="BMW", model="Serie 3", year=2020, km=80000,
                fuel=FuelType.DIESEL, origin_country="DE")
    base.update(kw)
    return Vehicle(**base)


def test_segmenta_premium_aleman():
    assert rotation.classify_segment(_v()) == "premium_german"


def test_segmenta_amg():
    v = _v(make="Mercedes", model="C63", version="AMG S")
    assert rotation.classify_segment(v) == "premium_german_high"


def test_segmenta_suv_grande():
    v = _v(make="BMW", model="X5", version="40d")
    assert rotation.classify_segment(v) == "suv_large"


def test_segmenta_city():
    v = _v(make="Volkswagen", model="Polo", version="GTI", fuel=FuelType.GASOLINE)
    assert rotation.classify_segment(v) == "city"


def test_segmenta_bev():
    v = _v(make="Tesla", model="Model 3", fuel=FuelType.BEV)
    assert rotation.classify_segment(v) == "ev_premium"


def test_velocity_score_decreases_with_speed():
    fast = _v(make="Volkswagen", model="Polo")
    slow = _v(make="Porsche", model="911")
    f = rotation.estimate_rotation(fast)
    s = rotation.estimate_rotation(slow)
    assert f.velocity_score < s.velocity_score
    assert f.median_days < s.median_days


def test_rotation_probs_consistent():
    r = rotation.estimate_rotation(_v())
    assert 0 <= r.prob_sell_within_30d <= r.prob_sell_within_60d <= r.prob_sell_within_90d <= 1


def test_risk_low_for_clean_vehicle():
    v = _v(km=60000)
    r = risk.compute_risk(v, Origin.EU_AUCTION, expected_days=35, has_market_sample=True)
    assert r.label == "Bajo"
    assert r.score < 15


def test_risk_high_for_extra_eu_with_rollback():
    v = _v(km=20000, year=2015)  # rollback sospechoso
    r = risk.compute_risk(v, Origin.EXTRA_EU, expected_days=70, has_market_sample=True)
    assert r.score >= 35
    assert r.label in ("Alto", "Crítico")


def test_risk_critical_with_structural_damage():
    v = _v(declared_damages="Daño estructural en pilar B")
    r = risk.compute_risk(v, Origin.EU_AUCTION, expected_days=35, has_market_sample=True)
    assert r.factors["structural_damage"] >= 30
