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

# PostGIS support is opt-in via USE_POSTGIS env var.
# When enabled (Neon.tech with `CREATE EXTENSION postgis;`, or a self-hosted
# Postgres with the extension), the `ubicacion` columns use a proper POINT
# geometry. When disabled (default — works on vanilla Postgres, Railway
# Postgres, SQLite in tests), they fall back to a String column and distance
# queries should use `geopy.distance.geodesic` on lat/lon parsed from the
# stored value or from separate fields.
Geometry = None
USE_POSTGIS = os.getenv("USE_POSTGIS", "false").lower() == "true"
if USE_POSTGIS and os.getenv("TESTING", "false").lower() != "true":
    try:
        from geoalchemy2 import Geometry
    except ImportError:
        Geometry = None

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/marketplace_db")

# SQLAlchemy 2.x requires `postgresql://`, but many providers (Neon, Heroku)
# hand out `postgres://`. Normalize for convenience.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# pool_pre_ping avoids stale connections on managed Postgres (Neon/Railway
# close idle connections).
engine_kwargs = {"echo": False, "pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs.pop("pool_pre_ping", None)

engine = create_engine(DATABASE_URL, **engine_kwargs)
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

    # ---- Revenue split (P0.2 / P0.3 — VERDICT_BUSINESS_MODEL.md) ----
    # "GMV TRESAAA Surplus" (what we invoice) = service_fee + logistics_fee + biomass_revenue.
    # `precio_final` is the price of the *food itself* (often €0 or symbolic).
    # Keeping them as separate columns lets the /dashboard endpoint present a
    # clean split without heuristics.
    service_fee_eur = Column(Float, default=0.0)
    logistics_fee_eur = Column(Float, default=0.0)
    biomass_revenue_eur = Column(Float, default=0.0)
    outcome = Column(String(32))  # see models.OutcomeTransaccion

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


class SubscriptionPlanDB(Base):
    """TRESAAA Surplus pricing tiers — seeded at startup from the canonical
    (Starter / Pro / Enterprise) config in `seed_subscription_plans`.

    Per VERDICT_BUSINESS_MODEL.md:
        * Starter    — €0/mes, ≤ 5 lotes/mes, features básicas
        * Pro        — €199/mes, ≤ 20 lotes/mes, compliance docs + dashboard + API read-only
        * Enterprise — €4.999/mes base + negociado, unlimited, API write + gestor cuenta + SLA
    """

    __tablename__ = "subscription_plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), unique=True, nullable=False)
    price_monthly_eur = Column(Float, nullable=False)
    max_lots_month = Column(Integer)  # NULL = unlimited
    includes = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WaitlistEntryDB(Base):
    __tablename__ = "waitlist_entries"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(255), nullable=False)
    empresa = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    telefono = Column(String(50), default="")
    sector = Column(String(100), default="")
    contacted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PdfCertificateDB(Base):
    """Certificados PDF de trazabilidad — producto desperdicio.es €1.99/mes.

    Cada fila representa un certificado generado por un usuario para documentar
    qué hizo con un producto alimentario (donación, compost, alimentación animal, etc.).
    El PDF contiene hash SHA-256 + QR de verificación pública que apunta a /verify/{hash}.
    """
    __tablename__ = "pdf_certificates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # nullable para tier Free sin auth
    user_email = Column(String(255), nullable=False, index=True)
    business_name = Column(String(255), nullable=False)
    nif = Column(String(32), nullable=True)
    fecha_evento = Column(DateTime, nullable=False)
    producto = Column(String(500), nullable=False)
    cantidad = Column(Float, nullable=False)
    unidad = Column(String(32), default="kg", nullable=False)  # kg, unidades, litros
    destino = Column(String(64), nullable=False)  # outcome: food_bank, donated_ong, cattle_feed, compost, energy_biogas
    destino_detalle = Column(String(255), nullable=True)  # ej. "Banco Alimentos Valencia"
    foto_url = Column(String(500), nullable=True)
    pdf_url = Column(String(500), nullable=True)
    hash_sha256 = Column(String(64), unique=True, nullable=False, index=True)
    inventory_item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=True, index=True)  # link si vino de inventario
    plan = Column(String(32), default="free", nullable=False)  # free, solo, pro, plus
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class NotificationChannelDB(Base):
    """Canales de notificación por usuario (web push + Telegram + email).

    Un usuario puede tener varios canales activos. Cuando un item del inventario
    se acerca a la fecha de caducidad, notifications_v2.send_alert() recorre
    todos los canales del user y manda la alerta.
    """
    __tablename__ = "notification_channels"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    user_email = Column(String(255), nullable=False, index=True)
    channel_type = Column(String(32), nullable=False, index=True)  # web_push | telegram | email
    payload = Column(JSON, nullable=False)  # web_push: subscription dict; telegram: {chat_id}
    enabled = Column(Boolean, default=True, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class InventoryItemDB(Base):
    """Inventario de productos del cliente con fechas de caducidad.

    Producto desperdicio.es: el cliente añade lo que compra → recibe alertas
    cuando se acerca la caducidad → puede generar certificado de gestión final.
    En Phase 2, FactuLens lo pre-llena automáticamente desde OCR factura proveedor.
    """
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    nombre = Column(String(255), nullable=False)
    categoria = Column(String(64), nullable=True)  # frutas, verduras, lacteos, carnes, panaderia, otros
    cantidad = Column(Float, nullable=False)
    unidad = Column(String(32), default="kg", nullable=False)
    fecha_compra = Column(DateTime, nullable=True)
    fecha_caducidad = Column(DateTime, nullable=False, index=True)
    lote = Column(String(64), nullable=True)
    proveedor = Column(String(255), nullable=True)
    proveedor_nif = Column(String(32), nullable=True)
    precio_unitario = Column(Float, nullable=True)  # para histórico precios cross-vertical FactuLens
    foto_url = Column(String(500), nullable=True)
    status = Column(String(32), default="vigente", nullable=False, index=True)  # vigente, consumido, donado, caducado, retirado
    notas = Column(Text, nullable=True)
    source = Column(String(32), default="manual", nullable=False)  # manual, factulens_ocr, api
    factura_id = Column(Integer, nullable=True)  # referencia futura a FactuLens invoice_id
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def _ensure_transacciones_columns():
    """Idempotent ALTER TABLE to add the P0.2/P0.3 revenue-split columns.

    The app was originally shipped without `service_fee_eur`,
    `logistics_fee_eur`, `biomass_revenue_eur` or `outcome`. Railway's
    Postgres keeps existing rows across deploys, so we can't drop+recreate.
    This runs on startup and is safe to call multiple times.
    """
    if DATABASE_URL.startswith("sqlite"):
        # SQLite is only used in tests, where create_all() already produces
        # the full schema; ALTER TABLE ... IF NOT EXISTS doesn't exist here.
        return
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE transacciones "
                "ADD COLUMN IF NOT EXISTS service_fee_eur DOUBLE PRECISION DEFAULT 0"
            ))
            conn.execute(text(
                "ALTER TABLE transacciones "
                "ADD COLUMN IF NOT EXISTS logistics_fee_eur DOUBLE PRECISION DEFAULT 0"
            ))
            conn.execute(text(
                "ALTER TABLE transacciones "
                "ADD COLUMN IF NOT EXISTS biomass_revenue_eur DOUBLE PRECISION DEFAULT 0"
            ))
            conn.execute(text(
                "ALTER TABLE transacciones "
                "ADD COLUMN IF NOT EXISTS outcome VARCHAR(32)"
            ))
    except Exception as e:
        # Don't kill the app on a hot deploy; log and move on.
        print(f"[init_db] _ensure_transacciones_columns warn: {e}", flush=True)


