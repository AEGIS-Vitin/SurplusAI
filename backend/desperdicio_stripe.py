"""
Stripe Checkout + Webhook + Customer Portal para desperdicio.es.

Endpoints:
  POST /api/v1/checkout/create-session  → genera Stripe Checkout URL para un tier
  POST /api/v1/checkout/webhook         → procesa eventos Stripe (sub creada/cancelada/etc)
  POST /api/v1/portal/create            → URL Customer Portal (cliente gestiona suscripción)
  GET  /api/v1/subscription/me          → estado actual del cliente (tier + status)

Variables entorno:
  STRIPE_SECRET_KEY            → sk_test_... o sk_live_...
  STRIPE_WEBHOOK_SECRET        → whsec_... (lo da Stripe al crear webhook endpoint)
  STRIPE_PRICE_DESPERDICIO_SOLO  → price_xxx (€1.99/mes)
  STRIPE_PRICE_DESPERDICIO_PRO   → price_xxx (€9.99/mes)
  STRIPE_PRICE_DESPERDICIO_PLUS  → price_xxx (€19.99/mes)
  PUBLIC_BASE_URL              → https://desperdicio.es (para success/cancel URLs)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database import SessionLocal, CustomerSubscriptionDB, UserDB

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["desperdicio-stripe"])


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _stripe_module():
    """Lazy import — el módulo sigue cargando aunque stripe no esté instalado."""
    try:
        import stripe
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        return stripe
    except ImportError:
        raise HTTPException(status_code=500, detail="stripe package no instalado")


def _price_id_for_tier(tier: str) -> str:
    mapping = {
        "solo": os.getenv("STRIPE_PRICE_DESPERDICIO_SOLO", ""),
        "pro": os.getenv("STRIPE_PRICE_DESPERDICIO_PRO", ""),
        "plus": os.getenv("STRIPE_PRICE_DESPERDICIO_PLUS", ""),
    }
    return mapping.get(tier, "")


# ----------------------------------------------------------------------------
# Pydantic
# ----------------------------------------------------------------------------

class CreateCheckoutPayload(BaseModel):
    user_email: EmailStr
    tier: str  # solo | pro | plus


class CheckoutSessionResponse(BaseModel):
    checkout_url: str
    session_id: str


class PortalPayload(BaseModel):
    user_email: EmailStr


class SubscriptionStatusResponse(BaseModel):
    user_email: str
    tier: str
    status: str
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool


# ----------------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------------

@router.post("/checkout/create-session", response_model=CheckoutSessionResponse)
def create_checkout_session(payload: CreateCheckoutPayload, db: Session = Depends(get_db)):
    """Crea Stripe Checkout Session para suscripción mensual del tier indicado."""
    if not os.getenv("STRIPE_SECRET_KEY"):
        raise HTTPException(
            status_code=503,
            detail="Stripe no configurado en el servidor. Pide a soporte que active los planes."
        )

    price_id = _price_id_for_tier(payload.tier)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Tier '{payload.tier}' no reconocido o sin price_id en .env")

    base_url = os.getenv("PUBLIC_BASE_URL", "https://desperdicio.es")
    stripe = _stripe_module()

    # Lookup / crea customer en Stripe
    sub = db.query(CustomerSubscriptionDB).filter_by(user_email=payload.user_email).first()
    customer_id = sub.stripe_customer_id if sub else None
    if not customer_id:
        cust = stripe.Customer.create(
            email=payload.user_email,
            metadata={"product": "desperdicio.es", "tier_requested": payload.tier},
        )
        customer_id = cust.id

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{base_url}/?stripe_success=1&session={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/?stripe_cancel=1",
        allow_promotion_codes=True,
        billing_address_collection="auto",
        metadata={"user_email": payload.user_email, "tier": payload.tier},
        subscription_data={"metadata": {"user_email": payload.user_email, "tier": payload.tier}},
    )

    # Guardar o actualizar registro
    if sub:
        sub.stripe_customer_id = customer_id
        sub.updated_at = datetime.utcnow()
    else:
        sub = CustomerSubscriptionDB(
            user_email=payload.user_email,
            stripe_customer_id=customer_id,
            tier="free",
            status="inactive",
        )
        db.add(sub)
    db.commit()

    return CheckoutSessionResponse(checkout_url=session.url, session_id=session.id)


@router.post("/portal/create")
def create_portal_session(payload: PortalPayload, db: Session = Depends(get_db)):
    """URL Stripe Customer Portal — cliente cambia tier o cancela."""
    if not os.getenv("STRIPE_SECRET_KEY"):
        raise HTTPException(status_code=503, detail="Stripe no configurado")

    sub = db.query(CustomerSubscriptionDB).filter_by(user_email=payload.user_email).first()
    if not sub or not sub.stripe_customer_id:
        raise HTTPException(status_code=404, detail="No customer Stripe para este email")

    stripe = _stripe_module()
    base_url = os.getenv("PUBLIC_BASE_URL", "https://desperdicio.es")

    portal = stripe.billing_portal.Session.create(
        customer=sub.stripe_customer_id,
        return_url=f"{base_url}/dashboard.html",
    )
    return {"portal_url": portal.url}


@router.get("/subscription/me", response_model=SubscriptionStatusResponse)
def get_subscription_status(user_email: EmailStr, db: Session = Depends(get_db)):
    """Estado actual de la suscripción para un email."""
    sub = db.query(CustomerSubscriptionDB).filter_by(user_email=user_email).first()
    if not sub:
        return SubscriptionStatusResponse(
            user_email=user_email, tier="free", status="inactive",
            current_period_end=None, cancel_at_period_end=False,
        )
    return SubscriptionStatusResponse(
        user_email=sub.user_email,
        tier=sub.tier,
        status=sub.status,
        current_period_end=sub.current_period_end,
        cancel_at_period_end=sub.cancel_at_period_end,
    )


# ----------------------------------------------------------------------------
# Webhook Stripe
# ----------------------------------------------------------------------------

@router.post("/checkout/webhook")
async def stripe_webhook(request: Request, stripe_signature: Optional[str] = Header(None), db: Session = Depends(get_db)):
    """Recibe eventos Stripe (suscripción creada, payment ok, cancelación, etc).

    Verifica firma con STRIPE_WEBHOOK_SECRET para evitar inyecciones de eventos falsos.
    """
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        # Sin secret no podemos verificar — aceptamos pero logueamos warning
        log.warning("[stripe-webhook] STRIPE_WEBHOOK_SECRET vacío, no se verifica firma")

    body = await request.body()
    stripe = _stripe_module()

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(body, stripe_signature or "", webhook_secret)
        else:
            event = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Payload inválido")
    except Exception as e:
        # firma inválida etc
        raise HTTPException(status_code=400, detail=f"Webhook verification fail: {e}")

    event_type = event.get("type") if isinstance(event, dict) else event["type"]
    data_obj = (event.get("data", {}) if isinstance(event, dict) else event["data"]).get("object", {})

    # Manejo de eventos clave
    if event_type == "checkout.session.completed":
        _handle_checkout_completed(db, data_obj)
    elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
        _handle_subscription_change(db, data_obj)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(db, data_obj)
    elif event_type == "invoice.payment_failed":
        _handle_payment_failed(db, data_obj)
    else:
        log.info("[stripe-webhook] evento sin handler: %s", event_type)

    return {"received": True}


def _handle_checkout_completed(db: Session, session: dict):
    """Cliente terminó el checkout — vincula customer y crea subscription."""
    user_email = (session.get("metadata") or {}).get("user_email")
    tier = (session.get("metadata") or {}).get("tier", "solo")
    customer_id = session.get("customer")
    subscription_id = session.get("subscription")

    if not user_email:
        log.warning("[stripe-webhook] checkout.session.completed sin user_email en metadata")
        return

    sub = db.query(CustomerSubscriptionDB).filter_by(user_email=user_email).first()
    if not sub:
        sub = CustomerSubscriptionDB(user_email=user_email, tier=tier, status="active")
        db.add(sub)
    sub.stripe_customer_id = customer_id
    sub.stripe_subscription_id = subscription_id
    sub.tier = tier
    sub.status = "active"
    sub.updated_at = datetime.utcnow()
    db.commit()
    log.info("[stripe-webhook] %s suscrito a %s (subscription=%s)", user_email, tier, subscription_id)


def _handle_subscription_change(db: Session, sub_obj: dict):
    """Suscripción creada o actualizada — sync status."""
    sub_id = sub_obj.get("id")
    sub_db = db.query(CustomerSubscriptionDB).filter_by(stripe_subscription_id=sub_id).first()
    if not sub_db:
        # Buscar por customer_id si subscription_id no se ha guardado aún
        cust = sub_obj.get("customer")
        if cust:
            sub_db = db.query(CustomerSubscriptionDB).filter_by(stripe_customer_id=cust).first()
        if not sub_db:
            log.warning("[stripe-webhook] subscription %s sin registro local", sub_id)
            return

    sub_db.stripe_subscription_id = sub_id
    sub_db.status = sub_obj.get("status", "active")
    period_end = sub_obj.get("current_period_end")
    if period_end:
        sub_db.current_period_end = datetime.utcfromtimestamp(int(period_end))
    sub_db.cancel_at_period_end = bool(sub_obj.get("cancel_at_period_end", False))

    # Detectar tier desde metadata o price
    metadata = sub_obj.get("metadata") or {}
    if metadata.get("tier"):
        sub_db.tier = metadata["tier"]

    sub_db.updated_at = datetime.utcnow()
    db.commit()


def _handle_subscription_deleted(db: Session, sub_obj: dict):
    sub_id = sub_obj.get("id")
    sub_db = db.query(CustomerSubscriptionDB).filter_by(stripe_subscription_id=sub_id).first()
    if not sub_db:
        return
    sub_db.status = "canceled"
    sub_db.tier = "free"
    sub_db.updated_at = datetime.utcnow()
    db.commit()
    log.info("[stripe-webhook] %s canceló suscripción", sub_db.user_email)


def _handle_payment_failed(db: Session, invoice: dict):
    cust = invoice.get("customer")
    sub_db = db.query(CustomerSubscriptionDB).filter_by(stripe_customer_id=cust).first()
    if not sub_db:
        return
    sub_db.status = "past_due"
    sub_db.updated_at = datetime.utcnow()
    db.commit()
    log.warning("[stripe-webhook] %s pago fallido", sub_db.user_email)
