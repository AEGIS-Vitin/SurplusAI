"""
AEGIS-FOOD: B2B Food Surplus Marketplace
Main FastAPI application with JWT authentication and email notifications.
"""

from fastapi import FastAPI, Depends, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
import os
from dotenv import load_dotenv

import models
import database
import pricing
import compliance
import matching
import carbon
import auth
import notifications

load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="AEGIS-FOOD API",
    description="B2B Food Surplus Marketplace para cumplir Ley 1/2025",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database (only if not in test mode)
if os.getenv("TESTING", "false").lower() != "true":
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
    user = auth.create_user(
        db,
        email=user_data.email,
        password=user_data.password,
        empresa_id=user_data.empresa_id,
        nombre_empresa=user_data.nombre_empresa,
        rol=user_data.rol
    )

    return user


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
        # For testing, store location as string if geoalchemy2 not available
        if os.getenv("TESTING", "false").lower() == "true":
            ubicacion = f"POINT({generador.ubicacion_lon} {generador.ubicacion_lat})"
        else:
            from geoalchemy2 import func as gf
            ubicacion = gf.ST_GeomFromText(f"POINT({generador.ubicacion_lon} {generador.ubicacion_lat})", 4326)

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

        return db_generador
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

    return generador


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
        # For testing, store location as string if geoalchemy2 not available
        if os.getenv("TESTING", "false").lower() == "true":
            ubicacion = f"POINT({receptor.ubicacion_lon} {receptor.ubicacion_lat})"
        else:
            from geoalchemy2 import func as gf
            ubicacion = gf.ST_GeomFromText(f"POINT({receptor.ubicacion_lon} {receptor.ubicacion_lat})", 4326)

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

        return db_receptor
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

    return receptor


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

    # Calculate initial price
    precio_actual = pricing.calculate_dynamic_price(
        lote.precio_base,
        lote.fecha_limite,
        datetime.utcnow(),
        num_bids=0,
        categoria=lote.categoria.value
    )

    try:
        # For testing, store location as string if geoalchemy2 not available
        if os.getenv("TESTING", "false").lower() == "true":
            ubicacion = f"POINT({lote.ubicacion_lon} {lote.ubicacion_lat})"
        else:
            from geoalchemy2 import func as gf
            ubicacion = gf.ST_GeomFromText(f"POINT({lote.ubicacion_lon} {lote.ubicacion_lat})", 4326)

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

        return db_lote
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
    if ubicacion_lat and ubicacion_lon and os.getenv("TESTING", "false").lower() != "true":
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

        result.append(models.LoteWithBids(
            **{**lote.__dict__, "num_bids": num_bids, "precio_oferta_mas_alta": precio_mas_alto[0] if precio_mas_alto else None}
        ))

    return result


@app.get("/lots/{lot_id}", response_model=models.Lote, tags=["Lotes"])
def get_lot(lot_id: int, db: Session = Depends(get_db)):
    """Get lot details - public"""

    lote = db.query(database.LoteDB).filter(
        database.LoteDB.id == lot_id
    ).first()

    if not lote:
        raise HTTPException(status_code=404, detail="Lote no encontrado")

    return lote


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

        # Update lot's dynamic price
        num_bids = db.query(database.PujaDB).filter(
            database.PujaDB.lote_id == lote.id
        ).count()

        lote.precio_actual = pricing.calculate_dynamic_price(
            lote.precio_base,
            lote.fecha_limite,
            lote.fecha_publicacion,
            num_bids=num_bids,
            categoria=lote.categoria.value
        )

        db.commit()
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
        estado=models.EstadoTransaccion.completada
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

    return {
        "summary": {
            "total_kg_saved": round(total_kg, 1),
            "total_transactions": len(transacciones),
            "co2_avoided_kg": round(total_co2, 2),
            "money_transacted": round(total_value, 2),
            "num_generadores": db.query(database.GeneradorDB).count(),
            "num_receptores": db.query(database.ReceptorDB).count()
        },
        "time_series": {
            "transactions_per_day": trans_by_day
        },
        "categories": category_stats,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
