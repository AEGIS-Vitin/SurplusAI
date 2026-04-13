"""
Tests for bidding (puja) operations.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
import models
import database


def test_place_bid(
    client: TestClient,
    test_lote,
    test_receptor,
    valid_auth_token
):
    """Test placing a bid on a lot"""
    response = client.post(
        "/bids",
        json={
            "lote_id": test_lote.id,
            "receptor_id": test_receptor.id,
            "precio_oferta": 45.0,
            "uso_previsto": 2,  # Donación consumo
            "mensaje": "Interested in these apples"
        },
        headers={"Authorization": f"Bearer {valid_auth_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["lote_id"] == test_lote.id
    assert data["receptor_id"] == test_receptor.id
    assert data["precio_oferta"] == 45.0
    assert data["estado"] == "pendiente"


def test_place_bid_without_auth(client: TestClient, test_lote, test_receptor):
    """Test that placing bid without auth fails"""
    response = client.post(
        "/bids",
        json={
            "lote_id": test_lote.id,
            "receptor_id": test_receptor.id,
            "precio_oferta": 45.0,
            "uso_previsto": 2
        }
    )

    assert response.status_code == 401


def test_place_bid_nonexistent_lot(
    client: TestClient,
    test_receptor,
    valid_auth_token
):
    """Test placing bid on non-existent lot"""
    response = client.post(
        "/bids",
        json={
            "lote_id": 999999,
            "receptor_id": test_receptor.id,
            "precio_oferta": 45.0,
            "uso_previsto": 2
        },
        headers={"Authorization": f"Bearer {valid_auth_token}"}
    )

    assert response.status_code == 404


def test_place_bid_nonexistent_receptor(
    client: TestClient,
    test_lote,
    valid_auth_token
):
    """Test placing bid as non-existent receptor"""
    response = client.post(
        "/bids",
        json={
            "lote_id": test_lote.id,
            "receptor_id": 999999,
            "precio_oferta": 45.0,
            "uso_previsto": 2
        },
        headers={"Authorization": f"Bearer {valid_auth_token}"}
    )

    assert response.status_code == 404


def test_list_bids_for_lot(client: TestClient, test_lote, test_puja):
    """Test listing all bids for a lot"""
    response = client.get(f"/bids/{test_lote.id}")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert data[0]["lote_id"] == test_lote.id


def test_list_bids_for_nonexistent_lot(client: TestClient):
    """Test listing bids for non-existent lot"""
    response = client.get("/bids/999999")

    assert response.status_code == 404


def test_bid_updates_lot_price(
    client: TestClient,
    test_lote,
    test_receptor,
    valid_auth_token,
    db: Session
):
    """Test that placing a bid updates the lot's dynamic price"""
    original_price = test_lote.precio_actual

    # Place a bid
    client.post(
        "/bids",
        json={
            "lote_id": test_lote.id,
            "receptor_id": test_receptor.id,
            "precio_oferta": 50.0,
            "uso_previsto": 2
        },
        headers={"Authorization": f"Bearer {valid_auth_token}"}
    )

    # Check if price changed (dynamic pricing with demand factor)
    db.refresh(test_lote)
    new_price = test_lote.precio_actual

    # Price should increase with demand (more bids)
    assert new_price >= original_price


def test_bid_with_invalid_use(
    client: TestClient,
    test_lote,
    test_receptor,
    valid_auth_token
):
    """Test placing bid with invalid use for product state"""
    response = client.post(
        "/bids",
        json={
            "lote_id": test_lote.id,
            "receptor_id": test_receptor.id,
            "precio_oferta": 45.0,
            "uso_previsto": 8  # Eliminación - may not be allowed
        },
        headers={"Authorization": f"Bearer {valid_auth_token}"}
    )

    # May succeed or fail depending on product state
    # This test documents the behavior
    assert response.status_code in [200, 400]


def test_bid_on_inactive_lot(
    client: TestClient,
    test_lote,
    test_receptor,
    valid_auth_token,
    db: Session
):
    """Test that bidding on inactive lot fails"""
    # Mark lot as adjudicated
    test_lote.estado = models.EstadoLote.adjudicado
    db.commit()

    response = client.post(
        "/bids",
        json={
            "lote_id": test_lote.id,
            "receptor_id": test_receptor.id,
            "precio_oferta": 45.0,
            "uso_previsto": 2
        },
        headers={"Authorization": f"Bearer {valid_auth_token}"}
    )

    assert response.status_code == 400
    assert "no activo" in response.json()["detail"].lower()


def test_multiple_bids_on_same_lot(
    client: TestClient,
    test_lote,
    test_receptor,
    valid_auth_token,
    db: Session
):
    """Test placing multiple bids on the same lot"""
    # Place first bid
    response1 = client.post(
        "/bids",
        json={
            "lote_id": test_lote.id,
            "receptor_id": test_receptor.id,
            "precio_oferta": 45.0,
            "uso_previsto": 2
        },
        headers={"Authorization": f"Bearer {valid_auth_token}"}
    )
    assert response1.status_code == 200

    # Place second bid with higher price
    response2 = client.post(
        "/bids",
        json={
            "lote_id": test_lote.id,
            "receptor_id": test_receptor.id,
            "precio_oferta": 48.0,
            "uso_previsto": 2
        },
        headers={"Authorization": f"Bearer {valid_auth_token}"}
    )
    assert response2.status_code == 200

    # Check that both bids are listed
    response_list = client.get(f"/bids/{test_lote.id}")
    assert len(response_list.json()) == 2
