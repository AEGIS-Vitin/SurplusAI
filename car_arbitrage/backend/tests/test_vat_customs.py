from app.core import customs, vat_regimes


def test_rebu_vat_solo_sobre_margen():
    r = vat_regimes.rebu_vat(sale_price=20000, total_purchase_cost_vat_incl=15000)
    # margen 5000, IVA = 5000 * 21/121 ≈ 867.77
    assert abs(r.vat_charged - 867.768) < 1
    assert r.vat_deductible == 0.0
    assert r.regime == "REBU"


def test_rebu_margen_negativo_no_iva():
    r = vat_regimes.rebu_vat(sale_price=10000, total_purchase_cost_vat_incl=12000)
    assert r.vat_charged == 0.0


def test_general_iva():
    r = vat_regimes.general_vat(sale_price_net=20000, deductible_input_vat=500)
    assert abs(r.vat_charged - 4200) < 1
    assert r.net_vat_to_pay == 4200 - 500


def test_intracomunitario_neutro():
    r = vat_regimes.intracomm_acquisition_vat(net_purchase_price=10000)
    assert r.net_vat_to_pay == 0.0


def test_aduanas_dubai_basico():
    cb = customs.compute_customs(
        purchase_eur=30000, freight_eur=2000, insurance_eur=450,
    )
    # CIF = 32450, arancel 10% = 3245, IVA 21% sobre 35695 = 7495.95
    assert abs(cb.cif_eur - 32450) < 1
    assert abs(cb.duty_eur - 3245) < 1
    assert abs(cb.vat_eur - 7495.95) < 1


def test_canarias_igic():
    cb = customs.compute_customs(
        purchase_eur=10000, freight_eur=500, insurance_eur=150, canary=True,
    )
    assert cb.vat_rate == 0.07


def test_historico_arancel_cero():
    cb = customs.compute_customs(
        purchase_eur=20000, freight_eur=1000, insurance_eur=300, historic=True,
    )
    assert cb.duty_eur == 0.0
