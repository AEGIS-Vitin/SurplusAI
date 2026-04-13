"""
Tests for compliance module and legal use hierarchy.
"""

import pytest
from datetime import datetime, timedelta
import compliance
import models


def test_product_state_before_best_before():
    """Test determining product state before best-before date"""
    now = datetime.utcnow()
    best_before = now + timedelta(days=5)
    expiry = best_before + timedelta(days=5)

    state = compliance.determine_product_state(best_before, expiry, now)
    assert state == compliance.EstadoProducto.antes_fecha_consumo


def test_product_state_after_best_before():
    """Test determining product state after best-before but before expiry"""
    now = datetime.utcnow()
    best_before = now - timedelta(days=1)
    expiry = now + timedelta(days=5)

    state = compliance.determine_product_state(best_before, expiry, now)
    assert state == compliance.EstadoProducto.despues_fecha_consumo


def test_product_state_before_expiry():
    """Test determining product state close to expiry"""
    now = datetime.utcnow()
    best_before = now - timedelta(days=5)
    expiry = now + timedelta(hours=12)

    state = compliance.determine_product_state(best_before, expiry, now)
    assert state == compliance.EstadoProducto.antes_fecha_expiracion


def test_product_state_after_expiry():
    """Test determining product state after expiry"""
    now = datetime.utcnow()
    best_before = now - timedelta(days=10)
    expiry = now - timedelta(days=1)

    state = compliance.determine_product_state(best_before, expiry, now)
    assert state == compliance.EstadoProducto.despues_fecha_expiracion


def test_permitted_uses_before_best_before():
    """Test permitted uses before best-before date"""
    state = compliance.EstadoProducto.antes_fecha_consumo

    uses = compliance.get_permitted_uses(state, compliance.Categoria.frutas)

    # All uses should be permitted
    assert compliance.UsoFinal.prevencion.value in uses
    assert compliance.UsoFinal.donacion_consumo.value in uses
    assert compliance.UsoFinal.transformacion.value in uses


def test_permitted_uses_after_expiry():
    """Test permitted uses after expiry date"""
    state = compliance.EstadoProducto.despues_fecha_expiracion

    uses = compliance.get_permitted_uses(state, compliance.Categoria.frutas)

    # Only composting and biogas should be allowed
    assert compliance.UsoFinal.compostaje.value in uses
    assert compliance.UsoFinal.biogas.value in uses
    assert compliance.UsoFinal.donacion_consumo.value not in uses


def test_validate_use_allowed_success():
    """Test validating an allowed use"""
    state = compliance.EstadoProducto.antes_fecha_consumo
    uso = compliance.UsoFinal.donacion_consumo.value

    is_allowed, reason = compliance.validate_use_allowed(
        state,
        compliance.Categoria.frutas,
        uso
    )

    assert is_allowed is True
    assert reason is None


def test_validate_use_blocked():
    """Test validating a blocked use"""
    state = compliance.EstadoProducto.despues_fecha_expiracion
    uso = compliance.UsoFinal.donacion_consumo.value

    is_allowed, reason = compliance.validate_use_allowed(
        state,
        compliance.Categoria.frutas,
        uso
    )

    assert is_allowed is False
    assert reason is not None
    assert "expiración" in reason.lower() or "expir" in reason.lower()


def test_generate_compliance_data():
    """Test generating compliance documentation data"""
    state = compliance.EstadoProducto.antes_fecha_consumo

    data = compliance.generate_compliance_data(
        transaccion_id=1,
        lote_id=1,
        generador_id=1,
        receptor_id=1,
        generador_nombre="Test Generator",
        receptor_nombre="Test Receptor",
        producto="Test Product",
        cantidad_kg=100.0,
        precio_final=50.0,
        uso_final=compliance.UsoFinal.donacion_consumo.value,
        estado_producto=state
    )

    assert data["tipo_documento"] == "compliance_legal"
    assert data["ley"] == "Ley 1/2025 - Prevención de pérdida y desperdicio de alimentos"
    assert data["transaccion_id"] == 1
    assert data["generador"]["nombre"] == "Test Generator"
    assert data["receptor"]["nombre"] == "Test Receptor"
    assert data["producto"]["cantidad_kg"] == 100.0
    assert data["producto"]["estado"] == "antes_fecha_consumo"
    assert data["conformidad"]["cumple_ley_1_2025"] is True


def test_compliance_hierarchy():
    """Test getting compliance hierarchy description"""
    hierarchy = compliance.ComplianceChecker.get_use_hierarchy_description()

    assert isinstance(hierarchy, dict)
    assert len(hierarchy) == 8

    # Check structure
    for level, data in hierarchy.items():
        assert "nombre" in data
        assert "descripcion" in data
        assert "prioridad" in data


def test_restricted_uses_for_meat_after_best_before():
    """Test that meat products have restricted uses after best-before"""
    state = compliance.EstadoProducto.despues_fecha_consumo

    uses = compliance.get_permitted_uses(state, compliance.Categoria.carnes)

    # Meat after best-before should have more restrictions
    assert compliance.UsoFinal.donacion_consumo.value not in uses


def test_vegetables_permitted_after_best_before():
    """Test that vegetables are more permissive after best-before"""
    state = compliance.EstadoProducto.despues_fecha_consumo

    uses_vegetables = compliance.get_permitted_uses(
        state,
        compliance.Categoria.verduras
    )
    uses_meat = compliance.get_permitted_uses(
        state,
        compliance.Categoria.carnes
    )

    # Vegetables should have more permitted uses than meat
    assert len(uses_vegetables) >= len(uses_meat)
