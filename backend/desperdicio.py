"""
Desperdicio.es — Producto certificados PDF + gestión inventario.

Mass-market low-price (€1.99-19.99/mes). Distinto de SurplusAI marketplace B2B.

Endpoints:
  POST   /api/v1/certificate/generate          → genera PDF (con/sin auth para Free tier)
  GET    /api/v1/certificate/verify/{hash}     → verificación pública (QR target)
  GET    /api/v1/certificate/mine              → histórico certificados del user autenticado
  POST   /api/v1/inventory/items               → crear item inventario
  GET    /api/v1/inventory/items               → listar items del user
  PATCH  /api/v1/inventory/items/{id}          → actualizar (status, cantidad, etc.)
  DELETE /api/v1/inventory/items/{id}          → eliminar
  GET    /api/v1/inventory/expiring            → próximos a caducar (default 7 días)

Plan tiers (free / solo €1.99 / pro €9.99 / plus €19.99) controla:
  - Free: 3 certificados/mes total, marca TRESAAA visible, sin inventario
  - Solo: certificados ilimitados, inventario hasta 50 items
  - Pro: + logo propio, histórico web 12 meses, inventario ilimitado
  - Plus: + multi-local, dashboard avanzado, export Holded
"""
from __future__ import annotations

import hashlib
import io
import os
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from database import SessionLocal, PdfCertificateDB, InventoryItemDB, UserDB, NotificationChannelDB, MagicLinkTokenDB
from auth import verify_token, create_access_token
from fastapi import status

router = APIRouter(prefix="/api/v1", tags=["desperdicio"])


