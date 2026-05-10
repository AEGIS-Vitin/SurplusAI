"""
TRESAAA Surplus: B2B Food Surplus Marketplace
Main FastAPI application with JWT authentication and email notifications.
"""

from fastapi import FastAPI, Depends, HTTPException, Query, Header
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
import math
import os
import re
from dotenv import load_dotenv

import models
import database
import pricing
import compliance
import matching
import auto_matching
import carbon
import auth
import notifications


# ---- TRESAAA Surplus pricing constants (P0.2 — see VERDICT_BUSINESS_MODEL.md) ----
# "Logística: €0.25/km + MÍNIMO €25-30 por recogida (insight Gemini crítico —
#  sin esto te matan las recogidas pequeñas)."
# We go with €25 as the floor, which is also what the frontend advertises.
LOGISTICS_PER_KM_EUR = 0.25
LOGISTICS_MIN_FEE_EUR = 25.0
# Service fee per lot scales with weight (P0.3 distribution §: €20–40 typical).
SERVICE_FEE_BY_WEIGHT = [
    # (max_kg_exclusive, fee_eur)
    (100, 20.0),
    (500, 25.0),
    (1500, 30.0),
    (5000, 40.0),
    (float("inf"), 80.0),   # big lots (>5t) go to Enterprise bracket
]
# Biomass / compost / feed revenue per tonne (plant pays TRESAAA Surplus for the raw
# material — we are the contract holder, per Grok/Gemini consensus).
BIOMASS_REVENUE_EUR_PER_TONNE = {
    "biomass_biogas": 55.0,
    "energy_biogas": 45.0,
    "compost": 30.0,
    "cattle_feed": 40.0,
    "food_bank": 0.0,
    "donated_ong": 0.0,
}


def calculate_logistics_fee(distance_km: Optional[float]) -> float:
    """€0.25/km with a hard floor at €25 (P0.2 — see docstring above)."""
    if distance_km is None or distance_km <= 0:
        return LOGISTICS_MIN_FEE_EUR
    computed = distance_km * LOGISTICS_PER_KM_EUR
    return round(max(computed, LOGISTICS_MIN_FEE_EUR), 2)


def calculate_service_fee(cantidad_kg: float) -> float:
    for max_kg, fee in SERVICE_FEE_BY_WEIGHT:
        if cantidad_kg < max_kg:
            return fee
    return SERVICE_FEE_BY_WEIGHT[-1][1]


def calculate_biomass_revenue(outcome: Optional[str], cantidad_kg: float) -> float:
    if not outcome:
        return 0.0
    per_tonne = BIOMASS_REVENUE_EUR_PER_TONNE.get(outcome, 0.0)
    return round(per_tonne * (cantidad_kg / 1000.0), 2)

load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="TRESAAA Surplus API",
    description="B2B Food Surplus Marketplace para cumplir Ley 1/2025",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# ---- CORS ----
# In production we lock to known origins; in dev we allow localhost on any port.
# Override via CORS_ORIGINS env var (comma-separated) if needed.
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
_default_origins_prod = ["https://tresaaa-surplus.es", "https://www.tresaaa-surplus.es"]
_default_origin_regex = r"^http://localhost(:\d+)?$"

_cors_override = os.getenv("CORS_ORIGINS")
if _cors_override:
    allow_origins = [o.strip() for o in _cors_override.split(",") if o.strip()]
    allow_origin_regex = None
elif ENVIRONMENT == "production":
    allow_origins = _default_origins_prod
    allow_origin_regex = _default_origin_regex  # still allow localhost for smoke tests
else:
    allow_origins = ["*"]
    allow_origin_regex = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database (only if not in test mode).
# In production, prefer `alembic upgrade head` at release time; we keep
# create_all as a safety net when MIGRATIONS=alembic is NOT set.
if os.getenv("TESTING", "false").lower() != "true":
    if os.getenv("MIGRATIONS", "create_all").lower() != "alembic":
        database.init_db()


# Dependency for database session
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Dependency for extracting JWT token from Authorization header
def extract_token(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """Extract JWT token from Authorization header (Bearer scheme)"""
    if not authorization:
        return None

    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]

    return None


# ==================== HEALTH CHECK ====================

@app.get("/health", response_model=models.HealthResponse, tags=["Health"])
def health_check(db: Session = Depends(get_db)):
    """Health check endpoint - public"""
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        db_status = "healthy"
        overall_status = "healthy"
    except Exception as e:
        db_status = f"error: {str(e)}"
        overall_status = "degraded"

    return models.HealthResponse(
        status=overall_status,
        database=db_status,
        timestamp=datetime.utcnow()
    )


# ==================== AUTHENTICATION ENDPOINTS ====================

@app.post("/auth/register", response_model=auth.UserResponse, tags=["Authentication"])
def register(
    user_data: auth.UserCreate,
    db: Session = Depends(get_db)
):
    """
    Register a new user account.

    Returns: User details and can be used to login
    """
    try:
        user = auth.create_user(
            db,
            email=user_data.email,
            password=user_data.password,
            empresa_id=user_data.empresa_id,
            nombre_empresa=user_data.nombre_empresa,
            rol=user_data.rol
        )
        return user
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Registration error: {str(e)}")


