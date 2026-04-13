"""
Tests for carbon footprint calculation module.
"""

import pytest
from carbon import (
    calculate_co2_avoided,
    _calculate_equivalencias,
    get_carbon_report,
    get_sector_footprints,
    CO2_FOOTPRINTS
)


class TestCO2CalculationPerCategory:
    """Test CO2 calculation for different product categories."""

    def test_calculate_co2_carnes(self):
        """Test CO2 calculation for meat products"""
        co2, details = calculate_co2_avoided(
            cantidad_kg=100.0,
            categoria="carnes",
            uso_final=2  # Donación consumo
        )

        # Meat: 27 kg CO2e per kg
        expected_base = 27.0 * 100.0
        expected = expected_base * 1.0  # Full credit for donation

        assert co2 == expected
        assert details["categoria"] == "carnes"
        assert details["co2_footprint_por_kg"] == 27.0
        assert details["co2_base"] == 2700.0

    def test_calculate_co2_verduras(self):
        """Test CO2 calculation for vegetables"""
        co2, details = calculate_co2_avoided(
            cantidad_kg=50.0,
            categoria="verduras",
            uso_final=2
        )

        # Vegetables: 0.6 kg CO2e per kg
        expected = 0.6 * 50.0
        assert co2 == expected
        assert details["co2_footprint_por_kg"] == 0.6

    def test_calculate_co2_frutas(self):
        """Test CO2 calculation for fruits"""
        co2, details = calculate_co2_avoided(
            cantidad_kg=100.0,
            categoria="frutas",
            uso_final=1  # Prevention
        )

        expected = 0.8 * 100.0
        assert co2 == expected
        assert details["categoria"] == "frutas"

    def test_calculate_co2_pescados(self):
        """Test CO2 calculation for fish"""
        co2, details = calculate_co2_avoided(
            cantidad_kg=25.0,
            categoria="pescados",
            uso_final=4  # Animal feed
        )

        base = 12.0 * 25.0
        expected = base * 0.80
        assert co2 == expected

    def test_calculate_co2_lacteos(self):
        """Test CO2 calculation for dairy"""
        co2, details = calculate_co2_avoided(
            cantidad_kg=200.0,
            categoria="lacteos",
            uso_final=2
        )

        expected = 2.5 * 200.0
        assert co2 == expected

    def test_calculate_co2_panaderia(self):
        """Test CO2 calculation for bakery products"""
        co2, details = calculate_co2_avoided(
            cantidad_kg=150.0,
            categoria="panaderia",
            uso_final=3  # Transformation
        )

        base = 1.2 * 150.0
        expected = base * 0.95
        assert co2 == expected


class TestUseCase:
    """Test CO2 calculations for different end uses."""

    def test_donation_full_credit(self):
        """Test donation use case gets full CO2 credit"""
        co2_prevention, _ = calculate_co2_avoided(100.0, "carnes", 1)
        co2_donation, _ = calculate_co2_avoided(100.0, "carnes", 2)

        # Both should have same credit for high-value uses
        assert co2_prevention == co2_donation

    def test_animal_feed_reduced_credit(self):
        """Test animal feed gets 80% credit"""
        base_co2, _ = calculate_co2_avoided(100.0, "carnes", 2)  # Full
        animal_feed_co2, details = calculate_co2_avoided(100.0, "carnes", 4)

        assert details["uso_factor"] == 0.80
        assert animal_feed_co2 == base_co2 * 0.80

    def test_composting_reduced_credit(self):
        """Test composting gets 60% credit"""
        full_co2, _ = calculate_co2_avoided(100.0, "verduras", 2)
        compost_co2, details = calculate_co2_avoided(100.0, "verduras", 6)

        assert details["uso_factor"] == 0.60
        assert compost_co2 == full_co2 * 0.60

    def test_biogas_lower_credit(self):
        """Test biogas gets 50% credit"""
        full_co2, _ = calculate_co2_avoided(100.0, "frutas", 2)
        biogas_co2, details = calculate_co2_avoided(100.0, "frutas", 7)

        assert details["uso_factor"] == 0.50
        assert biogas_co2 == full_co2 * 0.50

    def test_elimination_minimal_credit(self):
        """Test elimination gets minimal 30% credit"""
        full_co2, _ = calculate_co2_avoided(100.0, "panaderia", 2)
        elim_co2, details = calculate_co2_avoided(100.0, "panaderia", 8)

        assert details["uso_factor"] == 0.30
        assert elim_co2 == full_co2 * 0.30

    def test_industrial_use_70_percent(self):
        """Test industrial use gets 70% credit"""
        full_co2, _ = calculate_co2_avoided(100.0, "lacteos", 2)
        industrial_co2, details = calculate_co2_avoided(100.0, "lacteos", 5)

        assert details["uso_factor"] == 0.70
        assert industrial_co2 == full_co2 * 0.70


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_quantity(self):
        """Test calculation with zero quantity"""
        co2, details = calculate_co2_avoided(
            cantidad_kg=0.0,
            categoria="carnes",
            uso_final=2
        )

        assert co2 == 0.0
        assert details["co2_base"] == 0.0
        assert details["cantidad_kg"] == 0.0

    def test_very_small_quantity(self):
        """Test calculation with very small quantity"""
        co2, details = calculate_co2_avoided(
            cantidad_kg=0.001,
            categoria="verduras",
            uso_final=2
        )

        expected = 0.6 * 0.001
        assert round(co2, 4) == round(expected, 4)

    def test_very_large_quantity(self):
        """Test calculation with very large quantity"""
        co2, details = calculate_co2_avoided(
            cantidad_kg=10000.0,
            categoria="frutas",
            uso_final=2
        )

        expected = 0.8 * 10000.0
        assert co2 == expected

    def test_unknown_category_uses_default(self):
        """Test that unknown category uses default footprint"""
        co2, details = calculate_co2_avoided(
            cantidad_kg=100.0,
            categoria="unknown_product",
            uso_final=2
        )

        # Should use default 2.0 for unknown
        expected = 2.0 * 100.0
        assert co2 == expected
        assert details["co2_footprint_por_kg"] == 2.0

    def test_invalid_uso_final_uses_default(self):
        """Test that invalid uso_final uses default factor"""
        co2, details = calculate_co2_avoided(
            cantidad_kg=100.0,
            categoria="carnes",
            uso_final=99  # Invalid
        )

        # Should use default 0.50
        base = 27.0 * 100.0
        expected = base * 0.50
        assert co2 == expected
        assert details["uso_factor"] == 0.50