def extract_token(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """Extract JWT token from Authorization header (Bearer scheme).

    Local copy of the helper in main.py to keep this module self-contained.
    """
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def get_current_user(token: Optional[str], db: Session) -> UserDB:
    """Sync version of auth.get_current_user.

    auth.get_current_user is async but its body has no awaits, so we just
    re-implement it sync to avoid having to make every endpoint async.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        token_data = verify_token(token)
    except HTTPException:
        raise credentials_exception

    user = db.query(UserDB).filter(UserDB.email == token_data.email).first()
    if user is None:
        raise credentials_exception
    return user


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# Pydantic schemas
# ============================================================================

class CertificateCreate(BaseModel):
    user_email: EmailStr
    business_name: str = Field(..., min_length=2, max_length=255)
    nif: Optional[str] = Field(None, max_length=32)
    fecha_evento: datetime
    producto: str = Field(..., min_length=2, max_length=500)
    cantidad: float = Field(..., gt=0)
    unidad: str = Field("kg", max_length=32)
    destino: str = Field(..., max_length=64)
    destino_detalle: Optional[str] = Field(None, max_length=255)
    foto_url: Optional[str] = None
    inventory_item_id: Optional[int] = None


class CertificateResponse(BaseModel):
    id: int
    hash_sha256: str
    pdf_url: Optional[str]
    verify_url: str
    business_name: str
    producto: str
    cantidad: float
    unidad: str
    destino: str
    fecha_evento: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class CertificateVerifyResponse(BaseModel):
    business_name: str
    fecha_evento: datetime
    producto: str
    cantidad: float
    unidad: str
    destino: str
    destino_detalle: Optional[str]
    hash_sha256: str
    issued_at: datetime
    valid: bool = True


class InventoryItemCreate(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=255)
    categoria: Optional[str] = Field(None, max_length=64)
    cantidad: float = Field(..., gt=0)
    unidad: str = Field("kg", max_length=32)
    fecha_compra: Optional[datetime] = None
    fecha_caducidad: datetime
    lote: Optional[str] = Field(None, max_length=64)
    proveedor: Optional[str] = Field(None, max_length=255)
    proveedor_nif: Optional[str] = Field(None, max_length=32)
    precio_unitario: Optional[float] = None
    foto_url: Optional[str] = None
    notas: Optional[str] = None


class InventoryItemUpdate(BaseModel):
    nombre: Optional[str] = None
    cantidad: Optional[float] = None
    status: Optional[str] = None
    notas: Optional[str] = None


class InventoryItemResponse(BaseModel):
    id: int
    nombre: str
    categoria: Optional[str]
    cantidad: float
    unidad: str
    fecha_compra: Optional[datetime]
    fecha_caducidad: datetime
    proveedor: Optional[str]
    foto_url: Optional[str]
    status: str
    source: str
    days_to_expire: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Helpers
# ============================================================================

def _compute_hash(cert: dict) -> str:
    canonical = (
        f"{cert['user_email']}|{cert['business_name']}|{cert.get('nif') or ''}|"
        f"{cert['fecha_evento'].isoformat()}|{cert['producto']}|{cert['cantidad']}|"
        f"{cert['unidad']}|{cert['destino']}|{cert.get('destino_detalle') or ''}"
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _destino_legible(destino: str) -> str:
    mapping = {
        "food_bank": "Donación a Banco de Alimentos",
        "donated_ong": "Donación a ONG / asociación social",
        "cattle_feed": "Alimentación animal (SANDACH)",
        "compost": "Compostaje aeróbico",
        "energy_biogas": "Valorización energética (biogás)",
        "biomass_biogas": "Materia prima biogás",
        "consumido_personal": "Consumo propio / empleados",
        "retirado": "Retirada por gestor autorizado",
    }
    return mapping.get(destino, destino)


def _generate_pdf_bytes(cert_data: dict, hash_sha256: str, verify_url: str) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.graphics.barcode import qr
        from reportlab.graphics.shapes import Drawing
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"reportlab no instalado: {e}")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=20 * mm, rightMargin=20 * mm,
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "Title2", parent=styles["Title"],
        fontSize=20, textColor=colors.HexColor("#2A9D8F"), alignment=1, spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "Sub2", parent=styles["Normal"],
        fontSize=11, textColor=colors.HexColor("#666666"), alignment=1, spaceAfter=20,
    )
    section_style = ParagraphStyle(
        "Section2", parent=styles["Heading2"],
        fontSize=13, textColor=colors.HexColor("#2A9D8F"), spaceAfter=8,
    )
    body_style = ParagraphStyle("Body2", parent=styles["Normal"], fontSize=10, leading=14)
    legal_style = ParagraphStyle(
        "Legal2", parent=styles["Normal"], fontSize=8,
        textColor=colors.HexColor("#888888"), leading=11, spaceAfter=6,
    )

    story = []
    story.append(Paragraph("CERTIFICADO DE TRAZABILIDAD", title_style))
    story.append(Paragraph(
        "Documento de gestión responsable de excedente alimentario", subtitle_style
    ))

    fecha_str = cert_data["fecha_evento"].strftime("%d/%m/%Y %H:%M")
    issued_str = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")
    destino_legible = _destino_legible(cert_data["destino"])

    data_rows = [["Establecimiento", cert_data["business_name"]]]
    if cert_data.get("nif"):
        data_rows.append(["NIF", cert_data["nif"]])
    data_rows.extend([
        ["Fecha del evento", fecha_str],
        ["Producto", cert_data["producto"]],
        ["Cantidad", f"{cert_data['cantidad']:g} {cert_data['unidad']}"],
        ["Destino", destino_legible],
    ])
    if cert_data.get("destino_detalle"):
        data_rows.append(["Detalle", cert_data["destino_detalle"]])

    tbl = Table(data_rows, colWidths=[55 * mm, 110 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F4F4F4")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 16 * mm))

    story.append(Paragraph("Verificación pública", section_style))

    qr_code = qr.QrCodeWidget(verify_url, barLevel="M")
    bounds = qr_code.getBounds()
    qr_w = bounds[2] - bounds[0]
    qr_h = bounds[3] - bounds[1]
    qr_size = 28 * mm
    drawing = Drawing(qr_size, qr_size, transform=[qr_size / qr_w, 0, 0, qr_size / qr_h, 0, 0])
    drawing.add(qr_code)

    qr_table = Table([[drawing, Paragraph(
        "Este documento es verificable públicamente.<br/>"
        f"Escanea el QR o visita:<br/><font color='#2A9D8F'>{verify_url}</font><br/><br/>"
        f"<b>Hash SHA-256:</b><br/>"
        f"<font name='Courier' size='7'>{hash_sha256}</font><br/><br/>"
        f"<b>Emitido:</b> {issued_str}",
        body_style,
    )]], colWidths=[35 * mm, 130 * mm])
    qr_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(qr_table)
    story.append(Spacer(1, 12 * mm))

    story.append(Paragraph(
        "Este certificado documenta la gestión declarada del producto alimentario "
        "indicado conforme a los principios de prevención del desperdicio "
        "(Ley 1/2025) y la jerarquía de uso establecida. La veracidad de los "
        "datos declarados es responsabilidad del emisor. El hash criptográfico "
        "SHA-256 garantiza la integridad del documento.",
        legal_style,
    ))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "Generado por TRESAAA · Plataforma de trazabilidad alimentaria · desperdicio.es",
        legal_style,
    ))

    doc.build(story)
    return buf.getvalue()


def _upload_to_storage(pdf_bytes: bytes, filename: str) -> Optional[str]:
    bucket = os.getenv("R2_BUCKET")
    endpoint = os.getenv("R2_ENDPOINT")
    public_base = os.getenv("R2_PUBLIC_BASE_URL")
    access_key = os.getenv("R2_ACCESS_KEY_ID")
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY")

    if not all([bucket, endpoint, access_key, secret_key]):
        return None

    try:
        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
        )
        s3.put_object(
            Bucket=bucket,
            Key=filename,
            Body=pdf_bytes,
            ContentType="application/pdf",
            CacheControl="public, max-age=31536000",
        )
        if public_base:
            return f"{public_base.rstrip('/')}/{filename}"
        return f"{endpoint.rstrip('/')}/{bucket}/{filename}"
    except Exception as e:
        print(f"[desperdicio] upload R2 fallo: {e}")
        return None


# ============================================================================
# Certificate endpoints
# ============================================================================

@router.post("/certificate/generate", response_model=CertificateResponse, status_code=201)
def generate_certificate(payload: CertificateCreate, db: Session = Depends(get_db)):
    base_url = os.getenv("PUBLIC_BASE_URL", "https://surplusai.es")

    user = db.query(UserDB).filter(UserDB.email == payload.user_email).first()
    user_id = user.id if user else None

    # Rate-limit Free: 3 certs/mes por email sin auth
    if not user:
        one_month_ago = datetime.utcnow() - timedelta(days=30)
        cnt = db.query(PdfCertificateDB).filter(
            PdfCertificateDB.user_email == payload.user_email,
            PdfCertificateDB.created_at >= one_month_ago,
        ).count()
        if cnt >= 3:
            raise HTTPException(
                status_code=429,
                detail="Tier gratuito: 3 certificados/mes. Suscríbete a Solo €1.99/mes para ilimitados.",
            )

    cert_dict = payload.model_dump()
    hash_sha256 = _compute_hash(cert_dict)

    existing = db.query(PdfCertificateDB).filter_by(hash_sha256=hash_sha256).first()
    if existing:
        return CertificateResponse(
            id=existing.id,
            hash_sha256=existing.hash_sha256,
            pdf_url=existing.pdf_url,
            verify_url=f"{base_url}/api/v1/certificate/verify/{existing.hash_sha256}",
            business_name=existing.business_name,
            producto=existing.producto,
            cantidad=existing.cantidad,
            unidad=existing.unidad,
            destino=existing.destino,
            fecha_evento=existing.fecha_evento,
            created_at=existing.created_at,
        )

    verify_url = f"{base_url}/api/v1/certificate/verify/{hash_sha256}"
    pdf_bytes = _generate_pdf_bytes(cert_dict, hash_sha256, verify_url)
    filename = f"certificates/{hash_sha256}.pdf"
    pdf_url = _upload_to_storage(pdf_bytes, filename)

    row = PdfCertificateDB(
        user_id=user_id,
        user_email=payload.user_email,
        business_name=payload.business_name,
        nif=payload.nif,
        fecha_evento=payload.fecha_evento,
        producto=payload.producto,
        cantidad=payload.cantidad,
        unidad=payload.unidad,
        destino=payload.destino,
        destino_detalle=payload.destino_detalle,
        foto_url=payload.foto_url,
        pdf_url=pdf_url,
        hash_sha256=hash_sha256,
        inventory_item_id=payload.inventory_item_id,
        plan="solo" if user_id else "free",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    if payload.inventory_item_id and user_id:
        item = db.query(InventoryItemDB).filter(
            InventoryItemDB.id == payload.inventory_item_id,
            InventoryItemDB.user_id == user_id,
        ).first()
        if item:
            new_status_map = {
                "food_bank": "donado", "donated_ong": "donado",
                "cattle_feed": "donado", "compost": "donado",
                "energy_biogas": "donado", "biomass_biogas": "donado",
                "consumido_personal": "consumido", "retirado": "retirado",
            }
            item.status = new_status_map.get(payload.destino, "retirado")
            db.commit()

    # Email automático post-generación (Sprint 4) — best effort, no bloquea
    try:
        from desperdicio_email import send_certificate_email
        pdf_link = pdf_url or f"{base_url}/api/v1/certificate/{hash_sha256}/pdf"
        send_certificate_email(
            user_email=payload.user_email,
            business_name=payload.business_name,
            producto=payload.producto,
            cantidad=payload.cantidad,
            unidad=payload.unidad,
            destino_legible=_destino_legible(payload.destino),
            fecha_evento_str=payload.fecha_evento.strftime("%d/%m/%Y %H:%M"),
            pdf_url=pdf_link,
            verify_url=verify_url,
            hash_sha256=hash_sha256,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("[desperdicio] email auto fail: %s", e)

    return CertificateResponse(
        id=row.id,
        hash_sha256=row.hash_sha256,
        pdf_url=row.pdf_url,
        verify_url=verify_url,
        business_name=row.business_name,
        producto=row.producto,
        cantidad=row.cantidad,
        unidad=row.unidad,
        destino=row.destino,
        fecha_evento=row.fecha_evento,
        created_at=row.created_at,
    )


@router.get("/certificate/{hash_sha256}/pdf")
def get_certificate_pdf(hash_sha256: str, db: Session = Depends(get_db)):
    row = db.query(PdfCertificateDB).filter_by(hash_sha256=hash_sha256).first()
    if not row:
        raise HTTPException(status_code=404, detail="Certificado no encontrado")

    if row.pdf_url:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=row.pdf_url)

    base_url = os.getenv("PUBLIC_BASE_URL", "https://surplusai.es")
    cert_data = {
        "user_email": row.user_email,
        "business_name": row.business_name,
        "nif": row.nif,
        "fecha_evento": row.fecha_evento,
        "producto": row.producto,
        "cantidad": row.cantidad,
        "unidad": row.unidad,
        "destino": row.destino,
        "destino_detalle": row.destino_detalle,
    }
    verify_url = f"{base_url}/api/v1/certificate/verify/{hash_sha256}"
    pdf_bytes = _generate_pdf_bytes(cert_data, hash_sha256, verify_url)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="certificado-{hash_sha256[:8]}.pdf"'},
    )


@router.get("/certificate/verify/{hash_sha256}", response_model=CertificateVerifyResponse)
def verify_certificate(hash_sha256: str, db: Session = Depends(get_db)):
    row = db.query(PdfCertificateDB).filter_by(hash_sha256=hash_sha256).first()
    if not row:
        raise HTTPException(status_code=404, detail="Certificado no encontrado o hash inválido")
    return CertificateVerifyResponse(
        business_name=row.business_name,
        fecha_evento=row.fecha_evento,
        producto=row.producto,
        cantidad=row.cantidad,
        unidad=row.unidad,
        destino=_destino_legible(row.destino),
        destino_detalle=row.destino_detalle,
        hash_sha256=row.hash_sha256,
        issued_at=row.created_at,
        valid=True,
    )


# ============================================================================
# Inventory endpoints
# ============================================================================

def _to_inventory_response(item: InventoryItemDB) -> InventoryItemResponse:
    delta = item.fecha_caducidad - datetime.utcnow()
    return InventoryItemResponse(
        id=item.id,
        nombre=item.nombre,
        categoria=item.categoria,
        cantidad=item.cantidad,
        unidad=item.unidad,
        fecha_compra=item.fecha_compra,
        fecha_caducidad=item.fecha_caducidad,
        proveedor=item.proveedor,
        foto_url=item.foto_url,
        status=item.status,
        source=item.source,
        days_to_expire=delta.days,
        created_at=item.created_at,
    )


@router.post("/inventory/items", response_model=InventoryItemResponse, status_code=201)
def create_inventory_item(
    payload: InventoryItemCreate,
    db: Session = Depends(get_db),
    token: str = Depends(extract_token),
):
    user = get_current_user(token, db)
    item = InventoryItemDB(
        user_id=user.id,
        nombre=payload.nombre,
        categoria=payload.categoria,
        cantidad=payload.cantidad,
        unidad=payload.unidad,
        fecha_compra=payload.fecha_compra,
        fecha_caducidad=payload.fecha_caducidad,
        lote=payload.lote,
        proveedor=payload.proveedor,
        proveedor_nif=payload.proveedor_nif,
        precio_unitario=payload.precio_unitario,
        foto_url=payload.foto_url,
        notas=payload.notas,
        source="manual",
        status="vigente",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _to_inventory_response(item)


@router.get("/inventory/items", response_model=List[InventoryItemResponse])
def list_inventory_items(
    status_filter: Optional[str] = Query(None, alias="status"),
    category: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    token: str = Depends(extract_token),
):
    user = get_current_user(token, db)
    q = db.query(InventoryItemDB).filter(InventoryItemDB.user_id == user.id)
    if status_filter:
        q = q.filter(InventoryItemDB.status == status_filter)
    if category:
        q = q.filter(InventoryItemDB.categoria == category)
    q = q.order_by(InventoryItemDB.fecha_caducidad.asc()).limit(limit)
    return [_to_inventory_response(it) for it in q.all()]


@router.patch("/inventory/items/{item_id}", response_model=InventoryItemResponse)
def update_inventory_item(
    item_id: int,
    payload: InventoryItemUpdate,
    db: Session = Depends(get_db),
    token: str = Depends(extract_token),
):
    user = get_current_user(token, db)
    item = db.query(InventoryItemDB).filter(
        InventoryItemDB.id == item_id, InventoryItemDB.user_id == user.id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    if payload.nombre is not None:
        item.nombre = payload.nombre
    if payload.cantidad is not None:
        item.cantidad = payload.cantidad
    if payload.status is not None:
        valid_status = {"vigente", "consumido", "donado", "caducado", "retirado"}
        if payload.status not in valid_status:
            raise HTTPException(status_code=400, detail=f"Status inválido. Permitidos: {valid_status}")
        item.status = payload.status
    if payload.notas is not None:
        item.notas = payload.notas
    db.commit()
    db.refresh(item)
    return _to_inventory_response(item)


@router.delete("/inventory/items/{item_id}", status_code=204)
def delete_inventory_item(
    item_id: int,
    db: Session = Depends(get_db),
    token: str = Depends(extract_token),
):
    user = get_current_user(token, db)
    item = db.query(InventoryItemDB).filter(
        InventoryItemDB.id == item_id, InventoryItemDB.user_id == user.id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    db.delete(item)
    db.commit()
    return None


@router.get("/inventory/expiring", response_model=List[InventoryItemResponse])
def list_expiring_items(
    days_ahead: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    token: str = Depends(extract_token),
):
    user = get_current_user(token, db)
    cutoff = datetime.utcnow() + timedelta(days=days_ahead)
    items = (
        db.query(InventoryItemDB)
        .filter(
            InventoryItemDB.user_id == user.id,
            InventoryItemDB.status == "vigente",
            InventoryItemDB.fecha_caducidad <= cutoff,
        )
        .order_by(InventoryItemDB.fecha_caducidad.asc())
        .all()
    )
    return [_to_inventory_response(it) for it in items]


@router.get("/desperdicio/health")
def health():
    return {"status": "ok", "service": "desperdicio.es", "version": "1.0"}


# ============================================================================
# Notification channels (Sprint 2)
# ============================================================================

class WebPushSubscriptionPayload(BaseModel):
    user_email: EmailStr
    endpoint: str
    p256dh: str
    auth: str


class TelegramLinkPayload(BaseModel):
    user_email: EmailStr
    chat_id: str


class NotificationChannelResponse(BaseModel):
    id: int
    channel_type: str
    enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/push/subscribe", response_model=NotificationChannelResponse, status_code=201)
def push_subscribe(payload: WebPushSubscriptionPayload, db: Session = Depends(get_db)):
    """Guarda la PushSubscription que generó el navegador del cliente.

    El frontend manda esto justo después de aceptar el permiso de notificaciones.
    """
    user = db.query(UserDB).filter(UserDB.email == payload.user_email).first()
    user_id = user.id if user else None

    # Idempotencia: si ya hay subscription con mismo endpoint, devolvemos esa
    existing = db.query(NotificationChannelDB).filter(
        NotificationChannelDB.user_email == payload.user_email,
        NotificationChannelDB.channel_type == "web_push",
    ).all()
    for ex in existing:
        if (ex.payload or {}).get("endpoint") == payload.endpoint:
            ex.enabled = True
            db.commit()
            return NotificationChannelResponse(
                id=ex.id, channel_type=ex.channel_type, enabled=ex.enabled, created_at=ex.created_at,
            )

    sub_dict = {
        "endpoint": payload.endpoint,
        "keys": {"p256dh": payload.p256dh, "auth": payload.auth},
    }
    row = NotificationChannelDB(
        user_id=user_id,
        user_email=payload.user_email,
        channel_type="web_push",
        payload=sub_dict,
        enabled=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return NotificationChannelResponse(
        id=row.id, channel_type=row.channel_type, enabled=row.enabled, created_at=row.created_at,
    )


@router.post("/telegram/link", response_model=NotificationChannelResponse, status_code=201)
def telegram_link(payload: TelegramLinkPayload, db: Session = Depends(get_db)):
    """Vincula un chat_id de Telegram a un email de usuario.

    El cliente abre el bot @Vitinceo_bot, escribe /start, el bot le devuelve un
    enlace mágico tipo desperdicio.es/vincular?chat_id=XXX que pre-rellena este endpoint.
    """
    user = db.query(UserDB).filter(UserDB.email == payload.user_email).first()
    user_id = user.id if user else None

    existing = db.query(NotificationChannelDB).filter(
        NotificationChannelDB.user_email == payload.user_email,
        NotificationChannelDB.channel_type == "telegram",
    ).first()
    if existing:
        existing.payload = {"chat_id": payload.chat_id}
        existing.enabled = True
        db.commit()
        return NotificationChannelResponse(
            id=existing.id, channel_type=existing.channel_type,
            enabled=existing.enabled, created_at=existing.created_at,
        )

    row = NotificationChannelDB(
        user_id=user_id,
        user_email=payload.user_email,
        channel_type="telegram",
        payload={"chat_id": payload.chat_id},
        enabled=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return NotificationChannelResponse(
        id=row.id, channel_type=row.channel_type, enabled=row.enabled, created_at=row.created_at,
    )


@router.delete("/notifications/{channel_id}", status_code=204)
def disable_channel(channel_id: int, user_email: str = Query(...), db: Session = Depends(get_db)):
    """Desactiva un canal (no lo borra para no perder el endpoint si re-suscribe)."""
    ch = db.query(NotificationChannelDB).filter(
        NotificationChannelDB.id == channel_id,
        NotificationChannelDB.user_email == user_email,
    ).first()
    if not ch:
        raise HTTPException(status_code=404, detail="Canal no encontrado")
    ch.enabled = False
    db.commit()
    return None


@router.get("/push/public-key")
def push_public_key():
    """Devuelve la VAPID public key para que el frontend pueda llamar a
    PushManager.subscribe({applicationServerKey: ...}).
    """
    return {"vapid_public_key": os.getenv("VAPID_PUBLIC_KEY", "")}


@router.post("/notifications/check-expiring")
def check_expiring_and_notify(user_email: EmailStr, days_ahead: int = 3, db: Session = Depends(get_db)):
    """Comprueba items próximos a caducar y dispara notificación multi-canal.

    Útil para llamarlo desde el frontend al cargar la app (sin cron server-side).
    En producción habrá también un job que recorre todos los users.
    """
    user = db.query(UserDB).filter(UserDB.email == user_email).first()
    if not user:
        return {"items_found": 0, "notifications_sent": {}}

    cutoff = datetime.utcnow() + timedelta(days=days_ahead)
    items = (
        db.query(InventoryItemDB)
        .filter(
            InventoryItemDB.user_id == user.id,
            InventoryItemDB.status == "vigente",
            InventoryItemDB.fecha_caducidad <= cutoff,
        )
        .order_by(InventoryItemDB.fecha_caducidad.asc())
        .limit(10)
        .all()
    )

    if not items:
        return {"items_found": 0, "notifications_sent": {}}

    # Mensaje compacto con los próximos a caducar
    lines = []
    for it in items[:5]:
        delta = (it.fecha_caducidad - datetime.utcnow()).days
        when = "hoy" if delta == 0 else (f"en {delta} días" if delta > 0 else f"caducó hace {-delta} días")
        lines.append(f"• {it.nombre} ({it.cantidad:g} {it.unidad}) — {when}")

    title = f"⚠️ {len(items)} producto(s) próximo(s) a caducar"
    body = "\n".join(lines)
    url = "https://desperdicio.es/#empezar"

    from notifications_v2 import send_alert
    results = send_alert(db, user_email, title=title, body=body, url=url)
    return {"items_found": len(items), "notifications_sent": results}


# ============================================================================
# Telegram bot webhook (recibe /start de los clientes)
# ============================================================================

@router.post("/telegram/webhook")
def telegram_webhook(payload: dict, db: Session = Depends(get_db)):
    """Endpoint que recibe los updates del bot @Vitinceo_bot via webhook.

    Acepta solo el comando /vincular {hash}, que el cliente lanza desde el bot.
    El {hash} se le entrega en el flujo de registro de desperdicio.es y vincula
    su chat_id al user_email correspondiente.
    """
    msg = payload.get("message", {})
    text = (msg.get("text") or "").strip()
    chat_id = (msg.get("chat") or {}).get("id")
    if not chat_id or not text:
        return {"ok": True}

    # /start con parámetro (Telegram deep-link)
    if text.startswith("/start") or text.startswith("/vincular"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            from notifications_v2 import send_telegram
            send_telegram(
                str(chat_id),
                "👋 Hola, soy el bot de desperdicio.es.\n\n"
                "Para vincular tu cuenta:\n"
                "1. Entra en desperdicio.es\n"
                "2. Ve a tu perfil → Notificaciones\n"
                "3. Pulsa 'Conectar Telegram'\n"
                "4. Me llegará un código que pegas y ya estás listo."
            )
            return {"ok": True}

        token = parts[1].strip()
        # En esta versión inicial el token = email del cliente (debería ser un OTP)
        if "@" in token:
            row = NotificationChannelDB(
                user_id=None,
                user_email=token,
                channel_type="telegram",
                payload={"chat_id": str(chat_id)},
                enabled=True,
            )
            db.add(row)
            db.commit()
            from notifications_v2 import send_telegram
            send_telegram(
                str(chat_id),
                f"✅ Telegram vinculado a {token}.\n\nTe avisaré cuando tengas productos próximos a caducar."
            )
        else:
            from notifications_v2 import send_telegram
            send_telegram(str(chat_id), "❌ Token no válido. Vuelve a desperdicio.es y prueba de nuevo.")

    return {"ok": True}


# ============================================================================
# Magic-link auth (Sprint 5) — sin password
# ============================================================================

class MagicLinkRequest(BaseModel):
    user_email: EmailStr


class MagicLinkVerifyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_email: str


@router.post("/auth/magic-link/request", status_code=202)
def request_magic_link(payload: MagicLinkRequest, db: Session = Depends(get_db)):
    """Pide un magic link de acceso. Genera token + envía email."""
    import secrets
    magic_token = secrets.token_urlsafe(48)
    expires_at = datetime.utcnow() + timedelta(minutes=15)

    row = MagicLinkTokenDB(
        user_email=payload.user_email,
        token=magic_token,
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()

    base_url = os.getenv("PUBLIC_BASE_URL", "https://desperdicio.es")
    magic_link = f"{base_url}/auth.html?token={magic_token}"

    try:
        from desperdicio_email import send_magic_link_email
        send_magic_link_email(payload.user_email, magic_link)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("[magic-link] email fail: %s", e)

    return {"sent": True, "expires_in_seconds": 900}


@router.get("/auth/magic-link/verify", response_model=MagicLinkVerifyResponse)
def verify_magic_link(token: str = Query(..., min_length=20), db: Session = Depends(get_db)):
    """Valida el token del magic link y devuelve JWT."""
    row = db.query(MagicLinkTokenDB).filter_by(token=token).first()
    if not row:
        raise HTTPException(status_code=404, detail="Token inválido")
    if row.used_at:
        raise HTTPException(status_code=410, detail="Token ya usado")
    if row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="Token caducado")

    row.used_at = datetime.utcnow()

    user = db.query(UserDB).filter(UserDB.email == row.user_email).first()
    if not user:
        import secrets as _s
        from auth import hash_password
        user = UserDB(
            email=row.user_email,
            hashed_password=hash_password(_s.token_urlsafe(32)),
            empresa_id=0,
            nombre_empresa="desperdicio.es user",
            rol="user",
            is_active=True,
        )
        db.add(user)

    db.commit()
    db.refresh(user)

    jwt_token = create_access_token(
        data={"sub": user.email},
        expires_delta=timedelta(days=45),
    )
    return MagicLinkVerifyResponse(access_token=jwt_token, user_email=user.email)


@router.post("/auth/magic-link/cleanup")
def cleanup_expired_tokens(db: Session = Depends(get_db)):
    """Limpia tokens expirados (cron periodic)."""
    cutoff = datetime.utcnow() - timedelta(days=7)
    deleted = db.query(MagicLinkTokenDB).filter(
        MagicLinkTokenDB.expires_at < cutoff
    ).delete(synchronize_session=False)
    db.commit()
    return {"deleted": deleted}