@app.post("/auth/login", response_model=auth.Token, tags=["Authentication"])
def login(
    credentials: auth.UserLogin,
    db: Session = Depends(get_db)
):
    """
    Login with email and password.

    Returns: JWT access token for authenticated requests
    """
    user = auth.authenticate_user(db, credentials.email, credentials.password)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Account is disabled"
        )

    # Create token
    access_token = auth.create_access_token(
        data={
            "sub": user.email,
            "empresa_id": user.empresa_id,
            "rol": user.rol
        }
    )

    return auth.Token(
        access_token=access_token,
        expires_in=auth.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@app.get("/auth/me", response_model=auth.UserResponse, tags=["Authentication"])
def get_current_user_info(
    token: Optional[str] = Depends(extract_token),
    db: Session = Depends(get_db)
):
    """
    Get current user information.

    Requires: Valid JWT token in Authorization header
    """
    if not token:
        raise HTTPException(status_code=401, detail="No token provided")

    user = auth.get_current_user(token, db)
    return user


# ==================== HELPERS ====================

def parse_ubicacion(ubicacion) -> tuple:
    """Parse location from DB (POINT string, "lat,lon" string, or WKBElement) to (lat, lon).

    Tolerates three storage formats:
      * ``POINT(lon lat)`` — what the create endpoints write when PostGIS is off.
      * ``"lat,lon"`` — what some seed data / fixtures use.
      * ``WKBElement`` — what PostGIS hands back when ``USE_POSTGIS=true``.
    """
    if ubicacion is None:
        return 0.0, 0.0
    if isinstance(ubicacion, str):
        s = ubicacion.strip()
        # "POINT(lon lat)" format (note: PostGIS order is lon, lat)
        if s.upper().startswith("POINT"):
            try:
                coords = (
                    s.replace("POINT(", "")
                    .replace("POINT (", "")
                    .replace(")", "")
                    .strip()
                    .split()
                )
                return float(coords[1]), float(coords[0])
            except (IndexError, ValueError):
                return 0.0, 0.0
        # "lat,lon" format
        if "," in s:
            try:
                parts = s.split(",")
                return float(parts[0].strip()), float(parts[1].strip())
            except (IndexError, ValueError):
                return 0.0, 0.0
        return 0.0, 0.0
    # GeoAlchemy2 WKBElement - try to extract coords
    try:
        from geoalchemy2.shape import to_shape
        point = to_shape(ubicacion)
        return point.y, point.x
    except Exception:
        return 0.0, 0.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points in kilometres."""
    R = 6371.0088  # Earth mean radius (km)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * R * math.asin(min(1.0, math.sqrt(a)))


def logistics_radius_cap_km(max_weight_kg: Optional[float]) -> Optional[float]:
    """Return the logistics-aware default radius for a weight tier.

    Small lots (<50 kg) are only viable within a small radius because the
    transport cost dominates. Medium lots (50–500 kg) justify regional
    shipping. Large lots (>500 kg) can travel nationally.
    """
    if max_weight_kg is None:
        return None
    if max_weight_kg < 50:
        return 25.0
    if max_weight_kg <= 500:
        return 100.0
    return 2000.0  # effectively uncapped (Iberia diagonal is ~1100 km)


def db_to_generador_dict(g) -> dict:
    """Convert GeneradorDB to dict compatible with Generador model"""
    lat, lon = parse_ubicacion(g.ubicacion)
    return {
        "id": g.id,
        "nombre": g.nombre,
        "tipo": g.tipo,
        "cif": g.cif,
        "direccion": g.direccion,
        "ubicacion_lat": lat,
        "ubicacion_lon": lon,
        "contacto_email": g.contacto_email,
        "contacto_telefono": g.contacto_telefono,
        "plan_suscripcion": g.plan_suscripcion,
        "created_at": g.created_at,
    }


def db_to_receptor_dict(r) -> dict:
    """Convert ReceptorDB to dict compatible with Receptor model"""
    lat, lon = parse_ubicacion(r.ubicacion)
    return {
        "id": r.id,
        "nombre": r.nombre,
        "tipo": r.tipo,
        "cif": r.cif,
        "direccion": r.direccion,
        "ubicacion_lat": lat,
        "ubicacion_lon": lon,
        "capacidad_kg_dia": r.capacidad_kg_dia,
        "categorias_interes": r.categorias_interes or [],
        "licencias": r.licencias or [],
        "created_at": r.created_at,
    }


def db_to_lote_dict(l) -> dict:
    """Convert LoteDB to dict compatible with Lote model"""
    lat, lon = parse_ubicacion(l.ubicacion)
    return {
        "id": l.id,
        "generador_id": l.generador_id,
        "producto": l.producto,
        "categoria": l.categoria,
        "cantidad_kg": l.cantidad_kg,
        "ubicacion_lat": lat,
        "ubicacion_lon": lon,
        "fecha_publicacion": l.fecha_publicacion,
        "fecha_limite": l.fecha_limite,
        "precio_base": l.precio_base,
        "precio_actual": l.precio_actual,
        "temperatura_conservacion": l.temperatura_conservacion,
        "estado": l.estado,
        "lote_origen": l.lote_origen,
        "created_at": l.created_at,
    }


# ==================== GENERADOR ENDPOINTS ====================

@app.post("/generadores", response_model=models.Generador, tags=["Generadores"])
def create_generador(
    generador: models.GeneradorCreate,
    db: Session = Depends(get_db)
):
    """Create a new generator - public"""

    # Validate input
    if not generador.nombre or len(generador.nombre.strip()) == 0:
        raise HTTPException(status_code=422, detail="Nombre is required and cannot be empty")

    if not generador.cif or len(generador.cif.strip()) == 0:
        raise HTTPException(status_code=422, detail="CIF is required and cannot be empty")

    if not -90 <= generador.ubicacion_lat <= 90:
        raise HTTPException(status_code=422, detail="Latitude must be between -90 and 90")

    if not -180 <= generador.ubicacion_lon <= 180:
        raise HTTPException(status_code=422, detail="Longitude must be between -180 and 180")

    existing = db.query(database.GeneradorDB).filter(
        database.GeneradorDB.cif == generador.cif
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="CIF ya registrado")

    try:
        # Store location - use PostGIS if available, plain text otherwise
        try:
            from geoalchemy2 import func as gf
            ubicacion = gf.ST_GeomFromText(f"POINT({generador.ubicacion_lon} {generador.ubicacion_lat})", 4326)
        except ImportError:
            ubicacion = f"POINT({generador.ubicacion_lon} {generador.ubicacion_lat})"

        db_generador = database.GeneradorDB(
            nombre=generador.nombre.strip(),
            tipo=generador.tipo,
            cif=generador.cif.strip(),
            direccion=generador.direccion,
            ubicacion=ubicacion,
            contacto_email=generador.contacto_email,
            contacto_telefono=generador.contacto_telefono,
            plan_suscripcion=generador.plan_suscripcion
        )

        db.add(db_generador)
        db.commit()
        db.refresh(db_generador)

        return db_to_generador_dict(db_generador)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/generadores/{generador_id}", response_model=models.Generador, tags=["Generadores"])
def get_generador(generador_id: int, db: Session = Depends(get_db)):
    """Get generator details - public"""

    generador = db.query(database.GeneradorDB).filter(
        database.GeneradorDB.id == generador_id
    ).first()

    if not generador:
        raise HTTPException(status_code=404, detail="Generador no encontrado")

    return db_to_generador_dict(generador)


# ==================== RECEPTOR ENDPOINTS ====================

@app.post("/receptores", response_model=models.Receptor, tags=["Receptores"])
def create_receptor(
    receptor: models.ReceptorCreate,
    db: Session = Depends(get_db)
):
    """Create a new receiver - public"""

    # Validate input
    if not receptor.nombre or len(receptor.nombre.strip()) == 0:
        raise HTTPException(status_code=422, detail="Nombre is required and cannot be empty")

    if not receptor.cif or len(receptor.cif.strip()) == 0:
        raise HTTPException(status_code=422, detail="CIF is required and cannot be empty")

    if receptor.capacidad_kg_dia <= 0:
        raise HTTPException(status_code=422, detail="Capacidad debe ser mayor a 0")

    if not -90 <= receptor.ubicacion_lat <= 90:
        raise HTTPException(status_code=422, detail="Latitude must be between -90 and 90")

    if not -180 <= receptor.ubicacion_lon <= 180:
        raise HTTPException(status_code=422, detail="Longitude must be between -180 and 180")

    existing = db.query(database.ReceptorDB).filter(
        database.ReceptorDB.cif == receptor.cif
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="CIF ya registrado")

    try:
        # Store location - use PostGIS if available, plain text otherwise
        try:
            from geoalchemy2 import func as gf
            ubicacion = gf.ST_GeomFromText(f"POINT({receptor.ubicacion_lon} {receptor.ubicacion_lat})", 4326)
        except ImportError:
            ubicacion = f"POINT({receptor.ubicacion_lon} {receptor.ubicacion_lat})"

        db_receptor = database.ReceptorDB(
            nombre=receptor.nombre.strip(),
            tipo=receptor.tipo,
            cif=receptor.cif.strip(),
            direccion=receptor.direccion,
            ubicacion=ubicacion,
            capacidad_kg_dia=receptor.capacidad_kg_dia,
            categorias_interes=[c.value for c in receptor.categorias_interes],
            licencias=receptor.licencias
        )

        db.add(db_receptor)
        db.commit()
        db.refresh(db_receptor)

        return db_to_receptor_dict(db_receptor)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/receptores/{receptor_id}", response_model=models.Receptor, tags=["Receptores"])
def get_receptor(receptor_id: int, db: Session = Depends(get_db)):
    """Get receiver details - public"""

    receptor = db.query(database.ReceptorDB).filter(
        database.ReceptorDB.id == receptor_id
    ).first()

    if not receptor:
        raise HTTPException(status_code=404, detail="Receptor no encontrado")

    return db_to_receptor_dict(receptor)


# ==================== LOTE (LOT) ENDPOINTS ====================

@app.post("/lots", response_model=models.Lote, tags=["Lotes"])
def create_lot(
    lote: models.LoteCreate,
    token: Optional[str] = Depends(extract_token),
    db: Session = Depends(get_db)
):
    """
    Publish a new surplus lot.

    Requires: JWT authentication
    """
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    user = auth.get_current_user(token, db)

    # Validate input
    if not lote.producto or len(lote.producto.strip()) == 0:
        raise HTTPException(status_code=422, detail="Producto is required and cannot be empty")

    if lote.cantidad_kg <= 0:
        raise HTTPException(status_code=422, detail="Cantidad must be greater than 0")

    if lote.precio_base <= 0:
        raise HTTPException(status_code=422, detail="Precio base must be greater than 0")

    if lote.fecha_limite <= datetime.utcnow():
        raise HTTPException(status_code=422, detail="Fecha limite must be in the future")

    if not -90 <= lote.ubicacion_lat <= 90:
        raise HTTPException(status_code=422, detail="Latitude must be between -90 and 90")

    if not -180 <= lote.ubicacion_lon <= 180:
        raise HTTPException(status_code=422, detail="Longitude must be between -180 and 180")

    # Verify generator exists
    generador = db.query(database.GeneradorDB).filter(
        database.GeneradorDB.id == lote.generador_id
    ).first()

    if not generador:
        raise HTTPException(status_code=404, detail="Generador no encontrado")

    # ---- Dutch auction KILLED (P0.1) ----
    # The original model recomputed precio_actual as a descending-price
    # auction. VERDICT_BUSINESS_MODEL.md (Gemini leg, endorsed by Victor)
    # flagged this as a strategic error: TRESAAA Surplus charges logistics +
    # service fee + biomass revenue, NOT a cut of an auction. The price of
    # the *food* is whatever the generator sets (often 0€ or symbolic) and
    # it STAYS THERE. Dynamic pricing pressure creates perverse incentives
    # and penalises donations.
    precio_actual = lote.precio_base

    try:
        # Store location - use PostGIS if available, plain text otherwise
        try:
            from geoalchemy2 import func as gf
            ubicacion = gf.ST_GeomFromText(f"POINT({lote.ubicacion_lon} {lote.ubicacion_lat})", 4326)
        except ImportError:
            ubicacion = f"POINT({lote.ubicacion_lon} {lote.ubicacion_lat})"

        db_lote = database.LoteDB(
            generador_id=lote.generador_id,
            producto=lote.producto.strip(),
            categoria=lote.categoria,
            cantidad_kg=lote.cantidad_kg,
            ubicacion=ubicacion,
            fecha_limite=lote.fecha_limite,
            precio_base=lote.precio_base,
            precio_actual=precio_actual,
            temperatura_conservacion=lote.temperatura_conservacion,
            lote_origen=lote.lote_origen,
            estado=models.EstadoLote.activo
        )

        db.add(db_lote)
        db.commit()
        db.refresh(db_lote)

        # ---- Run automatic matching (P0.1) ----
        # Fire-and-forget; if scoring fails we don't want to kill the POST.
        try:
            candidates = auto_matching.rank_receivers(
                db, db_lote, lote.ubicacion_lat, lote.ubicacion_lon, limit=5
            )
            for c in candidates:
                # Notification is best-effort — missing SMTP config must not
                # break the API. notifications module already swallows.
                try:
                    if c.contacto_email:
                        notifications.notify_match_offered(
                            c.contacto_email,
                            c.receptor_nombre,
                            db_lote.producto,
                            db_lote.cantidad_kg,
                            db_lote.id,
                            c.distance_km,
                        )
                except Exception:
                    pass
        except Exception as e:
            print(f"[create_lot] auto-match warn: {e}", flush=True)

        return db_to_lote_dict(db_lote)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/lots", response_model=List[models.LoteWithBids], tags=["Lotes"])
def list_lots(
    categoria: Optional[models.Categoria] = None,
    ubicacion_lat: Optional[float] = None,
    ubicacion_lon: Optional[float] = None,
    radio_km: Optional[float] = 50.0,
    precio_max: Optional[float] = None,
    fecha_limite_min: Optional[datetime] = None,
    db: Session = Depends(get_db)
):
    """List active lots with filters - public"""

    query = db.query(database.LoteDB).filter(
        database.LoteDB.estado == models.EstadoLote.activo
    )

    if categoria:
        query = query.filter(database.LoteDB.categoria == categoria)

    if precio_max:
        query = query.filter(database.LoteDB.precio_actual <= precio_max)

    if fecha_limite_min:
        query = query.filter(database.LoteDB.fecha_limite >= fecha_limite_min)

    lotes = query.all()

    # Filter by location if provided
    if ubicacion_lat and ubicacion_lon:
        try:
            from geoalchemy2 import func as gf
            filtered_lotes = []

            for lote in lotes:
                distance_query = db.query(
                    gf.ST_Distance(
                        lote.ubicacion,
                        gf.ST_GeomFromText(f"POINT({ubicacion_lon} {ubicacion_lat})", 4326)
                    ) / 1000
                ).scalar()

                if distance_query and distance_query <= radio_km:
                    filtered_lotes.append(lote)

            lotes = filtered_lotes
        except Exception:
            # If geoalchemy2 not available, skip distance filtering
            pass

    # Build response with bid info
    result = []
    for lote in lotes:
        num_bids = db.query(database.PujaDB).filter(
            database.PujaDB.lote_id == lote.id
        ).count()

        precio_mas_alto = db.query(database.PujaDB.precio_oferta).filter(
            database.PujaDB.lote_id == lote.id
        ).order_by(database.PujaDB.precio_oferta.desc()).first()

        lote_dict = db_to_lote_dict(lote)
        result.append(models.LoteWithBids(
            **{**lote_dict, "num_bids": num_bids, "precio_oferta_mas_alta": precio_mas_alto[0] if precio_mas_alto else None}
        ))

    return result


@app.get("/lots/nearby", tags=["Lotes"])
def lots_nearby(
    lat: float = Query(..., ge=-90, le=90, description="Latitud del receptor"),
    lon: float = Query(..., ge=-180, le=180, description="Longitud del receptor"),
    radius_km: Optional[float] = Query(
        None, gt=0, le=5000,
        description="Radio de búsqueda en km. Si se omite, se usa el cap logístico por peso (25/100/2000)."
    ),
    max_weight_kg: Optional[float] = Query(
        None, gt=0,
        description="Peso máximo del lote. <50=pequeño, 50-500=mediano, >500=grande."
    ),
    category: Optional[models.Categoria] = Query(None, description="Filtrar por categoría"),
    limit: int = Query(100, ge=1, le=500, description="Máximo de lotes a devolver"),
    db: Session = Depends(get_db),
):
    """Return active lots close to ``(lat, lon)``, sorted by distance ascending.

    Logistics-aware defaults:

    * ``max_weight_kg < 50``  → radius cap **25 km** (lotes pequeños, transporte inviable más lejos)
    * ``50 ≤ kg ≤ 500``       → radius cap **100 km** (lotes medianos)
    * ``kg > 500``            → sin cap efectivo (nacional)

    If ``radius_km`` is omitted, the cap above is used; otherwise both are
    honoured and the smaller of the two applies. When neither is provided
    the default radius is 50 km.

    Uses PostGIS ``ST_DWithin`` when ``USE_POSTGIS=true``, otherwise computes
    great-circle distance in Python (works on SQLite and vanilla Postgres).
    """
    # 1. Resolve effective radius
    weight_cap = logistics_radius_cap_km(max_weight_kg)
    if radius_km is None:
        effective_radius = weight_cap if weight_cap is not None else 50.0
    else:
        effective_radius = radius_km
        if weight_cap is not None and effective_radius > weight_cap:
            effective_radius = weight_cap

    # 2. Base query — active lots joined to generator for name/contact
    query = (
        db.query(database.LoteDB, database.GeneradorDB)
        .join(
            database.GeneradorDB,
            database.LoteDB.generador_id == database.GeneradorDB.id,
        )
        .filter(database.LoteDB.estado == models.EstadoLote.activo)
    )
    if category is not None:
        query = query.filter(database.LoteDB.categoria == category)
    if max_weight_kg is not None:
        query = query.filter(database.LoteDB.cantidad_kg <= max_weight_kg)

    # 3. PostGIS fast-path (SQL-side ST_DWithin + ORDER BY distance)
    rows = None
    use_postgis = getattr(database, "USE_POSTGIS", False) and database.Geometry is not None
    if use_postgis:
        try:
            from geoalchemy2 import func as gf
            point = gf.ST_SetSRID(gf.ST_MakePoint(lon, lat), 4326)
            geog_lot = database.LoteDB.ubicacion.cast("geography")
            geog_point = point.cast("geography")
            distance_m = gf.ST_Distance(geog_lot, geog_point)
            rows = (
                query.filter(gf.ST_DWithin(geog_lot, geog_point, effective_radius * 1000.0))
                .order_by(distance_m.asc())
                .limit(limit)
                .all()
            )
        except Exception:
            rows = None  # fall through to Python path

    # 4. Python fallback — haversine over all candidates
    results = []
    if rows is None:
        for lote, gen in query.all():
            lat_l, lon_l = parse_ubicacion(lote.ubicacion)
            if lat_l == 0.0 and lon_l == 0.0:
                continue  # can't geolocate this lot
            d_km = haversine_km(lat, lon, lat_l, lon_l)
            if d_km > effective_radius:
                continue
            results.append((lote, gen, lat_l, lon_l, d_km))
        results.sort(key=lambda r: r[4])
        results = results[:limit]
    else:
        for lote, gen in rows:
            lat_l, lon_l = parse_ubicacion(lote.ubicacion)
            d_km = haversine_km(lat, lon, lat_l, lon_l) if (lat_l or lon_l) else 0.0
            results.append((lote, gen, lat_l, lon_l, d_km))

    # 5. Build response with bid counts + distance
    lots_out = []
    for lote, gen, lat_l, lon_l, d_km in results:
        num_bids = (
            db.query(database.PujaDB)
            .filter(database.PujaDB.lote_id == lote.id)
            .count()
        )
        categoria_val = lote.categoria.value if hasattr(lote.categoria, "value") else str(lote.categoria)
        estado_val = lote.estado.value if hasattr(lote.estado, "value") else str(lote.estado)
        lots_out.append({
            "id": lote.id,
            "generador_id": lote.generador_id,
            "generador_nombre": gen.nombre,
            "producto": lote.producto,
            "categoria": categoria_val,
            "cantidad_kg": lote.cantidad_kg,
            "ubicacion_lat": lat_l,
            "ubicacion_lon": lon_l,
            "fecha_publicacion": lote.fecha_publicacion.isoformat() if lote.fecha_publicacion else None,
            "fecha_limite": lote.fecha_limite.isoformat() if lote.fecha_limite else None,
            "precio_base": lote.precio_base,
            "precio_actual": lote.precio_actual,
            "temperatura_conservacion": lote.temperatura_conservacion,
            "estado": estado_val,
            "num_bids": num_bids,
            "distancia_km": round(d_km, 2),
        })

    return {
        "query": {
            "lat": lat,
            "lon": lon,
            "radius_km": effective_radius,
            "radius_km_requested": radius_km,
            "max_weight_kg": max_weight_kg,
            "weight_tier": (
                "pequeno" if (max_weight_kg is not None and max_weight_kg < 50)
                else "mediano" if (max_weight_kg is not None and max_weight_kg <= 500)
                else "grande" if max_weight_kg is not None
                else None
            ),
            "category": category.value if category else None,
            "limit": limit,
            "engine": "postgis" if (use_postgis and rows is not None) else "haversine",
        },
        "count": len(lots_out),
        "lots": lots_out,
    }


@app.get("/lots/{lot_id}", response_model=models.Lote, tags=["Lotes"])
def get_lot(lot_id: int, db: Session = Depends(get_db)):
    """Get lot details - public"""

    lote = db.query(database.LoteDB).filter(
        database.LoteDB.id == lot_id
    ).first()

    if not lote:
        raise HTTPException(status_code=404, detail="Lote no encontrado")

    return db_to_lote_dict(lote)


# ==================== AUTO MATCHING (P0.1) ====================

@app.post("/lots/{lot_id}/auto_match", response_model=models.AutoMatchResult, tags=["Lotes"])
def auto_match_lot(
    lot_id: int,
    notify_top: int = Query(5, ge=0, le=20, description="Cuántos receptores top notificar por email"),
    db: Session = Depends(get_db),
):
    """Rank receptors for a lot using the P0.1 scoring model and notify the
    top N. This replaces the old Dutch-auction loop — the matching is
    instantaneous and driven by:

        score = (1 / max(distance_km + 0.5, 0.5))
              * weight_factor(kg)
              * urgency_factor(hours_to_expiry)
              * priority_factor(receptor_tipo)

    Priority order per VERDICT_BUSINESS_MODEL.md:
    ONG / banco alimentos > transformador > piensos > biogás > compost.

    Notification is best-effort (SMTP may be down — we don't 500 on that).
    """
    lote = db.query(database.LoteDB).filter(database.LoteDB.id == lot_id).first()
    if not lote:
        raise HTTPException(status_code=404, detail="Lote no encontrado")

    lot_lat, lot_lon = parse_ubicacion(lote.ubicacion)
    candidates = auto_matching.rank_receivers(db, lote, lot_lat, lot_lon, limit=20)

    notified = 0
    for c in candidates[:notify_top]:
        try:
            if c.contacto_email:
                notifications.notify_match_offered(
                    c.contacto_email,
                    c.receptor_nombre,
                    lote.producto,
                    lote.cantidad_kg,
                    lote.id,
                    c.distance_km,
                )
                notified += 1
        except Exception:
            pass

    categoria_val = lote.categoria.value if hasattr(lote.categoria, "value") else str(lote.categoria)
    fallback = auto_matching.pick_fallback_receptor(db, categoria_val, lot_lat, lot_lon)

    return models.AutoMatchResult(
        lote_id=lote.id,
        categoria=categoria_val,
        matches=[
            models.AutoMatchCandidate(
                receptor_id=c.receptor_id,
                receptor_nombre=c.receptor_nombre,
                receptor_tipo=c.receptor_tipo,
                distance_km=c.distance_km,
                score=c.score,
                priority_factor=c.priority_factor,
                urgency_factor=c.urgency_factor,
                weight_factor=c.weight_factor,
            )
            for c in candidates
        ],
        notified_top_n=notified,
        fallback_available=fallback is not None,
    )


@app.post("/lots/{lot_id}/fallback", tags=["Lotes"])
def fallback_lot(lot_id: int, db: Session = Depends(get_db)):
    """Pick the fallback destination (pienso / biomasa / compost) when nobody
    accepted the lot within the SLA window (default 24h). This is the
    "disposal guarantee" — we commit to always finding a home, even if it's
    a biogas plant.

    Returns the chosen receptor + suggested outcome; the actual transaction
    close still goes through POST /transactions.
    """
    lote = db.query(database.LoteDB).filter(database.LoteDB.id == lot_id).first()
    if not lote:
        raise HTTPException(status_code=404, detail="Lote no encontrado")

    lot_lat, lot_lon = parse_ubicacion(lote.ubicacion)
    categoria_val = lote.categoria.value if hasattr(lote.categoria, "value") else str(lote.categoria)
    fb = auto_matching.pick_fallback_receptor(db, categoria_val, lot_lat, lot_lon)

    if not fb:
        raise HTTPException(
            status_code=404,
            detail="No hay receptor fallback disponible en el radio — alerta operativa."
        )

    outcome = auto_matching.TIPO_TO_OUTCOME.get(fb.receptor_tipo, "biomass_biogas")
    return {
        "lote_id": lote.id,
        "categoria": categoria_val,
        "fallback_receptor": {
            "id": fb.receptor_id,
            "nombre": fb.receptor_nombre,
            "tipo": fb.receptor_tipo,
            "distance_km": fb.distance_km,
        },
        "suggested_outcome": outcome,
        "note": "Ejecutar POST /transactions con outcome y receptor_id de fallback para formalizar."
    }


# ==================== PUJA (BID) ENDPOINTS ====================

@app.post("/bids", response_model=models.Puja, tags=["Pujas"])
def create_bid(
    puja: models.PujaCreate,
    token: Optional[str] = Depends(extract_token),
    db: Session = Depends(get_db)
):
    """
    Place a bid on a lot.

    Requires: JWT authentication
    """
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    user = auth.get_current_user(token, db)

    # Validate input
    if puja.precio_oferta <= 0:
        raise HTTPException(status_code=422, detail="Precio must be greater than 0")

    # Verify lot exists and is active
    lote = db.query(database.LoteDB).filter(
        database.LoteDB.id == puja.lote_id
    ).first()

    if not lote:
        raise HTTPException(status_code=404, detail="Lote no encontrado")

    if lote.estado != models.EstadoLote.activo:
        raise HTTPException(status_code=400, detail="Lote no activo")

    # Verify receiver exists
    receptor = db.query(database.ReceptorDB).filter(
        database.ReceptorDB.id == puja.receptor_id
    ).first()

    if not receptor:
        raise HTTPException(status_code=404, detail="Receptor no encontrado")

    # Validate use is permitted
    estado_producto = compliance.determine_product_state(
        lote.fecha_limite - timedelta(days=2),
        lote.fecha_limite
    )

    es_permitido, razon = compliance.validate_use_allowed(
        estado_producto,
        lote.categoria,
        puja.uso_previsto.value
    )

    if not es_permitido:
        raise HTTPException(status_code=400, detail=f"Uso no permitido: {razon}")

    try:
        db_puja = database.PujaDB(
            lote_id=puja.lote_id,
            receptor_id=puja.receptor_id,
            precio_oferta=puja.precio_oferta,
            uso_previsto=puja.uso_previsto,
            mensaje=puja.mensaje,
            estado=models.EstadoPuja.pendiente
        )

        db.add(db_puja)
        db.commit()

        # ---- Dutch auction KILLED (P0.1) ----
        # precio_actual used to be recomputed via pricing.calculate_dynamic_price
        # whenever a new bid arrived. It no longer is — the food price is
        # whatever the generator set and stays there. The only thing that
        # varies between transactions is the service/logistics fee TRESAAA Surplus
        # charges, which lives on the Transaccion row, not here.
        db.refresh(db_puja)

        # Send notification to generator
        generador = db.query(database.GeneradorDB).filter(
            database.GeneradorDB.id == lote.generador_id
        ).first()

        if generador:
            notifications.notify_bid_received(
                generador.contacto_email,
                generador.nombre,
                receptor.nombre,
                lote.producto,
                puja.precio_oferta,
                lote.cantidad_kg
            )

        return db_puja
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/bids/{lot_id}", response_model=List[models.Puja], tags=["Pujas"])
def list_bids_for_lot(lot_id: int, db: Session = Depends(get_db)):
    """List all bids for a lot - public"""

    lote = db.query(database.LoteDB).filter(
        database.LoteDB.id == lot_id
    ).first()

    if not lote:
        raise HTTPException(status_code=404, detail="Lote no encontrado")

    pujas = db.query(database.PujaDB).filter(
        database.PujaDB.lote_id == lot_id
    ).order_by(database.PujaDB.precio_oferta.desc()).all()

    return pujas


# ==================== TRANSACTION ENDPOINTS ====================

@app.post("/transactions", response_model=models.Transaccion, tags=["Transacciones"])
def close_transaction(
    transaccion: models.TransaccionCreate,
    token: Optional[str] = Depends(extract_token),
    db: Session = Depends(get_db)
):
    """
    Close a transaction by accepting a bid.

    Requires: JWT authentication
    """
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    user = auth.get_current_user(token, db)

    # Validate input
    if transaccion.cantidad_kg <= 0:
        raise HTTPException(status_code=422, detail="Cantidad must be greater than 0")

    if transaccion.precio_final <= 0:
        raise HTTPException(status_code=422, detail="Precio must be greater than 0")

    # Verify lot and bid exist
    lote = db.query(database.LoteDB).filter(
        database.LoteDB.id == transaccion.lote_id
    ).first()

    if not lote:
        raise HTTPException(status_code=404, detail="Lote no encontrado")

    puja = db.query(database.PujaDB).filter(
        database.PujaDB.id == transaccion.puja_id
    ).first()

    if not puja:
        raise HTTPException(status_code=404, detail="Puja no encontrada")

    # Calculate CO2 avoided
    co2_evitado, co2_details = carbon.calculate_co2_avoided(
        transaccion.cantidad_kg,
        lote.categoria.value,
        transaccion.uso_final.value
    )

    # ---- TRESAAA Surplus revenue split (P0.2) ----
    # Gemini, in VERDICT_BUSINESS_MODEL.md: "Logística sin mínimo de recogida =
    # suicidio margen. Minimum pickup fee obligatorio." We enforce €25 as the
    # floor regardless of what the client passes. The food price
    # (precio_final) remains whatever the generator set; TRESAAA Surplus invoices
    # on top of that.
    #
    # If the client didn't pass a logistics_fee, compute it from distance_km.
    # If neither is available, fall back to the minimum (€25) — we'd rather
    # overcharge than miss a fee.
    explicit_logistics_fee = transaccion.logistics_fee_eur
    if explicit_logistics_fee is None:
        explicit_logistics_fee = calculate_logistics_fee(transaccion.distance_km)
    # Enforce minimum €25 *always*, even if the caller tried to undercut it.
    logistics_fee = max(float(explicit_logistics_fee), LOGISTICS_MIN_FEE_EUR)

    service_fee = (
        transaccion.service_fee_eur
        if transaccion.service_fee_eur is not None
        else calculate_service_fee(transaccion.cantidad_kg)
    )

    # Derive outcome from receptor tipo + lot category when the caller
    # didn't specify one explicitly. This is what the dashboard reads.
    outcome_val = transaccion.outcome.value if transaccion.outcome else None
    if not outcome_val:
        receptor_tipo = puja.receptor.tipo.value if puja.receptor and hasattr(puja.receptor.tipo, "value") else None
        if not receptor_tipo:
            rec_row = db.query(database.ReceptorDB).filter(
                database.ReceptorDB.id == puja.receptor_id
            ).first()
            receptor_tipo = rec_row.tipo.value if rec_row and hasattr(rec_row.tipo, "value") else str(rec_row.tipo) if rec_row else "biogas"
        outcome_val = auto_matching.TIPO_TO_OUTCOME.get(receptor_tipo, "biomass_biogas")

    biomass_revenue = (
        transaccion.biomass_revenue_eur
        if transaccion.biomass_revenue_eur is not None
        else calculate_biomass_revenue(outcome_val, transaccion.cantidad_kg)
    )

    # Create transaction
    db_transaccion = database.TransaccionDB(
        lote_id=transaccion.lote_id,
        puja_id=transaccion.puja_id,
        generador_id=lote.generador_id,
        receptor_id=puja.receptor_id,
        precio_final=transaccion.precio_final,
        cantidad_kg=transaccion.cantidad_kg,
        uso_final=transaccion.uso_final,
        co2_evitado_kg=co2_evitado,
        estado=models.EstadoTransaccion.completada,
        service_fee_eur=service_fee,
        logistics_fee_eur=logistics_fee,
        biomass_revenue_eur=biomass_revenue,
        outcome=outcome_val,
    )

    # Mark lot as adjudicated
    lote.estado = models.EstadoLote.adjudicado

    # Mark bid as accepted
    puja.estado = models.EstadoPuja.aceptada

    db.add(db_transaccion)
    db.commit()

    # Generate compliance documents
    generador = db.query(database.GeneradorDB).filter(
        database.GeneradorDB.id == lote.generador_id
    ).first()

    receptor = db.query(database.ReceptorDB).filter(
        database.ReceptorDB.id == puja.receptor_id
    ).first()

    estado_producto = compliance.determine_product_state(
        lote.fecha_limite - timedelta(days=2),
        lote.fecha_limite
    )

    compliance_data = compliance.generate_compliance_data(
        db_transaccion.id,
        lote.id,
        generador.id,
        receptor.id,
        generador.nombre,
        receptor.nombre,
        lote.producto,
        transaccion.cantidad_kg,
        transaccion.precio_final,
        transaccion.uso_final.value,
        estado_producto
    )

    db_compliance = database.ComplianceDocDB(
        transaccion_id=db_transaccion.id,
        tipo=models.TipoComplianceDoc.trazabilidad,
        contenido_json=compliance_data
    )

    # Save carbon credit
    db_carbon = database.CarbonCreditDB(
        transaccion_id=db_transaccion.id,
        co2_evitado_kg=co2_evitado,
        tipo_calculo="lifecycle_analysis",
        equivalencias=co2_details["equivalencias"]
    )

    db.add(db_compliance)
    db.add(db_carbon)
    db.commit()

    db.refresh(db_transaccion)

    # Send notifications
    if generador and receptor:
        notifications.notify_bid_accepted(
            receptor.contacto_email,
            receptor.nombre,
            generador.nombre,
            lote.producto,
            transaccion.precio_final,
            transaccion.cantidad_kg,
            db_transaccion.id
        )

        notifications.notify_transaction_completed(
            generador.contacto_email,
            receptor.contacto_email,
            generador.nombre,
            receptor.nombre,
            lote.producto,
            transaccion.cantidad_kg,
            transaccion.precio_final,
            co2_evitado,
            db_transaccion.id
        )

    return db_transaccion


@app.get("/transactions/{transaction_id}", response_model=models.Transaccion, tags=["Transacciones"])
def get_transaction(transaction_id: int, db: Session = Depends(get_db)):
    """Get transaction details - public"""

    transaccion = db.query(database.TransaccionDB).filter(
        database.TransaccionDB.id == transaction_id
    ).first()

    if not transaccion:
        raise HTTPException(status_code=404, detail="Transacción no encontrada")

    return transaccion


# ==================== COMPLIANCE ENDPOINTS ====================

@app.get("/compliance/{transaction_id}", tags=["Compliance"])
def get_compliance_docs(transaction_id: int, db: Session = Depends(get_db)):
    """Get auto-generated legal documents for a transaction - public"""

    transaccion = db.query(database.TransaccionDB).filter(
        database.TransaccionDB.id == transaction_id
    ).first()

    if not transaccion:
        raise HTTPException(status_code=404, detail="Transacción no encontrada")

    docs = db.query(database.ComplianceDocDB).filter(
        database.ComplianceDocDB.transaccion_id == transaction_id
    ).all()

    return {
        "transaccion_id": transaction_id,
        "documentos": [doc.contenido_json for doc in docs]
    }


@app.get("/compliance-hierarchy", tags=["Compliance"])
def get_compliance_hierarchy():
    """Get legal use hierarchy per Ley 1/2025 - public"""
    return compliance.ComplianceChecker.get_use_hierarchy_description()


# ==================== MATCHING ENDPOINTS ====================

@app.get("/matches", response_model=List[models.MatchResponse], tags=["Matching"])
def get_predictive_matches(
    generador_id: int,
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db)
):
    """Get predictive matches for a generator - public"""

    generador = db.query(database.GeneradorDB).filter(
        database.GeneradorDB.id == generador_id
    ).first()

    if not generador:
        raise HTTPException(status_code=404, detail="Generador no encontrado")

    engine = matching.MatchingEngine(db)
    recommendations = engine.get_recommended_matches(generador_id, limit)
    predictions = engine.predict_next_surplus(generador_id)

    result = []
    for rec in recommendations:
        prediction = next((p for p in predictions if p["categoria"] == rec.get("categoria")), None)
        result.append(models.MatchResponse(
            receptor_id=rec["receptor_id"],
            receptor_nombre=rec["receptor_nombre"],
            producto_predicho=prediction["producto"] if prediction else "Producto similar",
            cantidad_predicha_kg=prediction["cantidad_predicha_kg"] if prediction else 50.0,
            fecha_predicha=prediction["fecha_predicha"] if prediction else datetime.utcnow() + timedelta(days=7),
            confianza=prediction["confianza"] if prediction else 0.5,
            score_match=rec["score_match"]
        ))

    return result


# ==================== STATS ENDPOINTS ====================

@app.get("/stats", response_model=models.StatsResponse, tags=["Statistics"])
def get_dashboard_stats(db: Session = Depends(get_db)):
    """Get dashboard metrics - public"""

    transacciones = db.query(database.TransaccionDB).filter(
        database.TransaccionDB.estado == models.EstadoTransaccion.completada
    ).all()

    total_kg = sum(t.cantidad_kg for t in transacciones)
    total_co2 = sum(t.co2_evitado_kg or 0 for t in transacciones)
    total_value = sum(t.precio_final for t in transacciones)

    num_generadores = db.query(database.GeneradorDB).count()
    num_receptores = db.query(database.ReceptorDB).count()

    avg_transaction_value = total_value / len(transacciones) if transacciones else 0

    return models.StatsResponse(
        total_kg_saved=round(total_kg, 1),
        total_transactions=len(transacciones),
        co2_avoided_kg=round(total_co2, 2),
        money_saved=round(total_value, 2),
        num_generadores=num_generadores,
        num_receptores=num_receptores,
        avg_transaction_value=round(avg_transaction_value, 2)
    )


@app.get("/dashboard", tags=["Statistics"])
def get_dashboard_metrics(db: Session = Depends(get_db)):
    """Get comprehensive dashboard metrics - public"""

    # Basic stats
    transacciones = db.query(database.TransaccionDB).filter(
        database.TransaccionDB.estado == models.EstadoTransaccion.completada
    ).all()

    total_kg = sum(t.cantidad_kg for t in transacciones)
    total_co2 = sum(t.co2_evitado_kg or 0 for t in transacciones)
    total_value = sum(t.precio_final for t in transacciones)

    # Time-series data (transactions per day for last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_trans = db.query(database.TransaccionDB).filter(
        database.TransaccionDB.created_at >= thirty_days_ago,
        database.TransaccionDB.estado == models.EstadoTransaccion.completada
    ).all()

    trans_by_day = {}
    for trans in recent_trans:
        day = trans.created_at.date().isoformat()
        trans_by_day[day] = trans_by_day.get(day, 0) + 1

    # Category breakdown
    category_stats = {}
    for trans in transacciones:
        lote = db.query(database.LoteDB).filter(database.LoteDB.id == trans.lote_id).first()
        if lote:
            cat = lote.categoria.value if hasattr(lote.categoria, 'value') else str(lote.categoria)
            if cat not in category_stats:
                category_stats[cat] = {"kg": 0, "transactions": 0, "co2": 0}
            category_stats[cat]["kg"] += trans.cantidad_kg
            category_stats[cat]["transactions"] += 1
            category_stats[cat]["co2"] += trans.co2_evitado_kg or 0

    # Top generators
    gen_stats = {}
    for trans in transacciones:
        gen_id = trans.generador_id
        if gen_id not in gen_stats:
            generador = db.query(database.GeneradorDB).filter(database.GeneradorDB.id == gen_id).first()
            gen_stats[gen_id] = {
                "nombre": generador.nombre if generador else "Unknown",
                "kg": 0,
                "transactions": 0
            }
        gen_stats[gen_id]["kg"] += trans.cantidad_kg
        gen_stats[gen_id]["transactions"] += 1

    top_generators = sorted(
        [{"id": k, **v} for k, v in gen_stats.items()],
        key=lambda x: x["kg"],
        reverse=True
    )[:5]

    # Top receptors
    rec_stats = {}
    for trans in transacciones:
        rec_id = trans.receptor_id
        if rec_id not in rec_stats:
            receptor = db.query(database.ReceptorDB).filter(database.ReceptorDB.id == rec_id).first()
            rec_stats[rec_id] = {
                "nombre": receptor.nombre if receptor else "Unknown",
                "kg": 0,
                "transactions": 0
            }
        rec_stats[rec_id]["kg"] += trans.cantidad_kg
        rec_stats[rec_id]["transactions"] += 1

    top_receptors = sorted(
        [{"id": k, **v} for k, v in rec_stats.items()],
        key=lambda x: x["kg"],
        reverse=True
    )[:5]

    # ---- P0.4 — Separate TRESAAA Surplus GMV from food value ----
    # "Valor comida rescatada" = sum(precio_final * cantidad_kg) — often low
    # because most lots are donated or symbolic. This is NOT the business
    # metric, just a proxy for social impact.
    # "GMV TRESAAA Surplus"          = sum(service_fee + logistics_fee + biomass_revenue).
    # This is what we invoice. Per VERDICT P0.3 we expect this to be 3-10x
    # bigger than the food value on realistic data.
    food_value = sum(
        (t.precio_final or 0.0) * (t.cantidad_kg or 0.0) for t in transacciones
    )
    gmv_service = sum((t.service_fee_eur or 0.0) for t in transacciones)
    gmv_logistics = sum((t.logistics_fee_eur or 0.0) for t in transacciones)
    gmv_biomass = sum((t.biomass_revenue_eur or 0.0) for t in transacciones)
    gmv_tresaaa_surplus = gmv_service + gmv_logistics + gmv_biomass

    # Outcome breakdown for the donut chart
    outcome_breakdown: dict = {}
    for t in transacciones:
        key = t.outcome or "unknown"
        entry = outcome_breakdown.setdefault(
            key, {"transactions": 0, "kg": 0.0, "gmv_tresaaa-surplus": 0.0}
        )
        entry["transactions"] += 1
        entry["kg"] += t.cantidad_kg or 0.0
        entry["gmv_tresaaa-surplus"] += (
            (t.service_fee_eur or 0.0)
            + (t.logistics_fee_eur or 0.0)
            + (t.biomass_revenue_eur or 0.0)
        )

    # Fallback / disposal-guarantee KPI: how many transactions ended in a
    # non-human destination (biogas/compost/cattle_feed). Tracks how often
    # our disposal guarantee actually had to kick in.
    fallback_outcomes = {"biomass_biogas", "energy_biogas", "compost", "cattle_feed"}
    fallback_tx_count = sum(1 for t in transacciones if t.outcome in fallback_outcomes)

    return {
        "summary": {
            "total_kg_saved": round(total_kg, 1),
            "total_transactions": len(transacciones),
            "co2_avoided_kg": round(total_co2, 2),
            # Back-compat: `money_transacted` kept for old clients but now
            # mirrors the clearer `food_value_eur`.
            "money_transacted": round(food_value, 2),
            "food_value_eur": round(food_value, 2),
            "gmv_tresaaa-surplus_eur": round(gmv_tresaaa-surplus, 2),
            "gmv_service_fee_eur": round(gmv_service, 2),
            "gmv_logistics_fee_eur": round(gmv_logistics, 2),
            "gmv_biomass_revenue_eur": round(gmv_biomass, 2),
            "fallback_tx_count": fallback_tx_count,
            "num_generadores": db.query(database.GeneradorDB).count(),
            "num_receptores": db.query(database.ReceptorDB).count()
        },
        "time_series": {
            "transactions_per_day": trans_by_day
        },
        "categories": category_stats,
        "outcomes": outcome_breakdown,
        "top_generators": top_generators,
        "top_receptors": top_receptors,
        "compliance_stats": {
            "total_documents_generated": db.query(database.ComplianceDocDB).count(),
            "carbon_credits_issued": db.query(database.CarbonCreditDB).count()
        }
    }


@app.get("/carbon-footprints", tags=["Statistics"])
def get_carbon_footprints():
    """Get CO2 footprint data for all product categories - public"""
    return carbon.get_sector_footprints()


# ==================== SUBSCRIPTION PLANS (P0.5) ====================

@app.get("/subscriptions/plans", response_model=List[models.SubscriptionPlan], tags=["Pricing"])
def list_subscription_plans(db: Session = Depends(get_db)):
    """List the 3 canonical TRESAAA Surplus pricing tiers.

    Seeded (idempotently) on startup from VERDICT_BUSINESS_MODEL.md:
      * Starter     €0/mes     · hasta 5 lotes/mes
      * Pro         €199/mes   · hasta 20 lotes/mes, API read-only, dashboard
      * Enterprise  €4.999/mes · unlimited, API write, gestor cuenta, SLA 99.9%

    Lot fee per unit: €25 base + €0.25/km (min €25) — enforced in
    POST /transactions (see P0.2).
    """
    # Make sure the seed ran at least once — cheap to call.
    try:
        database.seed_subscription_plans()
    except Exception:
        pass
    plans = db.query(database.SubscriptionPlanDB).order_by(
        database.SubscriptionPlanDB.price_monthly_eur.asc()
    ).all()
    return [
        models.SubscriptionPlan(
            id=p.id,
            name=p.name,
            price_monthly_eur=p.price_monthly_eur,
            max_lots_month=p.max_lots_month,
            includes=p.includes or {},
        )
        for p in plans
    ]


@app.get("/price-suggestion", tags=["Pricing"])
def suggest_price(
    categoria: models.Categoria,
    cantidad_kg: float,
    tipo_generador: models.TipoGenerador,
    dias_hasta_expiry: int = 7
):
    """Suggest base price for a new lot - public"""

    suggested_price = pricing.suggest_price_for_generator(
        categoria.value,
        cantidad_kg,
        tipo_generador.value,
        dias_hasta_expiry
    )

    return {
        "categoria": categoria.value,
        "cantidad_kg": cantidad_kg,
        "tipo_generador": tipo_generador.value,
        "precio_sugerido_eur": suggested_price,
        "precio_por_kg": round(suggested_price / cantidad_kg, 2) if cantidad_kg > 0 else 0
    }


# ---- Waitlist ----

class WaitlistEntry(BaseModel):
    nombre: str
    empresa: str
    email: str
    telefono: str = ""
    sector: str = ""

class WaitlistEntryResponse(BaseModel):
    status: str
    message: str = ""

@app.post("/waitlist/", response_model=WaitlistEntryResponse, tags=["Waitlist"], status_code=201)
async def join_waitlist(entry: WaitlistEntry, db: Session = Depends(database.get_db)):
    existing = db.query(database.WaitlistEntryDB).filter_by(email=entry.email).first()
    if existing:
        return {"status": "already_registered", "message": "Email ya registrado"}
    db.add(database.WaitlistEntryDB(
        nombre=entry.nombre,
        empresa=entry.empresa,
        email=entry.email,
        telefono=entry.telefono,
        sector=entry.sector,
    ))
    db.commit()
    return {"status": "ok", "message": "Te avisamos antes del lanzamiento"}

@app.get("/waitlist/count", tags=["Waitlist"])
async def waitlist_count(db: Session = Depends(database.get_db)):
    count = db.query(database.WaitlistEntryDB).count()
    return {"count": count}

@app.get("/waitlist/admin", tags=["Waitlist"])
async def waitlist_list(db: Session = Depends(database.get_db), current_user: auth.UserDB = Depends(auth.get_current_user)):
    if current_user.rol != "admin":
        raise HTTPException(403, "Solo admins")
    entries = db.query(database.WaitlistEntryDB).order_by(database.WaitlistEntryDB.created_at.desc()).all()
    return [{"id": e.id, "nombre": e.nombre, "empresa": e.empresa, "email": e.email,
             "telefono": e.telefono, "sector": e.sector, "contacted": e.contacted,
             "created_at": e.created_at.isoformat()} for e in entries]


# ---- Root redirect ----
# Anyone hitting https://tresaaa-surplus.es/ lands on the SPA at /app/.
# 302 (not 301) to avoid aggressive browser caching while the app evolves.
@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/app/", status_code=302)


# ---- Serve frontend ----
# Mount the static SPA at /app so the same container serves both API and UI.
# This keeps the deploy single-service (Railway / any PaaS) without a separate
# nginx box. Register this LAST so /docs, /health, /auth/*, etc. still resolve.
#
# Path resolution is tolerant: we search common container layouts because
# different deploy targets (Railway Dockerfile, Nixpacks, local dev) put the
# frontend dir in different absolute locations.
_candidate_frontend_paths = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend")),
    "/frontend",
    "/app/frontend",
    os.path.abspath(os.path.join(os.getcwd(), "frontend")),
    os.path.abspath(os.path.join(os.getcwd(), "..", "frontend")),
]
_frontend_path = None
for _p in _candidate_frontend_paths:
    if os.path.isdir(_p) and os.path.isfile(os.path.join(_p, "index.html")):
        _frontend_path = _p
        break

if _frontend_path:
    print(f"[frontend] mounting {_frontend_path} at /app", flush=True)
    app.mount(
        "/app",
        StaticFiles(directory=_frontend_path, html=True),
        name="frontend",
    )
else:
    print(f"[frontend] WARNING: no frontend dir found. Tried: {_candidate_frontend_paths}", flush=True)


@app.get("/_debug/frontend", include_in_schema=False)
async def _debug_frontend():
    """Diagnostic: reports what frontend path is mounted and what's at the common candidates."""
    info = {
        "cwd": os.getcwd(),
        "__file__": __file__,
        "mounted_path": _frontend_path,
        "candidates": [
            {"path": p, "is_dir": os.path.isdir(p), "has_index": os.path.isfile(os.path.join(p, "index.html"))}
            for p in _candidate_frontend_paths
        ],
    }
    return info


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