def seed_subscription_plans():
    """Idempotent seed of the 3 canonical pricing tiers.

    Source of truth: VERDICT_BUSINESS_MODEL.md · consensus Grok+Gemini+GPT-4o.
    Safe to re-run — uses INSERT ... ON CONFLICT DO UPDATE so changes to the
    feature-matrix ship on the next deploy.
    """
    plans = [
        {
            "name": "Starter",
            "price_monthly_eur": 0.0,
            "max_lots_month": 5,
            "includes": {
                "feature_matching_automatico": True,
                "feature_compliance_docs": True,
                "feature_dashboard": False,
                "feature_api_read": False,
                "feature_api_write": False,
                "feature_account_manager": False,
                "sla": None,
                "target": "Autónomos, pequeñas HORECA, piloto Ley 1/2025",
            },
        },
        {
            "name": "Pro",
            "price_monthly_eur": 199.0,
            "max_lots_month": 20,
            "includes": {
                "feature_matching_automatico": True,
                "feature_compliance_docs": True,
                "feature_dashboard": True,
                "feature_api_read": True,
                "feature_api_write": False,
                "feature_account_manager": False,
                "sla": "99.5% uptime, soporte 24h",
                "target": "Restaurantes grupo medio, industrias regionales, cadenas locales",
            },
        },
        {
            "name": "Enterprise",
            "price_monthly_eur": 4999.0,
            "max_lots_month": None,  # unlimited
            "includes": {
                "feature_matching_automatico": True,
                "feature_compliance_docs": True,
                "feature_dashboard": True,
                "feature_api_read": True,
                "feature_api_write": True,
                "feature_account_manager": True,
                "sla": "99.9% uptime, 4h response, gestor de cuenta dedicado",
                "target": "Cadenas de retail, grupos hospitalarios, catering industrial",
                "negotiable_surcharges": "Por volumen, ESG reporting custom, integración ERP/SAP",
            },
        },
    ]

    session = SessionLocal()
    try:
        for p in plans:
            existing = session.query(SubscriptionPlanDB).filter_by(name=p["name"]).first()
            if existing:
                existing.price_monthly_eur = p["price_monthly_eur"]
                existing.max_lots_month = p["max_lots_month"]
                existing.includes = p["includes"]
            else:
                session.add(SubscriptionPlanDB(**p))
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[init_db] seed_subscription_plans warn: {e}", flush=True)
    finally:
        session.close()


# Database initialization
def init_db():
    """Create all tables + idempotent column/seed patches."""
    Base.metadata.create_all(bind=engine)
    _ensure_transacciones_columns()
    seed_subscription_plans()


def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
