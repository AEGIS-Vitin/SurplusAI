"""
Advanced tests for pricing engine covering edge cases and complex scenarios.
"""

import pytest
from datetime import datetime, timedelta
import pricing


class TestDynamicPricingEdgeCases:
    """Edge case tests for dynamic pricing calculation"""

    def test_price_with_zero_base(self):
        """Test pricing when base price is zero"""
        base_price = 0.0
        now = datetime.utcnow()
        limit_date = now + timedelta(days=5)

        price = pricing.calculate_dynamic_price(
            base_price,
            limit_date,
            now,
            num_bids=0,
            categoria="frutas"
        )

        assert price >= 0
        assert price < 0.01

    def test_price_with_very_high_base(self):
        """Test pricing with very high base price"""
        base_price = 10000.0
        now = datetime.utcnow()
        limit_date = now + timedelta(days=5)

        price = pricing.calculate_dynamic_price(
            base_price,
            limit_date,
            now,
            num_bids=0,
            categoria="carnes"
        )

        assert price > 0
        assert price <= base_price
        assert price >= base_price * 0.10

    def test_price_with_extreme_bids(self):
        """Test pricing with very high number of bids"""
        base_price = 100.0
        now = datetime.utcnow()
        limit_date = now + timedelta(days=5)

        price_low_bids = pricing.calculate_dynamic_price(
            base_price,
            limit_date,
            now,
            num_bids=0,
            categoria="frutas"
        )

        price_many_bids = pricing.calculate_dynamic_price(
            base_price,
            limit_date,
            now,
            num_bids=100,  # Very high number
            categoria="frutas"
        )

        # Price should increase but be capped
        assert price_many_bids > price_low_bids
        assert price_many_bids <= base_price * 1.5  # Should be capped

    def test_price_lot_published_today_expires_tomorrow(self):
        """Test lot published today that expires tomorrow"""
        base_price = 100.0
        now = datetime.utcnow()
        limit_date = now + timedelta(days=1)

        price = pricing.calculate_dynamic_price(
            base_price,
            limit_date,
            now,
            num_bids=0,
            categoria="frutas"
        )

        # Price should be close to minimum (high decay)
        assert price < base_price * 0.5

    def test_price_with_same_publication_and_limit_date(self):
        """Test lot published on same date as expiry"""
        base_price = 100.0
        now = datetime.utcnow()

        price = pricing.calculate_dynamic_price(
            base_price,
            now,  # Expires immediately
            now,
            num_bids=0,
            categoria="frutas"
        )

        # Should handle gracefully
        assert price >= 0
        assert price <= base_price

    def test_price_negative_base_raises_error(self):
        """Test that negative base price raises error"""
        with pytest.raises(ValueError):
            pricing.calculate_dynamic_price(
                -100.0,
                datetime.utcnow() + timedelta(days=5),
                datetime.utcnow(),
                num_bids=0
            )

    def test_price_negative_bids_raises_error(self):
        """Test that negative bid count raises error"""
        with pytest.raises(ValueError):
            pricing.calculate_dynamic_price(
                100.0,
                datetime.utcnow() + timedelta(days=5),
                datetime.utcnow(),
                num_bids=-1
            )

    def test_price_consistency_across_categories(self):
        """Test that price calculation is consistent across all categories"""
        base_price = 100.0
        now = datetime.utcnow()
        limit_date = now + timedelta(days=5)

        categories = ["frutas", "verduras", "carnes", "pescados", "lacteos", "panaderia", "prepared", "otros"]
        prices = {}

        for category in categories:
            price = pricing.calculate_dynamic_price(
                base_price,
                limit_date,
                now,
                num_bids=0,
                categoria=category
            )
            prices[category] = price
            assert price > 0
            assert price <= base_price

        # Verify expected category ordering
        assert prices["carnes"] > prices["frutas"]  # Meat more valuable
        assert prices["pescados"] > prices["verduras"]  # Fish more valuable
        assert prices["panaderia"] < prices["frutas"]  # Bread cheaper

    def test_price_with_unknown_category(self):
        """Test pricing with unknown category"""
        base_price = 100.0
        now = datetime.utcnow()
        limit_date = now + timedelta(days=5)

        price = pricing.calculate_dynamic_price(
            base_price,
            limit_date,
            now,
            num_bids=0,
            categoria="unknown_category"
        )

        # Should use default scarcity factor (1.0)
        assert price > 0


