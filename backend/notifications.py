"""
Email notifications module for AEGIS-FOOD marketplace.
Sends emails on matches, bids, and transaction acceptance.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Email configuration from environment variables
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "noreply@aegis-food.com")
NOTIFICATIONS_ENABLED = os.getenv("NOTIFICATIONS_ENABLED", "true").lower() == "true"


def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None
) -> bool:
    """
    Send an email via SMTP.

    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML email body
        text_content: Plain text fallback

    Returns:
        True if successful, False otherwise
    """

    # Validate inputs
    if not to_email or len(to_email.strip()) == 0:
        logger.warning("Email address is empty")
        return False

    if not subject or len(subject.strip()) == 0:
        logger.warning("Email subject is empty")
        return False

    if not NOTIFICATIONS_ENABLED or not SMTP_USERNAME:
        logger.info(f"Notifications disabled or not configured. Would send to {to_email}")
        return False

    try:
        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM_EMAIL
        msg["To"] = to_email

        # Add text part
        if text_content:
            msg.attach(MIMEText(text_content, "plain"))

        # Add HTML part
        msg.attach(MIMEText(html_content, "html"))

        # Send email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)

        logger.info(f"Email sent successfully to {to_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        return False


def notify_match_found(
    generator_email: str,
    generator_name: str,
    receptor_name: str,
    product: str,
    quantity_kg: float,
    match_score: float
) -> bool:
    """
    Notify a generator when a good match is found.

    Args:
        generator_email: Generator email address
        generator_name: Generator company name
        receptor_name: Receptor company name
        product: Product name
        quantity_kg: Quantity in kg
        match_score: Match compatibility score (0-1)

    Returns:
        True if successful, False otherwise
    """

    subject = f"AEGIS-FOOD: Nuevo Comprador Compatible - {receptor_name}"

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #2d5016;">Hemos encontrado un comprador compatible</h2>

                <p>Hola {generator_name},</p>

                <p>Hemos identificado a <strong>{receptor_name}</strong> como un posible comprador para tu producto
                <strong>{product}</strong>.</p>

                <div style="background: #f0f0f0; padding: 15px; border-radius: 5px; margin: 20px 0;">
                    <p><strong>Detalles de la Compatibilidad:</strong></p>
                    <ul>
                        <li>Cantidad disponible: {quantity_kg} kg</li>
                        <li>Score de compatibilidad: {match_score * 100:.0f}%</li>
                        <li>Categoría interesada: Productos similares a {product}</li>
                    </ul>
                </div>

                <p>Te recomendamos publicar un lote de este producto en AEGIS-FOOD para que {receptor_name}
                pueda hacer una oferta.</p>

                <p style="margin-top: 30px; font-size: 0.9em; color: #666;">
                    Este es un mensaje automático de AEGIS-FOOD.<br>
                    Por favor no responder a este correo.
                </p>
            </div>
        </body>
    </html>
    """

    text_content = f"""
    Hola {generator_name},

    Hemos identificado a {receptor_name} como un posible comprador para tu producto {product}.

    Cantidad disponible: {quantity_kg} kg
    Score de compatibilidad: {match_score * 100:.0f}%

    Te recomendamos publicar un lote de este producto en AEGIS-FOOD.

    AEGIS-FOOD
    """

    return send_email(generator_email, subject, html_content, text_content)


