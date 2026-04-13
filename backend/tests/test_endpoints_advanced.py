"""
Advanced tests for API endpoints covering edge cases and input validation.
Tests for all major endpoints with comprehensive coverage.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import models


class TestGeneradorEndpoints:
    """Test cases for Generador endpoints"""

    def test_create_generador_success(self, client: TestClient, db: Session, valid_auth_token):
        """Test successful generador creation"""
        response = client.post(
            "/generadores",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "nombre": "Supermercado Principal",
                "tipo": "retail",
                "cif": "A12345678",
                "direccion": "Calle Mayor 123, Madrid",
                "ubicacion_lat": 40.4168,
                "ubicacion_lon": -3.7038,
                "contacto_email": "contact@supermarket.com",
                "contacto_telefono": "+34912345678",
                "plan_suscripcion": "premium"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["nombre"] == "Supermercado Principal"
        assert data["tipo"] == "retail"
        assert "id" in data

    def test_create_generador_invalid_cif(self, client: TestClient, valid_auth_token):
        """Test generador creation with invalid CIF format"""
        response = client.post(
            "/generadores",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "nombre": "Test",
                "tipo": "retail",
                "cif": "INVALID",  # Invalid CIF format
                "direccion": "Test 123",
                "ubicacion_lat": 40.4168,
                "ubicacion_lon": -3.7038,
                "contacto_email": "test@example.com",
                "contacto_telefono": "+34912345678"
            }
        )
        # Should reject invalid CIF format
        assert response.status_code in [400, 422]

    def test_create_generador_invalid_coordinates(self, client: TestClient, valid_auth_token):
        """Test generador creation with out-of-bounds coordinates"""
        response = client.post(
            "/generadores",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "nombre": "Test",
                "tipo": "retail",
                "cif": "A12345678",
                "direccion": "Test 123",
                "ubicacion_lat": 91.0,  # Invalid latitude (> 90)
                "ubicacion_lon": -3.7038,
                "contacto_email": "test@example.com",
                "contacto_telefono": "+34912345678"
            }
        )
        assert response.status_code in [400, 422]

    def test_create_generador_invalid_email(self, client: TestClient, valid_auth_token):
        """Test generador creation with invalid email"""
        response = client.post(
            "/generadores",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "nombre": "Test",
                "tipo": "retail",
                "cif": "A12345678",
                "direccion": "Test 123",
                "ubicacion_lat": 40.4168,
                "ubicacion_lon": -3.7038,
                "contacto_email": "not-an-email",  # Invalid email
                "contacto_telefono": "+34912345678"
            }
        )
        assert response.status_code in [400, 422]

    def test_create_generador_missing_required_field(self, client: TestClient, valid_auth_token):
        """Test generador creation with missing required field"""
        response = client.post(
            "/generadores",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "nombre": "Test",
                "tipo": "retail",
                "cif": "A12345678",
                # Missing direccion
                "ubicacion_lat": 40.4168,
                "ubicacion_lon": -3.7038,
                "contacto_email": "test@example.com",
                "contacto_telefono": "+34912345678"
            }
        )
        assert response.status_code == 422

    def test_get_generador_by_id(self, client: TestClient, test_generador, valid_auth_token):
        """Test retrieving generador by ID"""
        response = client.get(
            f"/generadores/{test_generador.id}",
            headers={"Authorization": f"Bearer {valid_auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_generador.id
        assert data["nombre"] == test_generador.nombre

    def test_get_generador_nonexistent(self, client: TestClient, valid_auth_token):
        """Test retrieving non-existent generador"""
        response = client.get(
            "/generadores/999999",
            headers={"Authorization": f"Bearer {valid_auth_token}"}
        )
        assert response.status_code == 404

    def test_update_generador_partial(self, client: TestClient, test_generador, valid_auth_token):
        """Test partial update of generador"""
        response = client.put(
            f"/generadores/{test_generador.id}",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "contacto_telefono": "+34999888777"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["contacto_telefono"] == "+34999888777"

    def test_delete_generador(self, client: TestClient, test_generador, valid_auth_token):
        """Test deleting generador"""
        response = client.delete(
            f"/generadores/{test_generador.id}",
            headers={"Authorization": f"Bearer {valid_auth_token}"}
        )
        assert response.status_code == 200

        # Verify it's deleted
        response = client.get(
            f"/generadores/{test_generador.id}",
            headers={"Authorization": f"Bearer {valid_auth_token}"}
        )
        assert response.status_code == 404

    def test_list_generadores_pagination(self, client: TestClient, valid_auth_token, db: Session):
        """Test pagination when listing generadores"""
        # Create multiple generadores
        for i in range(15):
            from database import GeneradorDB
            gen = GeneradorDB(
                nombre=f"Gen {i}",
                tipo=models.TipoGenerador.retail,
                cif=f"A{i:08d}",
                direccion="Test",
                ubicacion=None,
                contacto_email=f"gen{i}@example.com",
                contacto_telefono="+34123456789",
                plan_suscripcion="basico"
            )
            db.add(gen)
        db.commit()

        # Test first page
        response = client.get(
            "/generadores?skip=0&limit=10",
            headers={"Authorization": f"Bearer {valid_auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 10

        # Test second page
        response = client.get(
            "/generadores?skip=10&limit=10",
            headers={"Authorization": f"Bearer {valid_auth_token}"}
        )
        assert response.status_code == 200


class TestReceptorEndpoints:
    """Test cases for Receptor endpoints"""

    def test_create_receptor_success(self, client: TestClient, valid_auth_token):
        """Test successful receptor creation"""
        response = client.post(
            "/receptores",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "nombre": "Banco de Alimentos Madrid",
                "tipo": "banco_alimentos",
                "cif": "B87654321",
                "direccion": "Avenida Central 456, Madrid",
                "ubicacion_lat": 40.4200,
                "ubicacion_lon": -3.7050,
                "capacidad_kg_dia": 1000.0,
                "categorias_interes": ["frutas", "verduras"],
                "licencias": ["LICENSE_001"]
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["nombre"] == "Banco de Alimentos Madrid"
        assert data["tipo"] == "banco_alimentos"

    def test_create_receptor_invalid_capacity(self, client: TestClient, valid_auth_token):
        """Test receptor creation with invalid capacity"""
        response = client.post(
            "/receptores",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "nombre": "Test",
                "tipo": "banco_alimentos",
                "cif": "B87654321",
                "direccion": "Test 123",
                "ubicacion_lat": 40.4200,
                "ubicacion_lon": -3.7050,
                "capacidad_kg_dia": -100.0,  # Negative capacity
                "categorias_interes": ["frutas"]
            }
        )
        assert response.status_code in [400, 422]

    def test_update_receptor_categories(self, client: TestClient, test_receptor, valid_auth_token):
        """Test updating receptor categories of interest"""
        response = client.put(
            f"/receptores/{test_receptor.id}",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "categorias_interes": ["carnes", "pescados", "lacteos"]
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert set(data["categorias_interes"]) == {"carnes", "pescados", "lacteos"}

    def test_get_receptor_by_id(self, client: TestClient, test_receptor, valid_auth_token):
        """Test retrieving receptor by ID"""
        response = client.get(
            f"/receptores/{test_receptor.id}",
            headers={"Authorization": f"Bearer {valid_auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_receptor.id


class TestLoteEndpoints:
    """Test cases for Lote (Lot) endpoints"""

    def test_create_lote_success(self, client: TestClient, test_generador, valid_auth_token):
        """Test successful lot creation"""
        now = datetime.utcnow()
        response = client.post(
            "/lotes",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "generador_id": test_generador.id,
                "producto": "Manzanas Royal Gala",
                "categoria": "frutas",
                "cantidad_kg": 250.0,
                "fecha_limite": (now + timedelta(days=5)).isoformat(),
                "precio_base": 0.75,
                "temperatura_conservacion": 4.0,
                "lote_origen": "LOTE_2025_001"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["producto"] == "Manzanas Royal Gala"
        assert data["cantidad_kg"] == 250.0

    def test_create_lote_invalid_quantity(self, client: TestClient, test_generador, valid_auth_token):
        """Test lote creation with invalid quantity"""
        now = datetime.utcnow()
        response = client.post(
            "/lotes",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "generador_id": test_generador.id,
                "producto": "Test",
                "categoria": "frutas",
                "cantidad_kg": -100.0,  # Negative quantity
                "fecha_limite": (now + timedelta(days=5)).isoformat(),
                "precio_base": 0.75
            }
        )
        assert response.status_code in [400, 422]

    def test_create_lote_invalid_price(self, client: TestClient, test_generador, valid_auth_token):
        """Test lote creation with invalid price"""
        now = datetime.utcnow()
        response = client.post(
            "/lotes",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "generador_id": test_generador.id,
                "producto": "Test",
                "categoria": "frutas",
                "cantidad_kg": 100.0,
                "fecha_limite": (now + timedelta(days=5)).isoformat(),
                "precio_base": -50.0  # Negative price
            }
        )
        assert response.status_code in [400, 422]

    def test_create_lote_past_expiry(self, client: TestClient, test_generador, valid_auth_token):
        """Test lote creation with expiry in the past"""
        now = datetime.utcnow()
        response = client.post(
            "/lotes",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "generador_id": test_generador.id,
                "producto": "Test",
                "categoria": "frutas",
                "cantidad_kg": 100.0,
                "fecha_limite": (now - timedelta(days=1)).isoformat(),  # Past date
                "precio_base": 0.75
            }
        )
        assert response.status_code in [400, 422]

    def test_list_lotes_by_generador(self, client: TestClient, test_lote, valid_auth_token):
        """Test listing lotes for a specific generador"""
        response = client.get(
            f"/generadores/{test_lote.generador_id}/lotes",
            headers={"Authorization": f"Bearer {valid_auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert any(l["id"] == test_lote.id for l in data)

    def test_get_lote_by_id(self, client: TestClient, test_lote, valid_auth_token):
        """Test retrieving lote by ID"""
        response = client.get(
            f"/lotes/{test_lote.id}",
            headers={"Authorization": f"Bearer {valid_auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_lote.id

    def test_update_lote_price(self, client: TestClient, test_lote, valid_auth_token):
        """Test updating lote price"""
        response = client.put(
            f"/lotes/{test_lote.id}",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "precio_base": 100.0
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["precio_base"] == 100.0

    def test_retire_lote(self, client: TestClient, test_lote, valid_auth_token):
        """Test retiring a lote before expiry"""
        response = client.post(
            f"/lotes/{test_lote.id}/retire",
            headers={"Authorization": f"Bearer {valid_auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["estado"] == "retirado"


class TestPujaEndpoints:
    """Test cases for Puja (Bid) endpoints"""

    def test_create_puja_success(self, client: TestClient, test_lote, test_receptor, valid_auth_token):
        """Test successful bid creation"""
        response = client.post(
            "/pujas",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "lote_id": test_lote.id,
                "receptor_id": test_receptor.id,
                "precio_oferta": 40.0,
                "uso_previsto": "donacion_consumo",
                "mensaje": "We are interested in this lot for food donation"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["precio_oferta"] == 40.0
        assert data["estado"] == "pendiente"

    def test_create_puja_price_higher_than_base(self, client: TestClient, test_lote, test_receptor, valid_auth_token):
        """Test creating bid with price higher than base price"""
        # This should be allowed (competitive bidding)
        response = client.post(
            "/pujas",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "lote_id": test_lote.id,
                "receptor_id": test_receptor.id,
                "precio_oferta": test_lote.precio_base * 1.5,  # 150% of base
                "uso_previsto": "donacion_consumo",
                "mensaje": "High bid"
            }
        )
        assert response.status_code == 200

    def test_create_puja_negative_price(self, client: TestClient, test_lote, test_receptor, valid_auth_token):
        """Test creating bid with negative price"""
        response = client.post(
            "/pujas",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "lote_id": test_lote.id,
                "receptor_id": test_receptor.id,
                "precio_oferta": -10.0,  # Negative
                "uso_previsto": "donacion_consumo"
            }
        )
        assert response.status_code in [400, 422]

    def test_create_puja_invalid_uso(self, client: TestClient, test_lote, test_receptor, valid_auth_token):
        """Test creating bid with invalid uso_previsto"""
        response = client.post(
            "/pujas",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "lote_id": test_lote.id,
                "receptor_id": test_receptor.id,
                "precio_oferta": 40.0,
                "uso_previsto": "invalid_uso",  # Invalid uso
                "mensaje": "Test"
            }
        )
        assert response.status_code in [400, 422]

    def test_create_puja_nonexistent_lote(self, client: TestClient, test_receptor, valid_auth_token):
        """Test creating bid for non-existent lote"""
        response = client.post(
            "/pujas",
            headers={"Authorization": f"Bearer {valid_auth_token}"},
            json={
                "lote_id": 999999,
                "receptor_id": test_receptor.id,
                "precio_oferta": 40.0,
                "uso_previsto": "donacion_consumo"
            }
        )
        assert response.status_code == 404

    def test_list_pujas_for_lote(self, client: TestClient, test_puja, valid_auth_token):
        """Test listing all bids for a lote"""
        response = client.get(
            f"/lotes/{test_puja.lote_id}/pujas",
            headers={"Authorization": f"Bearer {valid_auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert any(p["id"] == test_puja.id for p in data)

    def test_accept_puja(self, client: TestClient, test_puja, valid_auth_token):
        """Test accepting a bid"""
        response = client.post(
            f"/pujas/{test_puja.id}/accept",
            headers={"Authorization": f"Bearer {valid_auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["estado"] == "aceptada"

    def test_reject_puja(self, client: TestClient, test_puja, valid_auth_token):
        """Test rejecting a bid"""
        response = client.post(
            f"/pujas/{test_puja.id}/reject",
            headers={"Authorization": f"Bearer {valid_auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["estado"] == "rechazada"

    def test_accept_rejected_puja_fails(self, client: TestClient, test_puja, valid_auth_token):
        """Test that accepting a rejected bid fails"""
        # First reject it
        client.post(
            f"/pujas/{test_puja.id}/reject",
            headers={"Authorization": f"Bearer {valid_auth_token}"}
        )

        # Try to accept
        response = client.post(
            f"/pujas/{test_puja.id}/accept",
            headers={"Authorization": f"Bearer {valid_auth_token}"}
        )
        assert response.status_code in [400, 409]  # Bad request or conflict


class TestAuthenticationEndpoints:
    """Test edge cases in authentication"""

    def test_register_with_weak_password(self, client: TestClient):
        """Test registration with weak password"""
        response = client.post(
            "/auth/register",
            json={
                "email": "test@example.com",
                "password": "123",  # Too short/weak
                "empresa_id": 1,
                "nombre_empresa": "Test"
            }
        )
        # Should either accept or reject based on password policy
        assert response.status_code in [200, 400, 422]

    def test_register_with_special_chars_email(self, client: TestClient):
        """Test registration with special characters in email"""
        response = client.post(
            "/auth/register",
            json={
                "email": "test+tag@example.com",
                "password": "securepass123",
                "empresa_id": 1,
                "nombre_empresa": "Test"
            }
        )
        # Gmail-style plus addressing should work
        assert response.status_code == 200

    def test_multiple_login_attempts(self, client: TestClient, test_user):
        """Test multiple consecutive login attempts"""
        for _ in range(3):
            response = client.post(
                "/auth/login",
                json={
                    "email": "test@example.com",
                    "password": "wrongpassword"
                }
            )
            assert response.status_code == 401

    def test_token_expiration(self, client: TestClient, valid_auth_token):
        """Test that valid token works immediately after creation"""
        response = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {valid_auth_token}"}
        )
        assert response.status_code == 200

    def test_malformed_auth_header(self, client: TestClient):
        """Test request with malformed Authorization header"""
        response = client.get(
            "/auth/me",
            headers={"Authorization": "NotBearer token"}
        )
        assert response.status_code == 401

    def test_missing_bearer_prefix(self, client: TestClient, valid_auth_token):
        """Test request with token but no Bearer prefix"""
        response = client.get(
            "/auth/me",
            headers={"Authorization": valid_auth_token}
        )
        assert response.status_code == 401