class TestPriceBreakdown:
    """Tests for price breakdown function"""

    def test_breakdown_matches_calculated_price(self):
        """Test that breakdown price_final matches calculate_dynamic_price"""
        base_price = 100.0
        now = datetime.utcnow()
        limit_date = now + timedelta(days=5)

        price = pricing.calculate_dynamic_price(
            base_price,
            limit_date,
            now,
            num_bids=2,
            categoria="frutas"
        )

        breakdown = pricing.get_price_breakdown(
            base_price,
            limit_date,
            now,
            num_bids=2,
            categoria="frutas"
        )

        assert breakdown["precio_final"] == price

    def test_breakdown_has_all_fields(self):
        """Test that breakdown includes all expected fields"""
        base_price = 100.0
        now = datetime.utcnow()
        limit_date = now + timedelta(days=5)

        breakdown = pricing.get_price_breakdown(
            base_price,
            limit_date,
            now,
            num_bids=2,
            categoria="frutas"
        )

        required_fields = [
            "precio_base",
            "precio_final",
            "dias_restantes",
            "tiempo_factor",
            "num_bids",
            "demanda_factor",
            "categoria",
            "scarcity_factor",
            "descuento_porcentaje"
        ]

        for field in required_fields:
            assert field in breakdown

    def test_breakdown_with_zero_base_price(self):
        """Test breakdown calculation with zero base price"""
        breakdown = pricing.get_price_breakdown(
            0.0,
            datetime.utcnow() + timedelta(days=5),
            datetime.utcnow(),
            num_bids=0,
            categoria="frutas"
        )

        assert breakdown["descuento_porcentaje"] == 0  # Division by zero handled

    def test_breakdown_discount_percentage_calculation(self):
        """Test that discount percentage is calculated correctly"""
        base_price = 100.0
        now = datetime.utcnow()
        limit_date = now + timedelta(days=7)

        breakdown = pricing.get_price_breakdown(
            base_price,
            limit_date,
            now,
            num_bids=0,
            categoria="frutas"
        )

        # Manually calculate expected discount
        expected_discount = (1 - breakdown["precio_final"] / base_price) * 100
        assert abs(breakdown["descuento_porcentaje"] - expected_discount) < 0.01