def notify_bid_received(
    generator_email: str,
    generator_name: str,
    receptor_name: str,
    product: str,
    bid_price: float,
    bid_quantity: float
) -> bool:
    """
    Notify a generator when a bid is received on their lot.

    Args:
        generator_email: Generator email address
        generator_name: Generator company name
        receptor_name: Receptor company name
        product: Product name
        bid_price: Bid price in EUR
        bid_quantity: Bid quantity in kg

    Returns:
        True if successful, False otherwise
    """

    subject = f"AEGIS-FOOD: Nueva Oferta Recibida - {product}"

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #2d5016;">Has recibido una nueva oferta</h2>

                <p>Hola {generator_name},</p>

                <p><strong>{receptor_name}</strong> ha hecho una oferta en tu lote de <strong>{product}</strong>.</p>

                <div style="background: #e8f5e9; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #4a7c2c;">
                    <p><strong>Detalles de la Oferta:</strong></p>
                    <ul>
                        <li>Producto: {product}</li>
                        <li>Cantidad: {bid_quantity} kg</li>
                        <li>Precio ofertado: €{bid_price:.2f}</li>
                        <li>Comprador: {receptor_name}</li>
                    </ul>
                </div>

                <p>Accede a tu cuenta en AEGIS-FOOD para revisar todas las ofertas recibidas y aceptar la que consideres más conveniente.</p>

                <p style="margin-top: 30px; font-size: 0.9em; color: #666;">
                    Este es un mensaje automático de AEGIS-FOOD.<br>
                    Por favor no responder a este correo.
                </p>
            </div>
        </body>
    </html>
    """

    text_content = f"""
    Hola {generator_name},

    {receptor_name} ha hecho una oferta en tu lote de {product}.

    Detalles de la Oferta:
    - Producto: {product}
    - Cantidad: {bid_quantity} kg
    - Precio ofertado: €{bid_price:.2f}
    - Comprador: {receptor_name}

    Accede a tu cuenta en AEGIS-FOOD para revisar y aceptar ofertas.

    AEGIS-FOOD
    """

    return send_email(generator_email, subject, html_content, text_content)


def notify_bid_accepted(
    receptor_email: str,
    receptor_name: str,
    generator_name: str,
    product: str,
    final_price: float,
    quantity_kg: float,
    transaction_id: int
) -> bool:
    """
    Notify a receptor when their bid is accepted.

    Args:
        receptor_email: Receptor email address
        receptor_name: Receptor company name
        generator_name: Generator company name
        product: Product name
        final_price: Final agreed price in EUR
        quantity_kg: Quantity in kg
        transaction_id: Transaction ID

    Returns:
        True if successful, False otherwise
    """

    subject = f"AEGIS-FOOD: Tu Oferta ha sido Aceptada - {product}"

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #2d5016;">Tu oferta ha sido aceptada</h2>

                <p>Hola {receptor_name},</p>

                <p><strong>{generator_name}</strong> ha aceptado tu oferta. ¡Transacción completada!</p>

                <div style="background: #d4edda; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #28a745;">
                    <p><strong>Detalles de la Transacción:</strong></p>
                    <ul>
                        <li>Producto: {product}</li>
                        <li>Cantidad: {quantity_kg} kg</li>
                        <li>Precio final: €{final_price:.2f}</li>
                        <li>Generador: {generator_name}</li>
                        <li>ID Transacción: {transaction_id}</li>
                    </ul>
                </div>

                <p>Los próximos pasos incluyen la coordinación de entrega y la generación automática de documentos de cumplimiento normativo.</p>

                <p>Accede a tu cuenta en AEGIS-FOOD para ver el estado completo de la transacción.</p>

                <p style="margin-top: 30px; font-size: 0.9em; color: #666;">
                    Este es un mensaje automático de AEGIS-FOOD.<br>
                    Por favor no responder a este correo.
                </p>
            </div>
        </body>
    </html>
    """

    text_content = f"""
    Hola {receptor_name},

    {generator_name} ha aceptado tu oferta. ¡Transacción completada!

    Detalles de la Transacción:
    - Producto: {product}
    - Cantidad: {quantity_kg} kg
    - Precio final: €{final_price:.2f}
    - Generador: {generator_name}
    - ID Transacción: {transaction_id}

    Accede a tu cuenta en AEGIS-FOOD para ver más detalles.

    AEGIS-FOOD
    """

    return send_email(receptor_email, subject, html_content, text_content)


def notify_transaction_completed(
    generator_email: str,
    receptor_email: str,
    generator_name: str,
    receptor_name: str,
    product: str,
    quantity_kg: float,
    final_price: float,
    co2_avoided_kg: float,
    transaction_id: int
) -> bool:
    """
    Notify both parties when a transaction is completed.

    Args:
        generator_email: Generator email
        receptor_email: Receptor email
        generator_name: Generator name
        receptor_name: Receptor name
        product: Product name
        quantity_kg: Quantity
        final_price: Final price
        co2_avoided_kg: CO2 avoided
        transaction_id: Transaction ID

    Returns:
        True if successful, False otherwise
    """

    subject = f"AEGIS-FOOD: Transacción Completada - {product} ({transaction_id})"

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #2d5016;">Transacción Completada</h2>

                <p>La transacción ha sido procesada con éxito.</p>

                <div style="background: #f0f0f0; padding: 15px; border-radius: 5px; margin: 20px 0;">
                    <p><strong>Resumen de la Transacción:</strong></p>
                    <ul>
                        <li>ID Transacción: {transaction_id}</li>
                        <li>Producto: {product}</li>
                        <li>Cantidad: {quantity_kg} kg</li>
                        <li>Precio final: €{final_price:.2f}</li>
                        <li>Generador: {generator_name}</li>
                        <li>Receptor: {receptor_name}</li>
                    </ul>
                </div>

                <div style="background: #e8f5e9; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #4a7c2c;">
                    <p><strong>Impacto Ambiental:</strong></p>
                    <p>CO2 evitado: <strong>{co2_avoided_kg:.2f} kg CO2e</strong></p>
                </div>

                <p>Los documentos de cumplimiento normativo han sido generados automáticamente.</p>

                <p style="margin-top: 30px; font-size: 0.9em; color: #666;">
                    Este es un mensaje automático de AEGIS-FOOD.<br>
                    Por favor no responder a este correo.
                </p>
            </div>
        </body>
    </html>
    """

    text_content = f"""
    Transacción Completada

    ID Transacción: {transaction_id}
    Producto: {product}
    Cantidad: {quantity_kg} kg
    Precio final: €{final_price:.2f}
    CO2 evitado: {co2_avoided_kg:.2f} kg CO2e

    Los documentos de cumplimiento normativo han sido generados automáticamente.

    AEGIS-FOOD
    """

    # Send to both parties
    success = True
    success &= send_email(generator_email, subject, html_content, text_content)
    success &= send_email(receptor_email, subject, html_content, text_content)

    return success
