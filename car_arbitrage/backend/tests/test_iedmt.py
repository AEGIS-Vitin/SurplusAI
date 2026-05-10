from app.core import iedmt
from app.models.vehicle import FuelType, Vehicle


def make(year=2020, fuel=FuelType.DIESEL, co2=145):
    return Vehicle(
        make="BMW", model="320d", year=year, km=80000, fuel=fuel,
        co2_wltp=co2, origin_country="DE",
    )


def test_bev_exento():
    v = make(fuel=FuelType.BEV, co2=0)
    r = iedmt.compute_iedmt(v, fiscal_value_new_eur=40000)
    assert r.tax_eur == 0.0
    assert "BEV" in (r.exemption_reason or "")


def test_tramos_co2_peninsula():
    assert iedmt.iedmt_rate(100) == 0.0
    assert iedmt.iedmt_rate(140) == 0.0475
    assert iedmt.iedmt_rate(180) == 0.0975
    assert iedmt.iedmt_rate(210) == 0.1475


def test_canarias_tipos_reducidos():
    assert iedmt.iedmt_rate(140, canary=True) == 0.0375


def test_depreciacion_floor():
    assert iedmt.depreciation_coef(50) == 0.10


def test_historico_exento():
    v = make(year=1990, fuel=FuelType.GASOLINE, co2=200)
    r = iedmt.compute_iedmt(v, fiscal_value_new_eur=10000, historic_vehicle=True)
    assert r.tax_eur == 0.0
    assert "histórico" in (r.exemption_reason or "")


def test_co2_none_asume_alto():
    v = Vehicle(make="X", model="Y", year=2018, km=100000, fuel=FuelType.GASOLINE,
                co2_wltp=None, origin_country="DE")
    r = iedmt.compute_iedmt(v, fiscal_value_new_eur=20000)
    assert r.rate == 0.1475
