"""
Multi-canal de notificaciones para desperdicio.es.

Canales soportados:
  - web_push  → Web Push API con VAPID (PWA instalable)
  - telegram  → Bot @Vitinceo_bot (reutilizado), un mensaje al chat_id vinculado

Uso:
  from notifications_v2 import send_alert
  send_alert(db, user_email, title="Caducan en 2 días", body="...", url="...")

El módulo es tolerante a fallos: si un canal falla, no rompe el resto.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from typing import Optional

import requests
from sqlalchemy.orm import Session

from database import NotificationChannelDB


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:info@tresaaa.com")


# ----------------------------------------------------------------------------
# Telegram
# ----------------------------------------------------------------------------

def send_telegram(chat_id: str, text: str, url: Optional[str] = None) -> bool:
    """Manda un mensaje al chat_id Telegram vinculado.

    Returns True si OK. Logea y devuelve False si falla — no raisea.
    """
    if not TELEGRAM_BOT_TOKEN:
        print("[notifications_v2] TELEGRAM_BOT_TOKEN vacío, skip telegram")
        return False

    body = text
    if url:
        body = f"{text}\n\n👉 {url}"

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": body, "parse_mode": "HTML", "disable_web_page_preview": False},
            timeout=8,
        )
        if r.status_code == 200 and r.json().get("ok"):
            return True
        print(f"[notifications_v2] telegram fail status={r.status_code} body={r.text[:200]}")
        return False
    except Exception as e:
        print(f"[notifications_v2] telegram exception: {e}")
        return False


# ----------------------------------------------------------------------------
# Web Push
# ----------------------------------------------------------------------------

def send_web_push(subscription: dict, title: str, body: str, url: Optional[str] = None) -> bool:
    """Envía notificación Web Push vía VAPID.

    `subscription` es el dict que devuelve PushManager.subscribe() en el navegador:
      {"endpoint": "...", "keys": {"p256dh": "...", "auth": "..."}}

    Lazy-import pywebpush para que el módulo cargue aunque la dependencia no esté instalada.
    """
    if not VAPID_PRIVATE_KEY:
        print("[notifications_v2] VAPID_PRIVATE_KEY vacío, skip web_push")
        return False

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        print("[notifications_v2] pywebpush no instalado, skip web_push")
        return False

    payload = json.dumps({"title": title, "body": body, "url": url or "https://desperdicio.es"})

    # pywebpush espera la private key en PEM o raw bytes. Tenemos raw base64url.
    # Convertimos a PEM via cryptography para que pywebpush lo acepte.
    try:
        from cryptography.hazmat.primitives.asymmetric.ec import derive_private_key, SECP256R1
        from cryptography.hazmat.primitives import serialization

        raw = base64.urlsafe_b64decode(VAPID_PRIVATE_KEY + "==")
        priv_int = int.from_bytes(raw, "big")
        priv = derive_private_key(priv_int, SECP256R1())
        pem = priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
    except Exception as e:
        print(f"[notifications_v2] no pude convertir VAPID a PEM: {e}")
        return False

    try:
        webpush(
            subscription_info=subscription,
            data=payload,
            vapid_private_key=pem,
            vapid_claims={"sub": VAPID_SUBJECT},
            timeout=8,
        )
        return True
    except WebPushException as e:
        print(f"[notifications_v2] web_push fail: {repr(e)}")
        return False
    except Exception as e:
        print(f"[notifications_v2] web_push exception: {e}")
        return False


# ----------------------------------------------------------------------------
# Multi-channel dispatcher
# ----------------------------------------------------------------------------

def send_alert(
    db: Session,
    user_email: str,
    title: str,
    body: str,
    url: Optional[str] = None,
) -> dict:
    """Manda la misma alerta por TODOS los canales habilitados del usuario.

    Returns dict {channel_type: success_bool}.
    """
    channels = db.query(NotificationChannelDB).filter(
        NotificationChannelDB.user_email == user_email,
        NotificationChannelDB.enabled == True,  # noqa: E712
    ).all()

    results = {}
    for ch in channels:
        success = False
        if ch.channel_type == "telegram":
            chat_id = (ch.payload or {}).get("chat_id")
            if chat_id:
                success = send_telegram(str(chat_id), f"<b>{title}</b>\n{body}", url=url)
        elif ch.channel_type == "web_push":
            sub = ch.payload or {}
            if sub.get("endpoint"):
                success = send_web_push(sub, title, body, url)
        else:
            print(f"[notifications_v2] tipo canal desconocido: {ch.channel_type}")
            continue

        results[f"{ch.channel_type}_{ch.id}"] = success
        if success:
            ch.last_used_at = datetime.utcnow()

    if results:
        db.commit()
    return results
