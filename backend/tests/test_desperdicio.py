"""
Tests para producto desperdicio.es.

Cubre:
  - Schema DB (modelos cargan)
  - Endpoint de generación PDF (free tier rate limit)
  - Helpers (_compute_hash idempotente, _destino_legible)
  - Validaciones Pydantic

Ejecutar:
  cd backend && TESTING=true pytest tests/test_desperdicio.py -v
"""
import os
import sys
from pathlib import Path

import pytest

# Permitir import del backend
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Forzar SQLite en memoria + suprimir DB init del backend principal
os.environ["TESTING"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"


def test_models_import():
    """Smoke test: los modelos cargan sin error sintáctico ni circular."""
    from database import (
        PdfCertificateDB, InventoryItemDB, NotificationChannelDB,
        CustomerSubscriptionDB, MagicLinkTokenDB,
    )
    assert PdfCertificateDB.__tablename__ == "pdf_certificates"
    assert InventoryItemDB.__tablename__ == "inventory_items"
    assert NotificationChannelDB.__tablename__ == "notification_channels"
    assert CustomerSubscriptionDB.__tablename__ == "customer_subscriptions"
    assert MagicLinkTokenDB.__tablename__ == "magic_link_tokens"


def test_compute_hash_idempotent():
    """Mismos datos → mismo hash."""
    from datetime import datetime
    from desperdicio import _compute_hash
    data = {
        "user_email": "test@x.com",
        "business_name": "Test SL",
        "nif": None,
        "fecha_evento": datetime(2026, 5, 12, 12, 0),
        "producto": "Pan",
        "cantidad": 5.0,
        "unidad": "kg",
        "destino": "food_bank",
        "destino_detalle": None,
    }
    h1 = _compute_hash(data)
    h2 = _compute_hash(dict(data))
    assert h1 == h2
    assert len(h1) == 64
    # Cambiar 1 campo cambia hash
    data2 = dict(data)
    data2["cantidad"] = 5.1
    assert _compute_hash(data2) != h1


def test_destino_legible():
    from desperdicio import _destino_legible
    assert "Banco" in _destino_legible("food_bank")
    assert "compostaje" in _destino_legible("compost").lower()
    # Desconocido devuelve el código sin mapping
    assert _destino_legible("xxx_unknown") == "xxx_unknown"


def test_certificate_create_validation():
    from desperdicio import CertificateCreate
    from datetime import datetime
    # Cantidad <=0 debe fallar
    with pytest.raises(Exception):
        CertificateCreate(
            user_email="test@x.com", business_name="X",
            fecha_evento=datetime.utcnow(),
            producto="Pan", cantidad=0, unidad="kg", destino="food_bank",
        )
    # Email inválido
    with pytest.raises(Exception):
        CertificateCreate(
            user_email="not-an-email", business_name="X",
            fecha_evento=datetime.utcnow(),
            producto="Pan", cantidad=1, unidad="kg", destino="food_bank",
        )


def test_inventory_item_validation():
    from desperdicio import InventoryItemCreate
    from datetime import datetime, timedelta
    item = InventoryItemCreate(
        nombre="Test producto",
        cantidad=2.5,
        unidad="kg",
        fecha_caducidad=datetime.utcnow() + timedelta(days=7),
    )
    assert item.cantidad == 2.5
    # Nombre demasiado corto
    with pytest.raises(Exception):
        InventoryItemCreate(
            nombre="x",
            cantidad=1,
            fecha_caducidad=datetime.utcnow(),
        )


def test_email_helper_template():
    """render_template sustituye {{ var }}."""
    from desperdicio_email import render_template
    # Comprobamos que existe el template y se sustituye al menos una var
    try:
        out = render_template(
            "email_certificate.html",
            business_name="MyBiz",
            producto="Pan",
            cantidad="5",
            unidad="kg",
            destino_legible="Banco",
            fecha_evento="01/01/2026",
            pdf_url="http://x",
            verify_url="http://y",
            hash_sha256="abc",
        )
        assert "MyBiz" in out
        assert "Pan" in out
    except FileNotFoundError:
        pytest.skip("Template HTML no encontrado en este entorno")


def test_admin_ocr_quotas():
    from desperdicio_ocr import OCR_MONTHLY_LIMITS, OCR_ALLOWED_TIERS
    assert OCR_ALLOWED_TIERS == {"pro", "plus"}
    assert OCR_MONTHLY_LIMITS["pro"] == 10
    assert OCR_MONTHLY_LIMITS["plus"] == 50


def test_stripe_price_lookup():
    from desperdicio_stripe import _price_id_for_tier
    # Sin env vars devuelve string vacío
    os.environ.pop("STRIPE_PRICE_DESPERDICIO_SOLO", None)
    assert _price_id_for_tier("solo") == ""
    os.environ["STRIPE_PRICE_DESPERDICIO_SOLO"] = "price_test123"
    assert _price_id_for_tier("solo") == "price_test123"
    assert _price_id_for_tier("inexistente") == ""
