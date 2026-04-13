"""
Tests for dynamic pricing module.
"""

import pytest
from datetime import datetime, timedelta
import pricing


def test_calculate_dynamic_price_no_bids():
    """Test dynamic price calculation with no bids"""
    base_price = 100.0
    now = datetime.utcnow()
    limit_date = now + timedelta(days=7)

    price = pricing.calculate_dynamic_price(
        base_price,
        limit_date,
        now,
        num_bids=0,
        categoria="frutas"
    )

    assert price <= base_price
    assert price > base_price * 0.10  # Should be above minimum floor


def test_calculate_dynamic_price_with_bids():
    """Test that price increases with more bids (demand factor)"""
    base_price = 100.0
    now = datetime.utcnow()
    limit_date = now + timedelta(days=7)

    price_no_bids = pricing.calculate_dynamic_price(
        base_price,
        limit_date,
        now,
        num_bids=0,
        categoria="frutas"
    )

    price_with_bids = pricing.calculate_dynamic_price(
        base_price,
        limit_date,
        now,
        num_bids=3,
        categoria="frutas"
    )

    # Price should increase with demand
    assert price_with_bids > price_no_bids


def test_calculate_dynamic_price_time_decay():
    """Test that price decreases as expiry date approaches"""
    base_price = 100.0
    now = datetime.utcnow()

    # Lot expires in 7 days
    limit_date_far = now + timedelta(days=7)
    pub_date = now - timedelta(days=1)

    price_early = pricing.calculate_dynamic_price(
        base_price,
        limit_date_far,
        pub_date,
        num_bids=0,
        categoria="frutas"
    )

    # Lot expires in 1 day
    limit_date_soon = now + timedelta(days=1)

    price_late = pricing.calculate_dynamic_price(
        base_price,
        limit_date_soon,
        pub_date,
        num_bids=0,
        categoria="frutas"
    )

    # Price should be lower for lot expiring sooner
    assert price_late < price_early


def test_calculate_dynamic_price_expired():
    """Test price for expired lot (should be minimum)"""
    base_price = 100.0
    now = datetime.utcnow()
    expired_date = now - timedelta(days=1)

    price = pricing.calculate_dynamic_price(
        base_price,
        expired_date,
        now,
        num_bids=0,
        categoria="frutas"
    )

    # Should be at minimum (10% of base)
    assert price == max(base_price * 0.10, 0.01)


def test_price_floor_applied():
    """Test that price never goes below 10% of base"""
    base_price = 100.0
    now = datetime.utcnow()
    expired_date = now - timedelta(days=100)  # Very expired

    price = pricing.calculate_dynamic_price(
        base_price,
        expired_date,
        now,
        num_bids=0,
        categoria="frutas"
    )

    assert price >= base_price * 0.10


def test_category_scarcity_factors():
    """Test that different categories have different prices"""
    base_price = 100.0
    now = datetime.utcnow()
    limit_date = now + timedelta(days=7)

    # Meat is most valuable
    price_meat = pricing.calculate_dynamic_price(
        base_price,
        limit_date,
        now,
        num_bids=0,
        categoria="carnes"
    )

    # Vegetables are less valuable
    price_vegetables = pricing.calculate_dynamic_price(
        base_price,
        limit_date,
        now,
        num_bids=0,
        categoria="verduras"
    )

    # Meat should be more expensive
    assert price_meat > price_vegetables


def test_get_price_breakdown():
    """Test getting detailed price breakdown"""
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

    assert "precio_base" in breakdown
    assert "precio_final" in breakdown
    assert "dias_restantes" in breakdown
    assert "tiempo_factor" in breakdown
    assert "demanda_factor" in breakdown
    assert "scarcity_factor" in breakdown
    assert breakdown["precio_base"] == base_price


def test_suggest_price_for_generator():
    """Test price suggestion for new lot"""
    suggested = pricing.suggest_price_for_generator(
        categoria="frutas",
        cantidad_kg=100.0,
        tipo_generador="retail",
        dias_hasta_expiry=7
    )

    assert suggested > 0
    assert isinstance(suggested, float)


def test_price_suggestion_bulk_discount():
    """Test that bulk quantities get discount"""
    small_qty = pricing.suggest_price_for_generator(
        categoria="frutas",
        cantidad_kg=50.0,
        tipo_generador="retail"
    )

    large_qty = pricing.suggest_price_for_generator(
        categoria="frutas",
        cantidad_kg=1000.0,
        tipo_generador="retail"
    )

    # Larger quantity should have lower per-unit price
    assert large_qty < small_qty


def test_price_suggestion_by_generator_type():
    """Test that different generator types get different prices"""
    retail_price = pricing.suggest_price_for_generator(
        categoria="frutas",
        cantidad_kg=100.0,
        tipo_generador="retail"
    )

    industria_price = pricing.suggest_price_for_generator(
        categoria="frutas",
        cantidad_kg=100.0,
        tipo_generador="industria"
    )

    # Industrial surpluses are cheaper
    assert industria_price < retail_price
