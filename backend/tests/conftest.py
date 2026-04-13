"""
Test fixtures and configuration for AEGIS-FOOD tests.
Uses SQLite in-memory database for testing (without PostGIS).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from fastapi.testclient import TestClient
import sys
import os

# Set testing flag before importing main
os.environ["TESTING"] = "true"

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import models
from main import app, get_db


# SQLite test database (in-memory)
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    """Create a test database session"""
    # Create all tables
    database.Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        database.Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db: Session):
    """Create a test client with test database"""

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    return TestClient(app)


@pytest.fixture(scope="function")
def test_user(db: Session):
    """Create a test user"""
    from auth import hash_password

    user = database.UserDB(
        email="test@example.com",
        hashed_password=hash_password("testpassword"),
        empresa_id=1,
        nombre_empresa="Test Company",
        rol="user"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(scope="function")
def test_generador(db: Session):
    """Create a test generator"""
    from geoalchemy2 import func as gf

    generador = database.GeneradorDB(
        nombre="Test Generator",
        tipo=models.TipoGenerador.retail,
        cif="A12345678",
        direccion="Calle Test 123, Madrid",
        ubicacion=None,  # Skip PostGIS geometry for SQLite
        contacto_email="gen@example.com",
        contacto_telefono="+34123456789",
        plan_suscripcion="basico"
    )
    db.add(generador)
    db.commit()
    db.refresh(generador)
    return generador


@pytest.fixture(scope="function")
def test_receptor(db: Session):
    """Create a test receptor"""
    from geoalchemy2 import func as gf

    receptor = database.ReceptorDB(
        nombre="Test Receptor",
        tipo=models.TipoReceptor.banco_alimentos,
        cif="B87654321",
        direccion="Avenida Test 456, Barcelona",
        ubicacion=None,  # Skip PostGIS geometry for SQLite
        capacidad_kg_dia=500.0,
        categorias_interes=["frutas", "verduras"],
        licencias=["LICENCIA_001"]
    )
    db.add(receptor)
    db.commit()
    db.refresh(receptor)
    return receptor


@pytest.fixture(scope="function")
def test_lote(db: Session, test_generador):
    """Create a test lot"""
    from datetime import datetime, timedelta

    lote = database.LoteDB(
        generador_id=test_generador.id,
        producto="Manzanas Golden",
        categoria=models.Categoria.frutas,
        cantidad_kg=100.0,
        ubicacion=None,  # Skip PostGIS geometry for SQLite
        fecha_publicacion=datetime.utcnow(),
        fecha_limite=datetime.utcnow() + timedelta(days=3),
        precio_base=50.0,
        precio_actual=50.0,
        temperatura_conservacion=4.0,
        estado=models.EstadoLote.activo,
        lote_origen="LOTE_001"
    )
    db.add(lote)
    db.commit()
    db.refresh(lote)
    return lote


@pytest.fixture(scope="function")
def test_puja(db: Session, test_lote, test_receptor):
    """Create a test bid"""
    from datetime import datetime

    puja = database.PujaDB(
        lote_id=test_lote.id,
        receptor_id=test_receptor.id,
        precio_oferta=45.0,
        uso_previsto=models.UsoFinal.donacion_consumo,
        mensaje="Interested in this lot",
        estado=models.EstadoPuja.pendiente,
        created_at=datetime.utcnow()
    )
    db.add(puja)
    db.commit()
    db.refresh(puja)
    return puja


@pytest.fixture(scope="function")
def valid_auth_token(test_user):
    """Create a valid JWT token for test user"""
    from auth import create_access_token

    token = create_access_token(
        data={
            "sub": test_user.email,
            "empresa_id": test_user.empresa_id,
            "rol": test_user.rol
        }
    )
    return token
