"""
Helper de email para desperdicio.es.

Renderiza plantillas HTML simples (con sustitución {{ var }}) y envía via SMTP.
Usa las variables del .env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_FROM, SMTP_PASSWORD.
Tolerante a fallos: si SMTP no configurado, devuelve False sin raisear.
"""
from __future__ import annotations

import logging
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER") or os.getenv("SMTP_USERNAME", "")
SMTP_FROM = os.getenv("SMTP_FROM") or os.getenv("SMTP_FROM_EMAIL") or SMTP_USER
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

TEMPLATES_DIR = Path(__file__).parent / "templates"


def render_template(template_name: str, **context) -> str:
    """Renderizado mínimo de templates Jinja-like (sustitución {{ var }})."""
    path = TEMPLATES_DIR / template_name
    if not path.exists():
        raise FileNotFoundError(f"Template no encontrado: {template_name}")
    text = path.read_text(encoding="utf-8")
    for k, v in context.items():
        text = text.replace("{{ " + k + " }}", str(v))
        text = text.replace("{{" + k + "}}", str(v))
    # Limpia variables no resueltas (deja [missing]) para no exponer plantilla cruda
    text = re.sub(r"\{\{\s*\w+\s*\}\}", "[…]", text)
    return text


def send_email(to_email: str, subject: str, html: str, text_fallback: Optional[str] = None) -> bool:
    """Envía email vía SMTP. Devuelve True si OK."""
    if not SMTP_USER or not SMTP_PASSWORD:
        log.warning("[desperdicio_email] SMTP no configurado (USER o PASSWORD vacío). Skip.")
        return False
    if not to_email or "@" not in to_email:
        log.warning("[desperdicio_email] to_email inválido: %r", to_email)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"desperdicio.es <{SMTP_FROM}>"
    msg["To"] = to_email
    if text_fallback:
        msg.attach(MIMEText(text_fallback, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        log.info("[desperdicio_email] enviado a %s subject=%s", to_email, subject[:40])
        return True
    except Exception as e:
        log.error("[desperdicio_email] fail enviando a %s: %s", to_email, e)
        return False


def send_certificate_email(
    user_email: str,
    business_name: str,
    producto: str,
    cantidad: float,
    unidad: str,
    destino_legible: str,
    fecha_evento_str: str,
    pdf_url: str,
    verify_url: str,
    hash_sha256: str,
) -> bool:
    """Envía el email post-generación con PDF + verify URL."""
    try:
        html = render_template(
            "email_certificate.html",
            business_name=business_name,
            producto=producto,
            cantidad=f"{cantidad:g}",
            unidad=unidad,
            destino_legible=destino_legible,
            fecha_evento=fecha_evento_str,
            pdf_url=pdf_url,
            verify_url=verify_url,
            hash_sha256=hash_sha256,
        )
    except FileNotFoundError as e:
        log.error("[desperdicio_email] template fail: %s", e)
        return False

    text = (
        f"Tu certificado de {business_name} está listo.\n"
        f"Producto: {producto} ({cantidad:g} {unidad})\n"
        f"Destino: {destino_legible}\n\n"
        f"Descargar PDF: {pdf_url}\n"
        f"Verificación pública: {verify_url}\n\n"
        f"Hash SHA-256: {hash_sha256}\n\n"
        f"— TRESAAA · desperdicio.es"
    )

    subject = f"✅ Tu certificado de trazabilidad — {business_name}"
    return send_email(user_email, subject, html, text_fallback=text)


def send_magic_link_email(user_email: str, magic_link: str) -> bool:
    """Email con magic link de auth (Sprint 5)."""
    html = f"""<!doctype html><html><body style="font-family:sans-serif;background:#FFF8F0;padding:30px">
    <div style="max-width:480px;margin:auto;background:white;padding:30px;border-radius:14px">
      <h2 style="color:#E76F51">Inicia sesión en desperdicio.es</h2>
      <p>Pulsa el botón para entrar — sin contraseña:</p>
      <p style="text-align:center;margin:24px 0">
        <a href="{magic_link}" style="display:inline-block;padding:14px 28px;background:#E76F51;color:white;text-decoration:none;border-radius:100px;font-weight:700">Entrar a mi cuenta</a>
      </p>
      <p style="font-size:13px;color:#888">Si no fuiste tú, ignora este email. El enlace caduca en 15 minutos.</p>
    </div></body></html>"""
    text = f"Pulsa este enlace para iniciar sesión en desperdicio.es:\n\n{magic_link}\n\nCaduca en 15 minutos."
    return send_email(user_email, "Tu acceso a desperdicio.es", html, text_fallback=text)
