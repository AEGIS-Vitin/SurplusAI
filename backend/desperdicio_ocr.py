"""
OCR de facturas/tickets para pre-llenar inventario.

Endpoint /api/v1/inventory/bulk-from-photo:
  - Cliente sube foto factura proveedor (multipart)
  - Claude Vision extrae líneas: producto, cantidad, unidad, fecha caducidad estimada
  - Crea InventoryItem por cada línea
  - Solo accesible para tier Pro/Plus (gating)

Coste estimado: ~$0.015-0.030 por foto (Claude Sonnet vision).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal, InventoryItemDB, UserDB, CustomerSubscriptionDB

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["desperdicio-ocr"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----------------------------------------------------------------------------
# Tier gating
# ----------------------------------------------------------------------------

OCR_ALLOWED_TIERS = {"pro", "plus"}
OCR_MONTHLY_LIMITS = {"pro": 10, "plus": 50}


def check_ocr_allowed(user_email: str, db: Session) -> tuple[bool, str]:
    """Devuelve (allowed, reason)."""
    sub = db.query(CustomerSubscriptionDB).filter_by(user_email=user_email).first()
    tier = sub.tier if sub else "free"
    if tier not in OCR_ALLOWED_TIERS:
        return False, f"OCR solo disponible en tier Pro (€9.99/mes) o Plus (€19.99/mes). Tu tier actual: {tier}"
    return True, ""


# ----------------------------------------------------------------------------
# Claude Vision
# ----------------------------------------------------------------------------

CLAUDE_PROMPT = """Eres un asistente que lee facturas y tickets de proveedores de alimentación. Extrae cada línea de producto y devuelve un JSON estricto con esta estructura:

{
  "items": [
    {
      "nombre": "string descriptivo",
      "categoria": "frutas|verduras|lacteos|carnes|pescados|panaderia|preparados|otros",
      "cantidad": float,
      "unidad": "kg|unidades|litros",
      "fecha_caducidad_estimada_dias": int (días desde hoy hasta probable caducidad, según tipo producto)
    }
  ]
}

Reglas:
- IGNORA totales, IVA, comisiones, envíos. Solo líneas de producto real.
- IGNORA productos no alimentarios (servilletas, bolsas, limpieza).
- "fecha_caducidad_estimada_dias" según tipo:
  * Lácteos frescos: 7-14
  * Carnes/pescados frescos: 2-5
  * Frutas/verduras frescas: 5-10
  * Pan: 1-3
  * Preparados: 3-7
  * Conservas/no perecedero: 365
- Si no detectas nada, devuelve {"items": []}.

DEVUELVE SOLO EL JSON, sin texto adicional."""


def call_claude_vision(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """Llama a Claude Sonnet con la imagen. Devuelve dict parseado."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY no configurada en servidor")

    try:
        import anthropic
    except ImportError:
        raise HTTPException(status_code=500, detail="anthropic SDK no instalado")

    client = anthropic.Anthropic(api_key=api_key)
    img_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_b64}},
                {"type": "text", "text": CLAUDE_PROMPT},
            ],
        }],
    )
    raw = msg.content[0].text.strip()

    # Extraer primer JSON object encontrado
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise HTTPException(status_code=502, detail=f"OCR no devolvió JSON: {raw[:200]}")
    try:
        return json.loads(match.group())
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"OCR JSON inválido: {e}")


# ----------------------------------------------------------------------------
# Pydantic
# ----------------------------------------------------------------------------

class OCRItemPreview(BaseModel):
    nombre: str
    categoria: Optional[str]
    cantidad: float
    unidad: str
    fecha_caducidad_estimada_dias: int


class BulkOCRResponse(BaseModel):
    items_detected: int
    items_inserted: int
    preview: List[OCRItemPreview]
    error: Optional[str] = None


# ----------------------------------------------------------------------------
# Endpoint
# ----------------------------------------------------------------------------

