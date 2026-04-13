"""
Tests for lot (lote) CRUD operations.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import models
import database


def test_list_lots(client: TestClient, test_lote):
    """Test listing all active lots"""
    response = client.get("/lots")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert data[0]["producto"] == "Manzanas Golden"
    assert data[0]["estado"] == "activo"


def test_get_lot_by_id(client: TestClient, test_lote):
    """Test getting a specific lot"""
    response = client.get(f"/lots/{test_lote.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == test_lote.id
    assert data["producto"] == "Manzanas Golden"
    assert data["cantidad_kg"] == 100.0


def test_get_nonexistent_lot(client: TestClient):
    """Test getting a non-existent lot"""
    response = client.get("/lots/999999")

    assert response.status_code == 404
    assert "no encontrado" in response.json()["detail"].lower()


def test_create_lot_with_auth(
    client: TestClient,
    test_generador,
    valid_auth_token,
    db: Session
):
    """Test creating a new lot with valid authentication"""
    future_date = datetime.utcnow() + timedelta(days=3)

    response = client.post(
        "/lots",
        json={
            "generador_id": test_generador.id,
            "producto": "Naranjas Valencia",
            "categoria": "frutas",
            "cantidad_kg": 250.0,
            "ubicacion_lat": 40.4168,
            "ubicacion_lon": -3.7038,
            "fecha_limite": future_date.isoformat(),
            "precio_base": 75.0,
            "temperatura_conservacion": 5.0,
            "lote_origen": "LOTE_002"
        },
        headers={"Authorization": f"Bearer {valid_auth_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["producto"] == "Naranjas Valencia"
    assert data["cantidad_kg"] == 250.0
    assert data["estado"] == "activo"
    assert data["precio_actual"] > 0


def test_create_lot_without_auth(client: TestClient, test_generador):
    """Test that creating lot without auth fails"""
    future_date = datetime.utcnow() + timedelta(days=3)

    response = client.post(
        "/lots",
        json={
            "generador_id": test_generador.id,
            "producto": "Plátanos",
            "categoria": "frutas",
            "cantidad_kg": 100.0,
            "ubicacion_lat": 40.0,
            "ubicacion_lon": -3.0,
            "fecha_limite": future_date.isoformat(),
            "precio_base": 50.0
        }
    )

    assert response.status_code == 401


def test_create_lot_nonexistent_generator(
    client: TestClient,
    valid_auth_token
):
    """Test creating lot with non-existent generator"""
    future_date = datetime.utcnow() + timedelta(days=3)

    response = client.post(
        "/lots",
        json={
            "generador_id": 999999,
            "producto": "Test Product",
            "categoria": "frutas",
            "cantidad_kg": 100.0,
            "ubicacion_lat": 40.0,
            "ubicacion_lon": -3.0,
            "fecha_limite": future_date.isoformat(),
            "precio_base": 50.0
        },
        headers={"Authorization": f"Bearer {valid_auth_token}"}
    )

    assert response.status_code == 404


def test_list_lots_by_category(client: TestClient, test_lote, db: Session):
    """Test filtering lots by category"""
    response = client.get("/lots?categoria=frutas")

    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert all(lot["categoria"] == "frutas" for lot in data)


def test_list_lots_by_price(client: TestClient, test_lote, db: Session):
    """Test filtering lots by max price"""
    response = client.get("/lots?precio_max=60")

    assert response.status_code == 200
    data = response.json()
    # Should include our test lot (precio_actual = 50)
    assert any(lot["id"] == test_lote.id for lot in data)


def test_lot_has_bid_count(client: TestClient, test_lote, test_puja):
    """Test that lot response includes bid count"""
    response = client.get(f"/lots/{test_lote.id}")

    # Note: In the list endpoint, bids are counted
    response = client.get("/lots")
    assert response.status_code == 200
    data = response.json()

    if data:
        assert "num_bids" in data[0]


def test_dynamic_price_calculation(
    client: TestClient,
    test_generador,
    valid_auth_token,
    db: Session
):
    """Test that dynamic price is calculated when lot is created"""
    future_date = datetime.utcnow() + timedelta(days=7)

    response = client.post(
        "/lots",
        json={
            "generador_id": test_generador.id,
            "producto": "Tomates",
            "categoria": "verduras",
            "cantidad_kg": 200.0,
            "ubicacion_lat": 40.4168,
            "ubicacion_lon": -3.7038,
            "fecha_limite": future_date.isoformat(),
            "precio_base": 100.0
        },
        headers={"Authorization": f"Bearer {valid_auth_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["precio_actual"] <= data["precio_base"]
    assert data["precio_actual"] > 0
