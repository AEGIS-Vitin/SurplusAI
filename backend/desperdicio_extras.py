"""
Sprints 19-22: extras desperdicio.es

- Sprint 19: bulk import inventario CSV
- Sprint 20: webhooks externos (cliente puede enchufar Slack/Discord/Zapier)
- Sprint 22: receta IA (Claude sugiere qué cocinar con sobrante)
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
from datetime import datetime, timedelta
from typing import List, Optional

import requests
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File
from pydantic import BaseModel, EmailStr, Field, HttpUrl
from sqlalchemy.orm import Session

from database import (
    SessionLocal, InventoryItemDB, UserDB, NotificationChannelDB,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["desperdicio-extras"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# Sprint 19: Bulk import inventario CSV
# ============================================================================

class BulkInventoryResponse(BaseModel):
    rows_processed: int
    items_created: int
    errors: list


@router.post("/inventory/bulk-csv", response_model=BulkInventoryResponse)
async def bulk_import_inventory(
    user_email: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Importa muchos productos al inventario desde CSV.

    Formato CSV (header obligatorio):
      nombre,categoria,cantidad,unidad,fecha_compra,fecha_caducidad,proveedor,lote,precio_unitario

    Solo nombre, cantidad y fecha_caducidad son obligatorios.
    Fechas en YYYY-MM-DD.
    """
    user = db.query(UserDB).filter(UserDB.email == user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no existe")

    body = await file.read()
    if len(body) > 1 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV >1MB; trocéalo")

    text = body.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    rows = 0
    created = 0
    errors = []

    for i, row in enumerate(reader, start=2):
        rows += 1
        try:
            nombre = (row.get("nombre") or "").strip()
            if not nombre:
                errors.append({"row": i, "error": "nombre vacío"})
                continue
            cantidad = float(row.get("cantidad") or 0)
            if cantidad <= 0:
                errors.append({"row": i, "error": "cantidad <=0"})
                continue
            fecha_cad_str = (row.get("fecha_caducidad") or "").strip()
            try:
                fecha_caducidad = datetime.strptime(fecha_cad_str, "%Y-%m-%d")
            except ValueError:
                fecha_caducidad = datetime.fromisoformat(fecha_cad_str)

            fecha_compra = None
            if row.get("fecha_compra"):
                try:
                    fecha_compra = datetime.strptime(row["fecha_compra"], "%Y-%m-%d")
                except Exception:
                    pass

            precio = None
            if row.get("precio_unitario"):
                try:
                    precio = float(row["precio_unitario"])
                except Exception:
                    pass

            item = InventoryItemDB(
                user_id=user.id,
                nombre=nombre[:255],
                categoria=(row.get("categoria") or None),
                cantidad=cantidad,
                unidad=(row.get("unidad") or "kg")[:32],
                fecha_compra=fecha_compra,
                fecha_caducidad=fecha_caducidad,
                proveedor=(row.get("proveedor") or None),
                lote=(row.get("lote") or None),
                precio_unitario=precio,
                source="csv_import",
                status="vigente",
            )
            db.add(item)
            created += 1
        except Exception as e:
            errors.append({"row": i, "error": str(e)[:200]})

    db.commit()
    return BulkInventoryResponse(rows_processed=rows, items_created=created, errors=errors[:20])


# ============================================================================
# Sprint 20: Webhooks externos cliente (Slack / Discord / Zapier / Make)
# ============================================================================

class WebhookCreatePayload(BaseModel):
    user_email: EmailStr
    name: str = Field(..., max_length=100, description="ej. 'Slack ventas' o 'Zapier zap-1'")
    url: HttpUrl = Field(..., description="URL del webhook (Slack incoming hook, Zapier hook, etc.)")
    events: List[str] = Field(default_factory=lambda: ["certificate.created"], description="Eventos a notificar")


@router.post("/webhooks/external", status_code=201)
def create_external_webhook(payload: WebhookCreatePayload, db: Session = Depends(get_db)):
    """Cliente registra un webhook externo (Slack/Discord/Zapier/Make)
    que recibe POST con cada evento del que se suscribe.

    Reusamos NotificationChannelDB con channel_type='webhook'.

    Eventos soportados:
      - certificate.created
      - inventory.expiring (cuando un item entra en ventana de caducidad)
      - subscription.changed
    """
    valid_events = {"certificate.created", "inventory.expiring", "subscription.changed"}
    bad = [e for e in payload.events if e not in valid_events]
    if bad:
        raise HTTPException(status_code=400, detail=f"Eventos no soportados: {bad}. Válidos: {valid_events}")

    user = db.query(UserDB).filter(UserDB.email == payload.user_email).first()
    user_id = user.id if user else None

    row = NotificationChannelDB(
        user_id=user_id,
        user_email=payload.user_email,
        channel_type="webhook",
        payload={"name": payload.name, "url": str(payload.url), "events": payload.events},
        enabled=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": payload.name, "events": payload.events, "url": str(payload.url)}


@router.get("/webhooks/external")
def list_external_webhooks(user_email: EmailStr, db: Session = Depends(get_db)):
    rows = db.query(NotificationChannelDB).filter(
        NotificationChannelDB.user_email == user_email,
        NotificationChannelDB.channel_type == "webhook",
    ).all()
    return [
        {
            "id": r.id,
            "name": (r.payload or {}).get("name"),
            "url": (r.payload or {}).get("url"),
            "events": (r.payload or {}).get("events", []),
            "enabled": r.enabled,
            "last_used_at": r.last_used_at.isoformat() + "Z" if r.last_used_at else None,
        }
        for r in rows
    ]


def fire_webhooks(db: Session, user_email: str, event: str, payload: dict) -> int:
    """Helper para disparar webhooks externos del cliente.

    Devuelve cuántos webhooks han recibido el evento exitosamente.
    """
    hooks = db.query(NotificationChannelDB).filter(
        NotificationChannelDB.user_email == user_email,
        NotificationChannelDB.channel_type == "webhook",
        NotificationChannelDB.enabled == True,  # noqa: E712
    ).all()

    sent = 0
    for h in hooks:
        cfg = h.payload or {}
        if event not in (cfg.get("events") or []):
            continue
        url = cfg.get("url")
        if not url:
            continue
        try:
            resp = requests.post(url, json={"event": event, "data": payload}, timeout=5)
            if resp.status_code < 400:
                sent += 1
                h.last_used_at = datetime.utcnow()
        except Exception as e:
            log.warning("[fire_webhooks] %s fail: %s", url, e)

    if sent:
        db.commit()
    return sent


# ============================================================================
# Sprint 22: Receta IA con sobrante (Claude)
# ============================================================================

class RecetaRequest(BaseModel):
    user_email: EmailStr
    items: List[str] = Field(..., min_items=1, max_items=10, description="Lista descriptiva: '3kg pan duro', '2kg manzanas', etc")
    contexto: Optional[str] = Field(None, max_length=300, description="ej. 'restaurante mediterráneo', 'cocina familiar'")


class RecetaResponse(BaseModel):
    receta_titulo: str
    descripcion_corta: str
    pasos: List[str]
    ingredientes_extra_necesarios: List[str]
    aprovechamiento_porcentaje: int


@router.post("/receta/sugerir", response_model=RecetaResponse)
def sugerir_receta(payload: RecetaRequest):
    """Claude sugiere una receta para aprovechar el sobrante."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="Anthropic no configurado")

    try:
        import anthropic
    except ImportError:
        raise HTTPException(status_code=500, detail="anthropic SDK no instalado")

    client = anthropic.Anthropic(api_key=api_key)
    items_str = "\n".join(f"- {it}" for it in payload.items)
    contexto = payload.contexto or "cocina casera"

    prompt = f"""Eres un chef que ayuda a no tirar comida. Te paso una lista de productos sobrantes:

{items_str}

Contexto: {contexto}

Sugiere UNA receta concreta que aproveche al máximo estos ingredientes. Devuelve EXCLUSIVAMENTE JSON con esta estructura:

{{
  "receta_titulo": "Nombre breve y atractivo",
  "descripcion_corta": "1 frase sobre el plato",
  "pasos": ["paso 1", "paso 2", ..., "paso N"],
  "ingredientes_extra_necesarios": ["lista de ingredientes que NO están en el sobrante pero son imprescindibles"],
  "aprovechamiento_porcentaje": 70
}}

Reglas:
- 4 a 8 pasos
- Realista, ejecutable en cocina pequeña
- Aprovechamiento_porcentaje = % del sobrante usado (0-100)
- DEVUELVE SOLO EL JSON
"""

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()

    import json as _json
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise HTTPException(status_code=502, detail=f"IA no devolvió JSON: {raw[:200]}")
    try:
        data = _json.loads(match.group())
    except _json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"JSON inválido: {e}")

    return RecetaResponse(**data)


# ============================================================================
# Sprint 21 helper: i18n strings
# ============================================================================

I18N_STRINGS = {
    "es": {
        "hero_title": "Certifica que NO tiras comida.",
        "hero_subtitle": "En 60 segundos.",
        "cta_primary": "Generar mi 1er certificado gratis",
        "cta_secondary": "Ver cómo funciona",
        "tier_solo_label": "Solo",
        "tier_pro_label": "Pro",
        "tier_plus_label": "Plus",
    },
    "ca": {
        "hero_title": "Certifica que NO llences menjar.",
        "hero_subtitle": "En 60 segons.",
        "cta_primary": "Generar el meu primer certificat gratis",
        "cta_secondary": "Veure com funciona",
        "tier_solo_label": "Solo",
        "tier_pro_label": "Pro",
        "tier_plus_label": "Plus",
    },
    "en": {
        "hero_title": "Prove you DON'T waste food.",
        "hero_subtitle": "In 60 seconds.",
        "cta_primary": "Get my first free certificate",
        "cta_secondary": "See how it works",
        "tier_solo_label": "Solo",
        "tier_pro_label": "Pro",
        "tier_plus_label": "Plus",
    },
}


@router.get("/i18n/{lang}")
def get_i18n_strings(lang: str):
    """Devuelve los strings traducibles para un idioma."""
    if lang not in I18N_STRINGS:
        raise HTTPException(status_code=404, detail=f"Idioma '{lang}' no soportado. Disponibles: {list(I18N_STRINGS.keys())}")
    return {"lang": lang, "strings": I18N_STRINGS[lang]}
