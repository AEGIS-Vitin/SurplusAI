"""
Contact handler — entry point unificado para mensajes inbound desde cualquier canal
(WhatsApp Cloud API, Twilio SMS/WA, formulario web, email inbound).

Endpoints:
  POST /api/v1/contact/inbound              → JSON genérico: {from, channel, text}
  POST /api/v1/contact/webhook/twilio       → Twilio form-encoded (SMS / WA Business)
  GET  /api/v1/contact/webhook/whatsapp     → Meta WA Cloud verify challenge
  POST /api/v1/contact/webhook/whatsapp     → Meta WA Cloud message events
  POST /api/v1/contact/form                 → contacto desde formulario web (open)
  POST /api/v1/contact/outbound/send        → admin envía mensaje saliente
  GET  /api/v1/contact/messages             → admin lista últimos mensajes

Cada inbound:
  1. Persiste en `contact_messages`
  2. Detecta intent simple (saludo, info, pricing, soporte, urgente, otro)
  3. Auto-responde con plantilla en el mismo canal cuando hay credenciales
  4. Notifica a Telegram (chat de Victor) con copia + intent + canal

Si no hay credenciales para responder en el canal (WA Cloud no activo, Twilio
sin alta), persiste y notifica solo a Telegram. Cero pérdida de mensajes.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Optional
from urllib import request as urlrequest, parse as urlparse

from fastapi import APIRouter, Depends, HTTPException, Header, Request, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database import SessionLocal, ContactMessageDB

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/contact", tags=["contact-multichannel"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


TRESAAA_PHONE = os.getenv("TRESAAA_PHONE", "+34650767401")
ADMIN_TOKEN = os.getenv("ADMIN_API_TOKEN", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

WA_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WA_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
WA_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "aegis_wa_2026")

TW_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TW_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TW_FROM = os.getenv("TWILIO_FROM_NUMBER", "")


def require_admin(authorization: Optional[str] = Header(None)):
    if not ADMIN_TOKEN:
        raise HTTPException(503, "ADMIN_API_TOKEN no configurado")
    if not authorization:
        raise HTTPException(401, "Auth requerida")
    parts = authorization.split()
    if len(parts) == 2 and parts[1] == ADMIN_TOKEN:
        return True
    if authorization == ADMIN_TOKEN:
        return True
    raise HTTPException(403, "Token admin inválido")


INTENT_PATTERNS = [
    ("urgente", re.compile(r"\b(urgente|emergencia|inspecci[oó]n)\b", re.I)),
    ("pricing", re.compile(r"\b(precio|cu[aá]nto cuesta|tarifa|plan|coste|cobr|suscrip)\b", re.I)),
    ("soporte", re.compile(r"\b(no funciona|error|fallo|bug|problema|ayuda|olvid)\b", re.I)),
    ("demo", re.compile(r"\b(demo|prueba|trial|gratis|primer certificado)\b", re.I)),
    ("info", re.compile(r"\b(info|qu[eé] es|quien sois|c[oó]mo funciona|verifactu|desperdicio)\b", re.I)),
    ("saludo", re.compile(r"\b(hola|hey|buenos|buenas|saludos)\b", re.I)),
]


def detect_intent(text: str) -> str:
    if not text:
        return "vacio"
    for label, pattern in INTENT_PATTERNS:
        if pattern.search(text):
            return label
    return "otro"


REPLY_TEMPLATES = {
    "saludo": (
        "Hola 👋 Soy el asistente de TRESAAA. ¿Necesitas info sobre desperdicio.es "
        "(certificados Ley 1/2025 + inventario) o factulens (facturación Verifactu)? "
        "Cuéntame y te derivo al equipo correcto."
    ),
    "pricing": (
        "Tenemos planes desde 1,99 €/mes (Solo, 5 certificados/mes), 9,99 €/mes "
        "(Pro, ilimitados + OCR factura) y 19,99 €/mes (Plus, multi-usuario + bulk CSV). "
        "Detalles en https://desperdicio.es/#precios. ¿Quieres demo?"
    ),
    "demo": (
        "El primer certificado es gratis sin tarjeta: https://desperdicio.es "
        "→ generas tu PDF firmado SHA-256 con QR en menos de 30 segundos."
    ),
    "info": (
        "TRESAAA da cumplimiento legal a empresas con dos productos: \n"
        "• desperdicio.es — Ley 1/2025 (certificados PDF + inventario + alertas caducidad).\n"
        "• factulens (próximamente) — Verifactu 2027 + facturación + fichaje.\n"
        "Web: https://desperdicio.es · Email: info@tresaaa.com"
    ),
    "soporte": (
        "Recibimos tu incidencia. Un humano de soporte te contesta en menos de 4 horas "
        "(L-V 09-19 CET). Si es urgente escribe 'URGENTE' al inicio."
    ),
    "urgente": (
        "✅ Marcado como URGENTE. Vas a recibir respuesta directa del fundador en menos de 1 hora "
        "en horario laboral (escalado vía Telegram). Si es fuera de horas, escribimos a primera hora."
    ),
    "otro": (
        "Gracias por tu mensaje. Lo hemos registrado y te respondemos en menos de 24 h. "
        "Si necesitas algo urgente, llama al " + TRESAAA_PHONE + " (L-V 09-19 CET)."
    ),
    "vacio": "Mensaje recibido sin contenido. ¿Puedes repetir?",
}


def _http_post_json(url: str, payload: dict, headers: Optional[dict] = None, timeout: int = 8):
    data = json.dumps(payload).encode()
    req = urlrequest.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")[:500]
    except Exception as e:
        return 0, f"err:{e}"


def _http_post_form(url: str, data: dict, auth: Optional[tuple] = None, timeout: int = 8):
    body = urlparse.urlencode(data).encode()
    req = urlrequest.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if auth:
        import base64
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")[:500]
    except Exception as e:
        return 0, f"err:{e}"


def telegram_notify(text: str) -> bool:
    if not TG_TOKEN or not TG_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    code, _ = _http_post_form(url, {
        "chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    })
    return 200 <= code < 300


def send_whatsapp_cloud(to_phone: str, text: str) -> bool:
    if not (WA_TOKEN and WA_PHONE_ID):
        return False
    url = f"https://graph.facebook.com/v20.0/{WA_PHONE_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone.lstrip("+"),
        "type": "text",
        "text": {"body": text[:4000]},
    }
    code, _ = _http_post_json(url, payload, headers={"Authorization": f"Bearer {WA_TOKEN}"})
    return 200 <= code < 300


def send_twilio(to_phone: str, text: str, channel: str = "sms") -> bool:
    if not (TW_SID and TW_TOKEN and TW_FROM):
        return False
    from_addr = TW_FROM if channel == "sms" else f"whatsapp:{TW_FROM.lstrip('whatsapp:')}"
    to_addr = to_phone if channel == "sms" else f"whatsapp:{to_phone}"
    url = f"https://api.twilio.com/2010-04-01/Accounts/{TW_SID}/Messages.json"
    code, _ = _http_post_form(url, {
        "From": from_addr, "To": to_addr, "Body": text[:1500],
    }, auth=(TW_SID, TW_TOKEN))
    return 200 <= code < 300


def auto_reply(channel: str, to_phone: str, intent: str) -> bool:
    text = REPLY_TEMPLATES.get(intent, REPLY_TEMPLATES["otro"])
    if channel in ("whatsapp", "whatsapp_cloud", "wa"):
        return send_whatsapp_cloud(to_phone, text)
    if channel == "twilio_wa":
        return send_twilio(to_phone, text, channel="whatsapp")
    if channel in ("sms", "twilio_sms"):
        return send_twilio(to_phone, text, channel="sms")
    return False


def persist_and_notify(db: Session, *, from_addr: str, channel: str, text: str, raw: Optional[dict] = None):
    intent = detect_intent(text)
    msg = ContactMessageDB(
        from_addr=from_addr or "unknown",
        channel=channel,
        text=text or "",
        intent=intent,
        raw_payload=json.dumps(raw)[:8000] if raw else None,
        created_at=datetime.utcnow(),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    response_sent = auto_reply(channel, from_addr, intent)
    msg.response_sent = response_sent
    db.commit()
    tg_text = (
        f"📨 <b>Inbound · {channel}</b>\n"
        f"<b>From:</b> <code>{from_addr}</code>\n"
        f"<b>Intent:</b> {intent}\n"
        f"<b>Auto-reply:</b> {'✅' if response_sent else '⚠️ no enviada (canal sin credenciales)'}\n"
        f"<b>Texto:</b>\n{text[:600]}"
    )
    telegram_notify(tg_text)
    return msg


class InboundRequest(BaseModel):
    from_addr: str
    channel: str
    text: str
    raw: Optional[dict] = None


@router.post("/inbound")
async def inbound_generic(req: InboundRequest, db: Session = Depends(get_db)):
    msg = persist_and_notify(db, from_addr=req.from_addr, channel=req.channel, text=req.text, raw=req.raw)
    return {
        "received": True,
        "message_id": msg.id,
        "intent": msg.intent,
        "auto_replied": bool(msg.response_sent),
    }


@router.post("/webhook/twilio")
async def webhook_twilio(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    payload = {k: form.get(k) for k in form.keys()}
    from_addr = payload.get("From", "")
    body = payload.get("Body", "")
    is_wa = from_addr.startswith("whatsapp:")
    channel = "twilio_wa" if is_wa else "twilio_sms"
    from_clean = from_addr.replace("whatsapp:", "")
    persist_and_notify(db, from_addr=from_clean, channel=channel, text=body, raw=payload)
    return PlainTextResponse(
        '<?xml version="1.0" encoding="UTF-8"?><Response/>',
        media_type="application/xml",
    )


@router.get("/webhook/whatsapp")
async def webhook_whatsapp_verify(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    hub_challenge: str = Query("", alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == WA_VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(403, "verify token invalid")


@router.post("/webhook/whatsapp")
async def webhook_whatsapp_message(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    from_phone = "+" + msg.get("from", "")
                    text = (msg.get("text", {}) or {}).get("body", "")
                    persist_and_notify(db, from_addr=from_phone, channel="whatsapp_cloud", text=text, raw=msg)
    except Exception as e:
        log.error("WA webhook parse failed: %s", e)
    return {"ok": True}


class ContactFormRequest(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    company: Optional[str] = None
    message: str


@router.post("/form")
async def contact_form(req: ContactFormRequest, db: Session = Depends(get_db)):
    composed = f"[Form web] {req.name}"
    if req.company:
        composed += f" ({req.company})"
    if req.phone:
        composed += f" · tel {req.phone}"
    composed += f"\n{req.message}"
    persist_and_notify(db, from_addr=req.email, channel="webform", text=composed, raw=req.dict())
    return {"received": True, "msg": "Mensaje registrado, te respondemos en menos de 24 h."}


class OutboundRequest(BaseModel):
    to_phone: str
    text: str
    channel: str = "whatsapp"


@router.post("/outbound/send", dependencies=[Depends(require_admin)])
async def outbound_send(req: OutboundRequest, db: Session = Depends(get_db)):
    if req.channel == "whatsapp":
        ok = send_whatsapp_cloud(req.to_phone, req.text)
    elif req.channel == "twilio_wa":
        ok = send_twilio(req.to_phone, req.text, channel="whatsapp")
    elif req.channel == "twilio_sms":
        ok = send_twilio(req.to_phone, req.text, channel="sms")
    else:
        raise HTTPException(400, "channel inválido")
    db.add(ContactMessageDB(
        from_addr="system",
        channel=f"OUT_{req.channel}",
        text=req.text,
        intent="outbound",
        response_sent=ok,
        raw_payload=json.dumps({"to": req.to_phone}),
        created_at=datetime.utcnow(),
    ))
    db.commit()
    if not ok:
        raise HTTPException(503, f"Canal {req.channel} sin credenciales o falló")
    return {"sent": True, "to": req.to_phone, "channel": req.channel}


@router.get("/messages", dependencies=[Depends(require_admin)])
async def list_messages(
    limit: int = Query(50, ge=1, le=500),
    channel: Optional[str] = None,
    intent: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(ContactMessageDB)
    if channel:
        q = q.filter(ContactMessageDB.channel == channel)
    if intent:
        q = q.filter(ContactMessageDB.intent == intent)
    rows = q.order_by(ContactMessageDB.id.desc()).limit(limit).all()
    return {
        "count": len(rows),
        "messages": [
            {
                "id": r.id,
                "from": r.from_addr,
                "channel": r.channel,
                "intent": r.intent,
                "text": r.text[:300],
                "auto_replied": bool(r.response_sent),
                "ts": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/health")
async def contact_health():
    return {
        "phone_oficial": TRESAAA_PHONE,
        "telegram": bool(TG_TOKEN and TG_CHAT_ID),
        "whatsapp_cloud": bool(WA_TOKEN and WA_PHONE_ID),
        "twilio": bool(TW_SID and TW_TOKEN and TW_FROM),
        "intents_supported": list(REPLY_TEMPLATES.keys()),
    }