class TestPriceSuggestion:
    """Tests for price suggestion for generators"""

    def test_suggest_price_all_categories(self):
        """Test price suggestion for all categories"""
        categories = ["frutas", "verduras", "carnes", "pescados", "lacteos", "panaderia", "prepared", "otros"]

        for category in categories:
            price = pricing.suggest_price_for_generator(
                categoria=category,
                cantidad_kg=100.0,
                tipo_generador="retail",
                dias_hasta_expiry=7
            )

            assert price > 0
            assert isinstance(price, float)

    def test_suggest_price_all_generator_types(self):
        """Test price suggestion for all generator types"""
        types = ["retail", "horeca", "industria", "primario"]

        prices = {}
        for gen_type in types:
            price = pricing.suggest_price_for_generator(
                categoria="frutas",
                cantidad_kg=100.0,
                tipo_generador=gen_type,
                dias_hasta_expiry=7
            )
            prices[gen_type] = price
            assert price > 0

        # Retail should be more expensive than industrial
        assert prices["retail"] > prices["industria"]

    def test_suggest_price_invalid_quantity_raises_error(self):
        """Test that zero or negative quantity raises error"""
        with pytest.raises(ValueError):
            pricing.suggest_price_for_generator(
                categoria="frutas",
                cantidad_kg=0,
                tipo_generador="retail"
            )

        with pytest.raises(ValueError):
            pricing.suggest_price_for_generator(
                categoria="frutas",
                cantidad_kg=-100,
                tipo_generador="retail"
            )

    def test_suggest_price_invalid_expiry_raises_error(self):
        """Test that invalid expiry raises error"""
        with pytest.raises(ValueError):
            pricing.suggest_price_for_generator(
                categoria="frutas",
                cantidad_kg=100,
                tipo_generador="retail",
                dias_hasta_expiry=0
            )

        with pytest.raises(ValueError):
            pricing.suggest_price_for_generator(
                categoria="frutas",
                cantidad_kg=100,
                tipo_generador="retail",
                dias_hasta_expiry=-5
            )

    def test_suggest_price_bulk_discount_scaling(self):
        """Test that bulk discount scales appropriately"""
        prices = {}

        quantities = [50, 200, 500, 1000]
        for qty in quantities:
            price = pricing.suggest_price_for_generator(
                categoria="frutas",
                cantidad_kg=qty,
                tipo_generador="retail"
            )
            prices[qty] = price

        # Verify decreasing prices with increasing quantities
        assert prices[50] > prices[200]
        assert prices[200] > prices[500]
        assert prices[500] > prices[1000]

    def test_suggest_price_for_unknown_type(self):
        """Test price suggestion with unknown generator type"""
        price = pricing.suggest_price_for_generator(
            categoria="frutas",
            cantidad_kg=100.0,
            tipo_generador="unknown_type",
            dias_hasta_expiry=7
        )

        # Should use default discount
        assert price > 0

    def test_suggest_price_consistency(self):
        """Test that suggestion is consistent across calls"""
        price1 = pricing.suggest_price_for_generator(
            categoria="verduras",
            cantidad_kg=300.0,
            tipo_generador="horeca",
            dias_hasta_expiry=5
        )

        price2 = pricing.suggest_price_for_generator(
            categoria="verduras",
            cantidad_kg=300.0,
            tipo_generador="horeca",
            dias_hasta_expiry=5
        )

        assert price1 == price2


class TestPricingIntegration:
    """Integration tests combining multiple pricing functions"""

    def test_dynamic_price_with_suggested_base(self):
        """Test dynamic pricing using suggested base price"""
        suggested_base = pricing.suggest_price_for_generator(
            categoria="carnes",
            cantidad_kg=500.0,
            tipo_generador="industria",
            dias_hasta_expiry=10
        )

        now = datetime.utcnow()
        limit_date = now + timedelta(days=10)

        dynamic_price = pricing.calculate_dynamic_price(
            suggested_base,
            limit_date,
            now,
            num_bids=2,
            categoria="carnes"
        )

        assert dynamic_price > 0
        assert dynamic_price <= suggested_base
        assert dynamic_price >= suggested_base * 0.10

    def test_price_trajectory_over_time(self):
        """Test how price changes as expiry approaches"""
        base_price = 100.0
        pub_date = datetime.utcnow() - timedelta(days=5)
        exp_date = pub_date + timedelta(days=7)

        prices = []

        # Simulate price over time
        for day_offset in range(8):
            current_date = pub_date + timedelta(days=day_offset)
            price = pricing.calculate_dynamic_price(
                base_price,
                exp_date,
                pub_date,
                num_bids=0,
                categoria="frutas"
            )
            prices.append(price)

        # Prices should generally be decreasing (time decay)
        # Allow for some variation due to rounding
        for i in range(len(prices) - 1):
            # Check that later prices are not much higher than earlier
            assert prices[i + 1] <= prices[i] * 1.01  # Allow 1% variance

    def test_demand_factor_scaling(self):
        """Test that demand factor increases non-linearly"""
        base_price = 100.0
        now = datetime.utcnow()
        limit_date = now + timedelta(days=7)

        prices = {}

        for num_bids in [0, 1, 3, 5, 10]:
            price = pricing.calculate_dynamic_price(
                base_price,
                limit_date,
                now,
                num_bids=num_bids,
                categoria="frutas"
            )
            prices[num_bids] = price

        # Verify increasing prices
        assert prices[0] < prices[1]
        assert prices[1] < prices[3]
        assert prices[3] < prices[5]

        # But growth should plateau
        assert prices[5] <= prices[10]  # Diminishing returns
