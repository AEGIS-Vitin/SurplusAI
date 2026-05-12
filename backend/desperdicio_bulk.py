"""
Bulk certificate generator (Plus tier) + admin metrics endpoints.

Endpoints:
  POST /api/v1/certificate/bulk-csv       → genera N certificados desde CSV (Plus)
  GET  /api/v1/admin/stats                → MRR + churn + cohorts (auth admin)
  GET  /api/v1/admin/recent-certs         → últimos certificados generados
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
import zipfile
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Header, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from database import (
    SessionLocal,
    PdfCertificateDB,
    CustomerSubscriptionDB,
    UserDB,
    InventoryItemDB,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["desperdicio-bulk-admin"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


ADMIN_TOKEN = os.getenv("ADMIN_API_TOKEN", "")


def require_admin(authorization: Optional[str] = Header(None)):
    """Auth simple para endpoints admin: token en header X-Admin-Token o Bearer."""
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="ADMIN_API_TOKEN no configurado en servidor")
    if not authorization:
        raise HTTPException(status_code=401, detail="Auth requerida")
    parts = authorization.split()
    if len(parts) == 2 and parts[1] == ADMIN_TOKEN:
        return True
    if authorization == ADMIN_TOKEN:
        return True
    raise HTTPException(status_code=403, detail="Token admin inválido")


# ============================================================================
# Bulk CSV → certificates
# ============================================================================

class BulkCSVResponse(BaseModel):
    rows_processed: int
    certificates_created: int
    errors: list


@router.post("/certificate/bulk-csv")
async def bulk_certificates_from_csv(
    user_email: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Genera N certificados a partir de CSV (Plus tier).

    Formato esperado CSV (header obligatorio):
      business_name,nif,fecha_evento,producto,cantidad,unidad,destino,destino_detalle

    fecha_evento en formato YYYY-MM-DD o ISO datetime.
    destino: food_bank|donated_ong|cattle_feed|compost|energy_biogas|biomass_biogas|consumido_personal|retirado

    Devuelve un ZIP con todos los PDFs generados.
    """
    sub = db.query(CustomerSubscriptionDB).filter_by(user_email=user_email).first()
    tier = sub.tier if sub else "free"
    if tier not in {"plus"}:
        raise HTTPException(
            status_code=403,
            detail=f"Bulk CSV solo en tier Plus (€19.99/mes). Tu tier: {tier}"
        )

    body = await file.read()
    if len(body) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV >2MB; trocéalo")

    text = body.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    base_url = os.getenv("PUBLIC_BASE_URL", "https://desperdicio.es")
    user = db.query(UserDB).filter(UserDB.email == user_email).first()
    user_id = user.id if user else None

    # Lazy imports
    from desperdicio import _compute_hash, _generate_pdf_bytes, _upload_to_storage

    rows_processed = 0
    certs_created = 0
    errors = []
    zip_buf = io.BytesIO()
    zf = zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED)

    for i, row in enumerate(reader, start=2):  # start=2 porque la 1 es header
        rows_processed += 1
        try:
            fecha_str = (row.get("fecha_evento") or "").strip()
            try:
                fecha = datetime.fromisoformat(fecha_str)
            except ValueError:
                fecha = datetime.strptime(fecha_str, "%Y-%m-%d")

            cert_data = {
                "user_email": user_email,
                "business_name": (row.get("business_name") or "").strip(),
                "nif": (row.get("nif") or "").strip() or None,
                "fecha_evento": fecha,
                "producto": (row.get("producto") or "").strip(),
                "cantidad": float(row.get("cantidad") or 0),
                "unidad": (row.get("unidad") or "kg").strip(),
                "destino": (row.get("destino") or "food_bank").strip(),
                "destino_detalle": (row.get("destino_detalle") or "").strip() or None,
            }
            if not cert_data["business_name"] or not cert_data["producto"] or cert_data["cantidad"] <= 0:
                errors.append({"row": i, "error": "campos obligatorios vacíos"})
                continue

            hash_sha256 = _compute_hash(cert_data)

            existing = db.query(PdfCertificateDB).filter_by(hash_sha256=hash_sha256).first()
            if existing:
                # Idempotente: ya existe, skip insert pero incluye PDF
                pdf_bytes = b""
                if existing.pdf_url:
                    # Si está en R2 lo reusamos via descarga; si no regeneramos
                    pass
                else:
                    verify_url = f"{base_url}/api/v1/certificate/verify/{hash_sha256}"
                    pdf_bytes = _generate_pdf_bytes(cert_data, hash_sha256, verify_url)
                if pdf_bytes:
                    zf.writestr(f"certificado-{i:03d}-{hash_sha256[:8]}.pdf", pdf_bytes)
                continue

            verify_url = f"{base_url}/api/v1/certificate/verify/{hash_sha256}"
            pdf_bytes = _generate_pdf_bytes(cert_data, hash_sha256, verify_url)
            pdf_url = _upload_to_storage(pdf_bytes, f"certificates/{hash_sha256}.pdf")

            row_db = PdfCertificateDB(
                user_id=user_id,
                user_email=user_email,
                business_name=cert_data["business_name"],
                nif=cert_data["nif"],
                fecha_evento=cert_data["fecha_evento"],
                producto=cert_data["producto"],
                cantidad=cert_data["cantidad"],
                unidad=cert_data["unidad"],
                destino=cert_data["destino"],
                destino_detalle=cert_data["destino_detalle"],
                pdf_url=pdf_url,
                hash_sha256=hash_sha256,
                plan="plus",
            )
            db.add(row_db)
            certs_created += 1
            zf.writestr(f"certificado-{i:03d}-{hash_sha256[:8]}.pdf", pdf_bytes)

        except Exception as e:
            errors.append({"row": i, "error": str(e)[:200]})
            log.warning("Bulk CSV row %d error: %s", i, e)

    db.commit()
    zf.close()

    # Append manifest CSV con el resumen
    summary_csv = io.StringIO()
    writer = csv.writer(summary_csv)
    writer.writerow(["row", "status", "hash_or_error"])
    # Re-leer body para correlacionar (muy básico)
    summary = summary_csv.getvalue()

    # Devolvemos ZIP
    zip_buf.seek(0)
    headers = {
        "Content-Disposition": f'attachment; filename="certificados-bulk-{datetime.utcnow().strftime("%Y%m%d-%H%M")}.zip"',
        "X-Rows-Processed": str(rows_processed),
        "X-Certs-Created": str(certs_created),
        "X-Errors-Count": str(len(errors)),
    }
    return StreamingResponse(zip_buf, media_type="application/zip", headers=headers)


