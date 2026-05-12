"""
Sprints 26-28: growth & monetization endpoints

- Sprint 26: A/B testing variants + tracking persistido
- Sprint 27: Affiliate program (registro + dashboard + tracking)
- Sprint 28: Email drip campaigns (welcome + activation + churn rescue)
"""
from __future__ import annotations

import logging
import os
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from database import (
    SessionLocal, AffiliateDB, AffiliateReferralDB, EmailCampaignLogDB,
    ABEventDB, CustomerSubscriptionDB, UserDB, PdfCertificateDB,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["desperdicio-growth"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# Sprint 26 — A/B testing
# ============================================================================

class ABEventPayload(BaseModel):
    variant: str = Field(..., max_length=32)
    event: str = Field(..., max_length=64)
    user_email: Optional[EmailStr] = None
    extra: Optional[dict] = None


@router.post("/ab/event", status_code=201)
def ab_event(payload: ABEventPayload, db: Session = Depends(get_db)):
    """Persiste evento A/B (impression / cta_click / signup / conversion).

    Mejora del Sprint 16: ahora persiste en DB para análisis cohort real.
    """
    row = ABEventDB(
        variant=payload.variant,
        event=payload.event,
        user_email=payload.user_email,
        extra=payload.extra,
    )
    db.add(row)
    db.commit()
    return {"tracked": True, "id": row.id}


@router.get("/ab/results/{variant}")
def ab_results(variant: str, db: Session = Depends(get_db)):
    """Métricas por variante: impressions, clicks, signups, conversion rate."""
    base = db.query(ABEventDB).filter(ABEventDB.variant == variant)
    impressions = base.filter(ABEventDB.event == "impression").count()
    clicks = base.filter(ABEventDB.event == "cta_click").count()
    signups = base.filter(ABEventDB.event == "signup").count()
    conversions = base.filter(ABEventDB.event == "conversion").count()

    ctr = (clicks / impressions * 100) if impressions else 0
    signup_rate = (signups / clicks * 100) if clicks else 0
    conv_rate = (conversions / signups * 100) if signups else 0

    return {
        "variant": variant,
        "impressions": impressions,
        "clicks": clicks,
        "signups": signups,
        "conversions": conversions,
        "ctr_pct": round(ctr, 2),
        "click_to_signup_pct": round(signup_rate, 2),
        "signup_to_conversion_pct": round(conv_rate, 2),
    }


# ============================================================================
# Sprint 27 — Affiliate program
# ============================================================================

def _generate_affiliate_code() -> str:
    """Código corto memorable: 6 chars alfanuméricos uppercase."""
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(6))


class AffiliateRegisterPayload(BaseModel):
    user_email: EmailStr
    nombre: str = Field(..., min_length=2, max_length=255)
    organizacion: Optional[str] = Field(None, max_length=255)
    payout_iban: Optional[str] = Field(None, max_length=64)


class AffiliateResponse(BaseModel):
    code: str
    nombre: str
    organizacion: Optional[str]
    commission_pct: float
    total_referrals: int
    total_paid_eur: float
    referral_link: str
    is_active: bool


@router.post("/affiliate/register", response_model=AffiliateResponse, status_code=201)
def register_affiliate(payload: AffiliateRegisterPayload, db: Session = Depends(get_db)):
    """Registra a un nuevo afiliado y le entrega su código de referencia único."""
    existing = db.query(AffiliateDB).filter_by(user_email=payload.user_email).first()
    if existing:
        base_url = os.getenv("PUBLIC_BASE_URL", "https://desperdicio.es")
        return AffiliateResponse(
            code=existing.code, nombre=existing.nombre, organizacion=existing.organizacion,
            commission_pct=existing.commission_pct, total_referrals=existing.total_referrals,
            total_paid_eur=existing.total_paid_eur,
            referral_link=f"{base_url}/?ref={existing.code}",
            is_active=existing.is_active,
        )

    # Generar código único (reintenta si colisión)
    for _ in range(10):
        code = _generate_affiliate_code()
        if not db.query(AffiliateDB).filter_by(code=code).first():
            break
    else:
        raise HTTPException(status_code=500, detail="No se pudo generar código único")

    row = AffiliateDB(
        code=code,
        user_email=payload.user_email,
        nombre=payload.nombre,
        organizacion=payload.organizacion,
        payout_iban=payload.payout_iban,
        commission_pct=20.0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    base_url = os.getenv("PUBLIC_BASE_URL", "https://desperdicio.es")
    return AffiliateResponse(
        code=row.code, nombre=row.nombre, organizacion=row.organizacion,
        commission_pct=row.commission_pct, total_referrals=row.total_referrals,
        total_paid_eur=row.total_paid_eur,
        referral_link=f"{base_url}/?ref={row.code}",
        is_active=row.is_active,
    )


@router.get("/affiliate/me", response_model=AffiliateResponse)
def get_my_affiliate(user_email: EmailStr, db: Session = Depends(get_db)):
    """Estado actual de un afiliado (referrals + comisión acumulada)."""
    row = db.query(AffiliateDB).filter_by(user_email=user_email).first()
    if not row:
        raise HTTPException(status_code=404, detail="No eres afiliado todavía")

    # Recalcular en vivo
    refs = db.query(AffiliateReferralDB).filter_by(affiliate_id=row.id).all()
    total_paid = sum(r.commission_eur_to_date for r in refs)

    base_url = os.getenv("PUBLIC_BASE_URL", "https://desperdicio.es")
    return AffiliateResponse(
        code=row.code, nombre=row.nombre, organizacion=row.organizacion,
        commission_pct=row.commission_pct, total_referrals=len(refs),
        total_paid_eur=round(total_paid, 2),
        referral_link=f"{base_url}/?ref={row.code}",
        is_active=row.is_active,
    )


@router.post("/affiliate/track-signup")
def track_affiliate_signup(
    ref_code: str = Query(..., description="Código del afiliado"),
    user_email: EmailStr = Query(...),
    tier: Optional[str] = Query("free"),
    db: Session = Depends(get_db),
):
    """Cliente firmó usando ?ref=CODE. Asignar al afiliado.

    Se llama desde el frontend al detectar el param ref en la URL al hacer signup.
    """
    aff = db.query(AffiliateDB).filter_by(code=ref_code, is_active=True).first()
    if not aff:
        return {"tracked": False, "reason": "código inválido"}

    existing = db.query(AffiliateReferralDB).filter_by(user_email=user_email).first()
    if existing:
        return {"tracked": False, "reason": "user ya asignado a un afiliado"}

    ref = AffiliateReferralDB(
        affiliate_id=aff.id,
        user_email=user_email,
        tier_at_signup=tier,
    )
    db.add(ref)
    aff.total_referrals = (aff.total_referrals or 0) + 1
    db.commit()
    return {"tracked": True, "affiliate_code": ref_code, "user_email": user_email}


@router.post("/affiliate/recalc-commissions")
def recalculate_commissions(db: Session = Depends(get_db)):
    """Cron mensual: recalcula comisiones acumuladas por afiliado."""
    refs = db.query(AffiliateReferralDB).all()
    tier_prices = {"solo": 1.99, "pro": 9.99, "plus": 19.99, "free": 0}

    updated = 0
    for ref in refs:
        sub = db.query(CustomerSubscriptionDB).filter_by(user_email=ref.user_email).first()
        if not sub or sub.status != "active":
            continue
        # Asumimos 1 mes desde signup hasta hoy (simplificación)
        months = max(1, (datetime.utcnow() - ref.created_at).days // 30)
        monthly = tier_prices.get(sub.tier, 0)
        affiliate = db.query(AffiliateDB).filter_by(id=ref.affiliate_id).first()
        commission_total = monthly * months * (affiliate.commission_pct / 100) if affiliate else 0
        ref.commission_eur_to_date = round(commission_total, 2)
        updated += 1

    db.commit()
    return {"refs_updated": updated}


# ============================================================================
# Sprint 28 — Email drip campaigns
# ============================================================================

DRIP_CAMPAIGNS = {
    "welcome": {
        "delay_days": 0,
        "subject": "Bienvenido a desperdicio.es 👋",
        "body": (
            "Hola,\n\nGracias por probar desperdicio.es. Tu cuenta ya está lista para generar "
            "certificados de trazabilidad de excedentes alimentarios en 60 segundos.\n\n"
            "Lo que puedes hacer ahora mismo:\n"
            "• Generar tu primer certificado: https://desperdicio.es/#empezar\n"
            "• Crear tu inventario y recibir alertas: https://desperdicio.es/dashboard.html\n"
            "• Vincular Telegram para alertas instant: abre @Vitinceo_bot y escribe /start\n\n"
            "Si tienes dudas, responde a este email.\n\n— Vitin · TRESAAA"
        ),
    },
    "day3": {
        "delay_days": 3,
        "subject": "¿Has generado tu primer certificado?",
        "body": (
            "Hola,\n\nHan pasado 3 días desde que te registraste en desperdicio.es.\n\n"
            "Si todavía no has generado ningún certificado, te recomiendo probarlo HOY con cualquier producto que retires de venta:\n"
            "• Pan que sobra → donar a banco de alimentos\n"
            "• Fruta no perfecta → granja de animales\n"
            "• Restos de cocina → compostaje\n\n"
            "60 segundos en https://desperdicio.es/#empezar y tienes el PDF firmado en tu correo.\n\n— Vitin"
        ),
    },
    "day7": {
        "delay_days": 7,
        "subject": "Cómo desgravar lo que donas (IRPF)",
        "body": (
            "Hola,\n\nUna semana después: ¿sabías que las donaciones a entidades de utilidad pública desgravan hasta el 35% en tu IRPF?\n\n"
            "Pero solo si tienes un certificado válido por cada donación. Sin él, Hacienda no acepta la deducción.\n\n"
            "Te explicamos los requisitos exactos en este post: https://desperdicio.es/blog/deducir-donacion-alimentos-irpf-autonomo.html\n\n"
            "Y si donas habitualmente, el plan Solo a 1,99€/mes son certificados ilimitados (recuperas el coste del año en 1 sola donación).\n\n— Vitin"
        ),
    },
    "churn_rescue": {
        "delay_days": 0,  # se dispara on-demand cuando hay cancelación
        "subject": "Antes de irte… ¿qué te ha faltado?",
        "body": (
            "Hola,\n\nVeo que has cancelado tu suscripción a desperdicio.es. Antes de despedirte, ¿podrías contestarme qué te ha faltado o qué no funcionó?\n\n"
            "Cualquier feedback me ayuda muchísimo. Incluso si solo es 'demasiado caro' o 'no lo usaba lo suficiente'.\n\n"
            "Y si vuelves en los próximos 7 días, te aplicamos 1 mes gratis. Solo respondes a este email con 'vuelvo' y te lo activo.\n\n— Vitin"
        ),
    },
}


@router.post("/drip/send/{campaign}")
def trigger_drip_campaign(
    campaign: str,
    user_email: EmailStr = Query(...),
    db: Session = Depends(get_db),
):
    """Envía un email de campaña drip al usuario indicado."""
    if campaign not in DRIP_CAMPAIGNS:
        raise HTTPException(status_code=404, detail=f"Campaña '{campaign}' no existe")

    cfg = DRIP_CAMPAIGNS[campaign]

    # Idempotencia: no reenviar si ya se envió en últimos 30d
    recent = db.query(EmailCampaignLogDB).filter(
        EmailCampaignLogDB.user_email == user_email,
        EmailCampaignLogDB.campaign == campaign,
        EmailCampaignLogDB.sent_at >= datetime.utcnow() - timedelta(days=30),
    ).first()
    if recent:
        return {"sent": False, "reason": "ya enviada en los últimos 30 días"}

    try:
        from desperdicio_email import send_email
        body_html = cfg["body"].replace("\n", "<br>")
        success = send_email(
            user_email,
            cfg["subject"],
            f"<html><body style='font-family:sans-serif;line-height:1.6'>{body_html}</body></html>",
            text_fallback=cfg["body"],
        )
    except Exception as e:
        log.error("Drip send fail: %s", e)
        success = False

    log_row = EmailCampaignLogDB(user_email=user_email, campaign=campaign)
    db.add(log_row)
    db.commit()

    return {"sent": success, "campaign": campaign, "log_id": log_row.id}


@router.post("/drip/cron/run-pending")
def run_pending_drip_campaigns(
    cron_secret: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Cron diario: recorre users y envía drips según delay_days desde signup."""
    expected = os.getenv("CRON_SECRET", "")
    if expected and cron_secret != expected:
        raise HTTPException(status_code=403, detail="Cron auth fail")

    sent_count = 0
    today = datetime.utcnow()

    for user in db.query(UserDB).all():
        signup_age_days = (today - user.created_at).days if user.created_at else 0

        for campaign_name, cfg in DRIP_CAMPAIGNS.items():
            if campaign_name == "churn_rescue":
                continue  # solo on-demand
            if signup_age_days < cfg["delay_days"]:
                continue

            recent = db.query(EmailCampaignLogDB).filter(
                EmailCampaignLogDB.user_email == user.email,
                EmailCampaignLogDB.campaign == campaign_name,
            ).first()
            if recent:
                continue

            try:
                from desperdicio_email import send_email
                send_email(user.email, cfg["subject"], cfg["body"].replace("\n", "<br>"), text_fallback=cfg["body"])
                db.add(EmailCampaignLogDB(user_email=user.email, campaign=campaign_name))
                sent_count += 1
            except Exception as e:
                log.warning("Drip cron fail %s: %s", user.email, e)

    db.commit()
    return {"sent": sent_count, "executed_at": today.isoformat() + "Z"}


# ============================================================================
# Sprint 31 — Public API quickstart docs (mini OpenAPI passthrough info)
# ============================================================================

@router.get("/api-info")
def api_info():
    """Información para developers que integren la API públicamente."""
    return {
        "name": "desperdicio.es Public API",
        "version": "1.0",
        "base_url": "https://surplusai-backend-production.up.railway.app/api/v1",
        "auth": "Bearer JWT (obtenido via /auth/magic-link/verify)",
        "rate_limit_free": "60 req/min",
        "rate_limit_paid": "600 req/min",
        "openapi_docs": "https://surplusai-backend-production.up.railway.app/docs",
        "webhooks_supported": ["certificate.created", "inventory.expiring", "subscription.changed"],
        "support_email": "info@tresaaa.com",
    }


# ============================================================================
# Sprint 33 — Carbon credits export simple
# ============================================================================

CO2_KG_PER_KG_FOOD_AVOIDED = 2.5  # kg CO2eq por kg comida evitada (FAO promedio)


@router.get("/carbon/me")
def my_carbon_impact(user_email: EmailStr, db: Session = Depends(get_db)):
    """Calcula CO2 evitado total por el usuario según sus certificados."""
    user = db.query(UserDB).filter(UserDB.email == user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no existe")

    rows = db.query(PdfCertificateDB).filter(
        PdfCertificateDB.user_id == user.id,
        PdfCertificateDB.destino.in_(["food_bank", "donated_ong", "cattle_feed", "compost"]),
    ).all()

    total_kg = sum(r.cantidad for r in rows if r.unidad == "kg")
    total_co2 = total_kg * CO2_KG_PER_KG_FOOD_AVOIDED

    return {
        "user_email": user_email,
        "kg_food_recovered": round(total_kg, 1),
        "kg_co2eq_avoided": round(total_co2, 1),
        "tree_year_equivalents": round(total_co2 / 21, 1),  # 1 árbol absorbe ~21kg CO2/año
        "car_km_equivalents": round(total_co2 * 5, 0),  # ~200g CO2/km coche promedio
        "certificates_count": len(rows),
        "factor": "2,5 kg CO2eq/kg alimento evitado (FAO promedio sector hostelería)",
    }


# ============================================================================
# Sprint 32 — White-label info endpoint
# ============================================================================

@router.get("/whitelabel/info")
def whitelabel_info():
    """Info para asesorías que quieren white-label."""
    return {
        "name": "desperdicio.es White-Label para asesorías",
        "description": "Tu marca, tu URL, tus colores. Integra el motor desperdicio.es en tu propio dominio.",
        "pricing": {
            "setup": 999,
            "monthly_base": 199,
            "per_active_client_eur": 1.50,
            "currency": "EUR",
        },
        "features_included": [
            "Subdominio personalizado (tu-marca.desperdicio.es)",
            "Dominio propio (con tu certificado SSL)",
            "Tu logo en todos los certificados PDF",
            "Tu paleta de colores en la UI",
            "Hasta 1.000 clientes B2B incluidos en plan base",
            "API para gestión masiva",
            "Soporte prioritario por Slack",
        ],
        "min_clients_breakeven_eur_per_month": 30,
        "contact": "info@tresaaa.com",
    }