class TestEquivalencyCalculations:
    """Test CO2 equivalency calculations."""

    def test_equivalencias_returned_in_details(self):
        """Test that equivalencies are included in details"""
        co2, details = calculate_co2_avoided(100.0, "carnes", 2)

        assert "equivalencias" in details
        equiv = details["equivalencias"]
        assert "km_coche_gasolina" in equiv
        assert "kWh_electricidad" in equiv
        assert "arboles_plantados_1_ano" in equiv
        assert "viaje_madrid_barcelona_avion" in equiv
        assert "kg_co2" in equiv

    def test_equivalencias_calculation_car_km(self):
        """Test car km equivalency calculation"""
        equiv = _calculate_equivalencias(23.0)  # 23 kg CO2

        # 23 kg / 0.23 kg/km = 100 km
        assert equiv["km_coche_gasolina"] == 100.0

    def test_equivalencias_calculation_electricity(self):
        """Test electricity kWh equivalency"""
        equiv = _calculate_equivalencias(42.0)  # 42 kg CO2

        # 42 kg / 0.42 kg/kWh = 100 kWh
        assert equiv["kWh_electricidad"] == 100.0

    def test_equivalencias_calculation_trees(self):
        """Test tree planting equivalency"""
        equiv = _calculate_equivalencias(20.0)  # 20 kg CO2

        # 20 kg / 20 kg/year = 1 tree
        assert equiv["arboles_plantados_1_ano"] == 1.0

    def test_equivalencias_zero(self):
        """Test equivalencies for zero CO2"""
        equiv = _calculate_equivalencias(0.0)

        assert equiv["km_coche_gasolina"] == 0.0
        assert equiv["kWh_electricidad"] == 0.0
        assert equiv["arboles_plantados_1_ano"] == 0.0


class TestCarbonReport:
    """Test carbon impact report generation."""

    def test_empty_transaction_list(self):
        """Test report with empty transaction list"""
        report = get_carbon_report([])

        assert report["total_transacciones"] == 0
        assert report["total_kg_salvados"] == 0.0
        assert report["total_co2_evitado_kg"] == 0.0
        assert report["impacto_promedio_por_transaccion_kg"] == 0.0

    def test_report_structure(self):
        """Test report has correct structure"""
        report = get_carbon_report([])

        assert "periodo" in report
        assert "total_transacciones" in report
        assert "total_kg_salvados" in report
        assert "total_co2_evitado_kg" in report
        assert "equivalencias" in report
        assert "impacto_promedio_por_transaccion_kg" in report
        assert "impacto_promedio_por_kg" in report


class TestSectorFootprints:
    """Test sector footprint data."""

    def test_get_sector_footprints_returns_dict(self):
        """Test that function returns dictionary"""
        footprints = get_sector_footprints()

        assert isinstance(footprints, dict)
        assert len(footprints) > 0

    def test_sector_footprints_have_required_fields(self):
        """Test that each sector has required fields"""
        footprints = get_sector_footprints()

        for categoria, data in footprints.items():
            assert "valor" in data
            assert "descripcion" in data
            assert "rango" in data

    def test_sector_footprints_values_match_constants(self):
        """Test that footprint values match CO2_FOOTPRINTS"""
        footprints = get_sector_footprints()

        for categoria in CO2_FOOTPRINTS.keys():
            assert footprints[categoria]["valor"] == CO2_FOOTPRINTS[categoria]

    def test_sector_footprints_carnes_highest(self):
        """Test that meat has highest footprint"""
        footprints = get_sector_footprints()

        all_values = [data["valor"] for data in footprints.values()]
        assert footprints["carnes"]["valor"] == max(all_values)

    def test_sector_footprints_verduras_lowest(self):
        """Test that vegetables have lowest footprint"""
        footprints = get_sector_footprints()

        all_values = [data["valor"] for data in footprints.values()]
        assert footprints["verduras"]["valor"] == min(all_values)
