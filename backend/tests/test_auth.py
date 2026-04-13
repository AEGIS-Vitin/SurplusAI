"""
Tests for JWT authentication endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
import auth


def test_user_registration(client: TestClient, db: Session):
    """Test user registration endpoint"""
    response = client.post(
        "/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "securepassword123",
            "empresa_id": 123,
            "nombre_empresa": "New Company",
            "rol": "user"
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert data["empresa_id"] == 123
    assert data["nombre_empresa"] == "New Company"
    assert "hashed_password" not in data


def test_user_registration_duplicate_email(client: TestClient, test_user):
    """Test that duplicate email registration fails"""
    response = client.post(
        "/auth/register",
        json={
            "email": "test@example.com",  # Already exists
            "password": "newpassword",
            "empresa_id": 999,
            "nombre_empresa": "Another Company"
        }
    )

    assert response.status_code == 400
    assert "already registered" in response.json()["detail"].lower()


def test_user_login_success(client: TestClient, test_user):
    """Test successful user login"""
    response = client.post(
        "/auth/login",
        json={
            "email": "test@example.com",
            "password": "testpassword"
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == auth.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def test_user_login_invalid_password(client: TestClient, test_user):
    """Test login with invalid password"""
    response = client.post(
        "/auth/login",
        json={
            "email": "test@example.com",
            "password": "wrongpassword"
        }
    )

    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


def test_user_login_nonexistent_email(client: TestClient):
    """Test login with non-existent email"""
    response = client.post(
        "/auth/login",
        json={
            "email": "nonexistent@example.com",
            "password": "anypassword"
        }
    )

    assert response.status_code == 401


def test_get_current_user(client: TestClient, test_user, valid_auth_token):
    """Test getting current user info with valid token"""
    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {valid_auth_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == test_user.email
    assert data["empresa_id"] == test_user.empresa_id


def test_get_current_user_no_token(client: TestClient):
    """Test getting current user without token"""
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_get_current_user_invalid_token(client: TestClient):
    """Test getting current user with invalid token"""
    response = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer invalid.token.here"}
    )
    assert response.status_code == 401


def test_password_hashing():
    """Test password hashing and verification"""
    password = "testpassword123"
    hashed = auth.hash_password(password)

    assert hashed != password
    assert auth.verify_password(password, hashed)
    assert not auth.verify_password("wrongpassword", hashed)


def test_token_creation_and_verification():
    """Test JWT token creation and verification"""
    data = {
        "sub": "test@example.com",
        "empresa_id": 123,
        "rol": "user"
    }

    token = auth.create_access_token(data)
    assert token is not None

    token_data = auth.verify_token(token)
    assert token_data.email == "test@example.com"
    assert token_data.empresa_id == 123
    assert token_data.rol == "user"


def test_expired_token():
    """Test that expired tokens are rejected"""
    from datetime import timedelta
    from jose import JWTError

    data = {"sub": "test@example.com"}
    # Create token with negative expiry (already expired)
    expired_token = auth.create_access_token(
        data,
        expires_delta=timedelta(seconds=-10)
    )

    with pytest.raises(Exception):  # Should raise JWTError
        auth.verify_token(expired_token)
