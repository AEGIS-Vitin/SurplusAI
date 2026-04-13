"""
SQLAlchemy database setup with PostGIS support.
"""

import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Enum, ForeignKey, Boolean, JSON, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import models

# For SQLite, we use JSON instead of ARRAY
try:
    from sqlalchemy import ARRAY
except ImportError:
    ARRAY = None

# Only import geoalchemy2 if not in test mode and using PostgreSQL
if os.getenv("TESTING", "false").lower() != "true":
    from geoalchemy2 import Geometry
else:
    Geometry = None

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/marketplace_db")

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Database models
class GeneradorDB(Base):
    __tablename__ = "generadores"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(255), nullable=False)
    tipo = Column(Enum(models.TipoGenerador), nullable=False)
    cif = Column(String(20), unique=True, nullable=False, index=True)
    direccion = Column(String(500), nullable=False)
    ubicacion = Column(Geometry("POINT", srid=4326) if Geometry else String(255), nullable=False)
    contacto_email = Column(String(255), nullable=False)
    contacto_telefono = Column(String(20), nullable=False)
    plan_suscripcion = Column(String(50), default="basico")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    lotes = relationship("LoteDB", back_populates="generador")
    transacciones = relationship("TransaccionDB", back_populates="generador")
    predicciones = relationship("PrediccionMatchingDB", back_populates="generador")


class ReceptorDB(Base):
    __tablename__ = "receptores"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(255), nullable=False)
    tipo = Column(Enum(models.TipoReceptor), nullable=False)
    cif = Column(String(20), unique=True, nullable=False, index=True)
    direccion = Column(String(500), nullable=False)
    ubicacion = Column(Geometry("POINT", srid=4326) if Geometry else String(255), nullable=False)
    capacidad_kg_dia = Column(Float, nullable=False)
    # Use JSON instead of ARRAY for SQLite compatibility
    categorias_interes = Column(JSON, default=[])
    licencias = Column(JSON, default=[])
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    pujas = relationship("PujaDB", back_populates="receptor")
    transacciones = relationship("TransaccionDB", back_populates="receptor")
    predicciones = relationship("PrediccionMatchingDB", back_populates="receptor")


class LoteDB(Base):
    __tablename__ = "lotes"

    id = Column(Integer, primary_key=True, index=True)
    generador_id = Column(Integer, ForeignKey("generadores.id"), nullable=False, index=True)
    producto = Column(String(255), nullable=False)
    categoria = Column(Enum(models.Categoria), nullable=False)
    cantidad_kg = Column(Float, nullable=False)
    ubicacion = Column(Geometry("POINT", srid=4326) if Geometry else String(255), nullable=False)
    fecha_publicacion = Column(DateTime, default=datetime.utcnow, nullable=False)
    fecha_limite = Column(DateTime, nullable=False, index=True)
    precio_base = Column(Float, nullable=False)
    precio_actual = Column(Float, nullable=False)
    temperatura_conservacion = Column(Float)
    estado = Column(Enum(models.EstadoLote), default=models.EstadoLote.activo, index=True)
    lote_origen = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    generador = relationship("GeneradorDB", back_populates="lotes")
    pujas = relationship("PujaDB", back_populates="lote")
    transacciones = relationship("TransaccionDB", back_populates="lote")


class PujaDB(Base):
    __tablename__ = "pujas"

    id = Column(Integer, primary_key=True, index=True)
    lote_id = Column(Integer, ForeignKey("lotes.id"), nullable=False, index=True)
    receptor_id = Column(Integer, ForeignKey("receptores.id"), nullable=False, index=True)
    precio_oferta = Column(Float, nullable=False)
    uso_previsto = Column(Enum(models.UsoFinal), nullable=False)
    mensaje = Column(Text)
    estado = Column(Enum(models.EstadoPuja), default=models.EstadoPuja.pendiente)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    lote = relationship("LoteDB", back_populates="pujas")
    receptor = relationship("ReceptorDB", back_populates="pujas")
    transacciones = relationship("TransaccionDB", back_populates="puja")


class TransaccionDB(Base):
    __tablename__ = "transacciones"

    id = Column(Integer, primary_key=True, index=True)
    lote_id = Column(Integer, ForeignKey("lotes.id"), nullable=False, index=True)
    puja_id = Column(Integer, ForeignKey("pujas.id"), nullable=False)
    generador_id = Column(Integer, ForeignKey("generadores.id"), nullable=False, index=True)
    receptor_id = Column(Integer, ForeignKey("receptores.id"), nullable=False, index=True)
    precio_final = Column(Float, nullable=False)
    cantidad_kg = Column(Float, nullable=False)
    uso_final = Column(Enum(models.UsoFinal), nullable=False)
    co2_evitado_kg = Column(Float)
    estado = Column(Enum(models.EstadoTransaccion), default=models.EstadoTransaccion.pendiente)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    lote = relationship("LoteDB", back_populates="transacciones")
    puja = relationship("PujaDB", back_populates="transacciones")
    generador = relationship("GeneradorDB", back_populates="transacciones")
    receptor = relationship("ReceptorDB", back_populates="transacciones")
    compliance_docs = relationship("ComplianceDocDB", back_populates="transaccion")
    carbon_credits = relationship("CarbonCreditDB", back_populates="transaccion")


class ComplianceDocDB(Base):
    __tablename__ = "compliance_docs"

    id = Column(Integer, primary_key=True, index=True)
    transaccion_id = Column(Integer, ForeignKey("transacciones.id"), nullable=False, index=True)
    tipo = Column(Enum(models.TipoComplianceDoc), nullable=False)
    contenido_json = Column(JSON, nullable=False)
    pdf_url = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    transaccion = relationship("TransaccionDB", back_populates="compliance_docs")


class CarbonCreditDB(Base):
    __tablename__ = "carbon_credits"

    id = Column(Integer, primary_key=True, index=True)
    transaccion_id = Column(Integer, ForeignKey("transacciones.id"), nullable=False, index=True)
    co2_evitado_kg = Column(Float, nullable=False)
    tipo_calculo = Column(String(100), nullable=False)
    equivalencias = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    transaccion = relationship("TransaccionDB", back_populates="carbon_credits")


class PrediccionMatchingDB(Base):
    __tablename__ = "predicciones_matching"

    id = Column(Integer, primary_key=True, index=True)
    generador_id = Column(Integer, ForeignKey("generadores.id"), nullable=False, index=True)
    receptor_id = Column(Integer, ForeignKey("receptores.id"), nullable=False, index=True)
    producto_predicho = Column(String(255), nullable=False)
    cantidad_predicha_kg = Column(Float, nullable=False)
    fecha_predicha = Column(DateTime, nullable=False)
    confianza = Column(Float, nullable=False)  # 0.0 to 1.0
    notificado = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    generador = relationship("GeneradorDB", back_populates="predicciones")
    receptor = relationship("ReceptorDB", back_populates="predicciones")


class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    empresa_id = Column(Integer, nullable=False, index=True)
    nombre_empresa = Column(String(255), nullable=False)
    rol = Column(String(50), default="user", nullable=False)  # 'user', 'admin'
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Database initialization
def init_db():
    """Create all tables"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