@router.post("/inventory/bulk-from-photo", response_model=BulkOCRResponse)
async def bulk_from_photo(
    user_email: str = Form(...),
    proveedor: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Recibe foto de factura → Claude Vision extrae líneas → crea inventory items.

    Requisitos:
    - tier Pro o Plus
    - imagen jpeg/png/webp <5MB
    """
    allowed, reason = check_ocr_allowed(user_email, db)
    if not allowed:
        raise HTTPException(status_code=403, detail=reason)

    # Validar imagen
    ct = (file.content_type or "").lower()
    valid = {"image/jpeg": "image/jpeg", "image/jpg": "image/jpeg", "image/png": "image/png", "image/webp": "image/webp"}
    if ct not in valid:
        raise HTTPException(status_code=400, detail=f"Formato no soportado: {ct}. Usa JPEG/PNG/WEBP.")
    media_type = valid[ct]

    body = await file.read()
    if len(body) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Imagen >5MB. Reduce calidad o tamaño.")
    if len(body) < 1000:
        raise HTTPException(status_code=400, detail="Imagen demasiado pequeña, no parece una factura.")

    # Llamar a Claude Vision
    try:
        ocr_result = call_claude_vision(body, media_type=media_type)
    except HTTPException:
        raise
    except Exception as e:
        log.error("OCR call failed: %s", e)
        raise HTTPException(status_code=502, detail=f"OCR vision falló: {e}")

    items_raw = ocr_result.get("items", [])
    preview = []
    inserted = 0

    user = db.query(UserDB).filter(UserDB.email == user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no existe; haz login primero")

    today = datetime.utcnow()
    for it in items_raw:
        try:
            nombre = (it.get("nombre") or "").strip()
            if not nombre:
                continue
            cantidad = float(it.get("cantidad", 0))
            if cantidad <= 0:
                continue
            unidad = it.get("unidad") or "kg"
            categoria = it.get("categoria")
            days = int(it.get("fecha_caducidad_estimada_dias", 7))
            fecha_caducidad = today + timedelta(days=max(1, min(days, 365)))

            # Persistir item
            row = InventoryItemDB(
                user_id=user.id,
                nombre=nombre[:255],
                categoria=categoria[:64] if categoria else None,
                cantidad=cantidad,
                unidad=unidad[:32],
                fecha_compra=today,
                fecha_caducidad=fecha_caducidad,
                proveedor=proveedor[:255] if proveedor else None,
                source="factulens_ocr",
                status="vigente",
            )
            db.add(row)
            inserted += 1

            preview.append(OCRItemPreview(
                nombre=nombre,
                categoria=categoria,
                cantidad=cantidad,
                unidad=unidad,
                fecha_caducidad_estimada_dias=days,
            ))
        except Exception as e:
            log.warning("OCR line skipped: %s — %s", e, it)
            continue

    db.commit()

    return BulkOCRResponse(
        items_detected=len(items_raw),
        items_inserted=inserted,
        preview=preview,
    )


@router.get("/inventory/ocr/quota")
def ocr_quota(user_email: str, db: Session = Depends(get_db)):
    """Devuelve la cuota OCR mensual del cliente según su tier."""
    sub = db.query(CustomerSubscriptionDB).filter_by(user_email=user_email).first()
    tier = sub.tier if sub else "free"
    monthly_limit = OCR_MONTHLY_LIMITS.get(tier, 0)

    user = db.query(UserDB).filter(UserDB.email == user_email).first()
    used = 0
    if user:
        cutoff = datetime.utcnow() - timedelta(days=30)
        used = db.query(InventoryItemDB).filter(
            InventoryItemDB.user_id == user.id,
            InventoryItemDB.source == "factulens_ocr",
            InventoryItemDB.created_at >= cutoff,
        ).count()

    return {
        "tier": tier,
        "monthly_limit": monthly_limit,
        "used_last_30d": used,
        "remaining": max(0, monthly_limit - used),
    }