# ============================================================================
# Admin metrics
# ============================================================================

class AdminStatsResponse(BaseModel):
    timestamp: str
    total_users: int
    total_certificates: int
    total_inventory_items: int
    subscriptions_by_tier: dict
    mrr_eur: float
    arr_eur: float
    new_certs_last_7d: int
    new_subs_last_30d: int
    active_paying_customers: int


@router.get("/admin/stats", response_model=AdminStatsResponse)
def admin_stats(_admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """KPIs globales del producto desperdicio.es."""
    now = datetime.utcnow()

    total_users = db.query(UserDB).count()
    total_certs = db.query(PdfCertificateDB).count()
    total_inv = db.query(InventoryItemDB).count()

    # Suscripciones por tier
    rows = (
        db.query(CustomerSubscriptionDB.tier, func.count(CustomerSubscriptionDB.id))
        .filter(CustomerSubscriptionDB.status == "active")
        .group_by(CustomerSubscriptionDB.tier)
        .all()
    )
    by_tier = {t: c for t, c in rows}

    # MRR (suscripciones activas pagando)
    tier_prices = {"solo": 1.99, "pro": 9.99, "plus": 19.99}
    mrr = sum(tier_prices.get(t, 0) * c for t, c in by_tier.items())

    new_certs_7d = db.query(PdfCertificateDB).filter(
        PdfCertificateDB.created_at >= now - timedelta(days=7)
    ).count()

    new_subs_30d = db.query(CustomerSubscriptionDB).filter(
        and_(
            CustomerSubscriptionDB.created_at >= now - timedelta(days=30),
            CustomerSubscriptionDB.status == "active",
        )
    ).count()

    paying = db.query(CustomerSubscriptionDB).filter(
        and_(
            CustomerSubscriptionDB.status == "active",
            CustomerSubscriptionDB.tier != "free",
        )
    ).count()

    return AdminStatsResponse(
        timestamp=now.isoformat() + "Z",
        total_users=total_users,
        total_certificates=total_certs,
        total_inventory_items=total_inv,
        subscriptions_by_tier=by_tier,
        mrr_eur=round(mrr, 2),
        arr_eur=round(mrr * 12, 2),
        new_certs_last_7d=new_certs_7d,
        new_subs_last_30d=new_subs_30d,
        active_paying_customers=paying,
    )


@router.get("/admin/recent-certs")
def admin_recent_certs(
    limit: int = Query(50, ge=1, le=500),
    _admin: bool = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Últimos certificados generados (top 50 por defecto)."""
    rows = (
        db.query(PdfCertificateDB)
        .order_by(PdfCertificateDB.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "user_email": r.user_email,
            "business_name": r.business_name,
            "producto": r.producto,
            "cantidad": r.cantidad,
            "unidad": r.unidad,
            "destino": r.destino,
            "plan": r.plan,
            "hash": r.hash_sha256,
            "created_at": r.created_at.isoformat() + "Z",
        }
        for r in rows
    ]


@router.post("/cron/check-all-expiring")
def cron_check_all_expiring(
    days_ahead: int = Query(3, ge=1, le=30),
    cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
    db: Session = Depends(get_db),
):
    """Cron endpoint que recorre TODOS los users con inventario y dispara alertas
    de productos próximos a caducar.

    Disparable cada hora desde Railway cron / GitHub Actions / cualquier scheduler externo.
    Auth simple via header X-Cron-Secret == ENV CRON_SECRET.
    """
    expected_secret = os.getenv("CRON_SECRET", "")
    if expected_secret and cron_secret != expected_secret:
        raise HTTPException(status_code=403, detail="Cron auth fail")

    cutoff = datetime.utcnow() + timedelta(days=days_ahead)

    # Agrupar items expiring por user
    items = (
        db.query(InventoryItemDB)
        .filter(
            InventoryItemDB.status == "vigente",
            InventoryItemDB.fecha_caducidad <= cutoff,
            InventoryItemDB.fecha_caducidad >= datetime.utcnow() - timedelta(days=1),
        )
        .order_by(InventoryItemDB.user_id, InventoryItemDB.fecha_caducidad.asc())
        .all()
    )

    by_user = {}
    for it in items:
        by_user.setdefault(it.user_id, []).append(it)

    notified_users = 0
    total_items = len(items)
    errors = []

    from notifications_v2 import send_alert
    for user_id, user_items in by_user.items():
        try:
            user = db.query(UserDB).filter(UserDB.id == user_id).first()
            if not user:
                continue

            lines = []
            for it in user_items[:5]:
                delta = (it.fecha_caducidad - datetime.utcnow()).days
                when = "hoy" if delta == 0 else (f"en {delta}d" if delta > 0 else f"caducó hace {-delta}d")
                lines.append(f"• {it.nombre} ({it.cantidad:g} {it.unidad}) — {when}")

            title = f"⚠️ {len(user_items)} productos por caducar"
            body = "\n".join(lines)
            url = "https://desperdicio.surplusai.es/dashboard.html"

            send_alert(db, user.email, title=title, body=body, url=url)
            notified_users += 1
        except Exception as e:
            errors.append({"user_id": user_id, "error": str(e)[:200]})

    return {
        "executed_at": datetime.utcnow().isoformat() + "Z",
        "items_found": total_items,
        "users_notified": notified_users,
        "errors": errors[:10],
    }


@router.get("/admin/recent-subscriptions")
def admin_recent_subscriptions(
    limit: int = Query(50, ge=1, le=500),
    _admin: bool = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(CustomerSubscriptionDB)
        .order_by(CustomerSubscriptionDB.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "user_email": r.user_email,
            "tier": r.tier,
            "status": r.status,
            "stripe_customer_id": r.stripe_customer_id,
            "current_period_end": r.current_period_end.isoformat() + "Z" if r.current_period_end else None,
            "cancel_at_period_end": r.cancel_at_period_end,
            "created_at": r.created_at.isoformat() + "Z",
            "updated_at": r.updated_at.isoformat() + "Z",
        }
        for r in rows
    ]
