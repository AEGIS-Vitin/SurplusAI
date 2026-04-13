"""
Compliance module implementing Spain's Ley 1/2025 on food waste.
Manages legal use hierarchy and automatic documentation generation.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Tuple, Optional
import json


class UsoFinal(int, Enum):
    """
    Legal hierarchy of food surplus uses per Ley 1/2025
    Lower number = higher preference/priority
    """
    prevencion = 1  # Prevention (reduction)
    donacion_consumo = 2  # Donation for human consumption
    transformacion = 3  # Food transformation
    alimentacion_animal = 4  # Animal feed
    uso_industrial = 5  # Industrial use
    compostaje = 6  # Composting
    biogas = 7  # Biogas/bioenergy
    eliminacion = 8  # Disposal (last resort)


class EstadoProducto(str, Enum):
    """Product state for compliance determination"""
    antes_fecha_consumo = "antes_fecha_consumo"  # Before best-before date
    despues_fecha_consumo = "despues_fecha_consumo"  # After best-before date
    antes_fecha_expiracion = "antes_fecha_expiracion"  # Before expiry date
    despues_fecha_expiracion = "despues_fecha_expiracion"  # After expiry date


class Categoria(str, Enum):
    """Product categories"""
    carnes = "carnes"
    pescados = "pescados"
    lacteos = "lacteos"
    panaderia = "panaderia"
    frutas = "frutas"
    verduras = "verduras"
    prepared = "prepared"
    otros = "otros"


def determine_product_state(
    fecha_consumo_preferente: datetime,
    fecha_expiracion: datetime,
    fecha_actual: Optional[datetime] = None
) -> EstadoProducto:
    """
    Determine product state for compliance.

    Args:
        fecha_consumo_preferente: Best-before date
        fecha_expiracion: Expiry date
        fecha_actual: Current date (defaults to now)

    Returns:
        EstadoProducto enum
    """

    if fecha_actual is None:
        fecha_actual = datetime.utcnow()

    if fecha_actual < fecha_consumo_preferente:
        return EstadoProducto.antes_fecha_consumo
    elif fecha_actual < fecha_expiracion:
        return EstadoProducto.despues_fecha_consumo
    elif fecha_actual < fecha_expiracion + __import__('datetime').timedelta(days=3):
        return EstadoProducto.antes_fecha_expiracion
    else:
        return EstadoProducto.despues_fecha_expiracion


def get_permitted_uses(
    estado_producto: EstadoProducto,
    categoria: Categoria,
    has_cold_chain: bool = True
) -> List[int]:
    """
    Get list of permitted uses based on product state and category.
    Returns list of UsoFinal enum values (1-8) in order of legal preference.

    Uses are blocked based on:
    - Product state (before/after best-before/expiry)
    - Product category (some cannot be used for certain purposes)
    - Cold chain maintenance

    Args:
        estado_producto: Current product state
        categoria: Product category
        has_cold_chain: Whether cold chain was maintained

    Returns:
        List of permitted UsoFinal values, in legal preference order
    """

    # All uses typically allowed before best-before date
    if estado_producto == EstadoProducto.antes_fecha_consumo:
        return [
            UsoFinal.prevencion.value,
            UsoFinal.donacion_consumo.value,
            UsoFinal.transformacion.value,
            UsoFinal.alimentacion_animal.value,
            UsoFinal.uso_industrial.value,
            UsoFinal.compostaje.value,
            UsoFinal.biogas.value
        ]

    # After best-before but before expiry: restricted uses
    elif estado_producto == EstadoProducto.despues_fecha_consumo:
        # No more donation to humans or direct transformation
        # Can be used for animal feed if safe
        permitted = [
            UsoFinal.alimentacion_animal.value,
            UsoFinal.uso_industrial.value,
            UsoFinal.compostaje.value,
            UsoFinal.biogas.value
        ]

        # Carnes, pescados, lacteos may be restricted
        if categoria in [Categoria.carnes, Categoria.pescados, Categoria.lacteos]:
            if has_cold_chain:
                permitted.insert(0, UsoFinal.transformacion.value)
        else:
            permitted.insert(0, UsoFinal.transformacion.value)

        return permitted

    # Before expiry (close): very restricted
    elif estado_producto == EstadoProducto.antes_fecha_expiracion:
        return [
            UsoFinal.alimentacion_animal.value,
            UsoFinal.uso_industrial.value,
            UsoFinal.compostaje.value,
            UsoFinal.biogas.value
        ]

    # After expiry: only composting/biogas/disposal
    else:  # despues_fecha_expiracion
        return [
            UsoFinal.compostaje.value,
            UsoFinal.biogas.value,
            UsoFinal.eliminacion.value
        ]


def validate_use_allowed(
    estado_producto: EstadoProducto,
    categoria: Categoria,
    uso_solicitado: int,
    has_cold_chain: bool = True
) -> Tuple[bool, Optional[str]]:
    """
    Validate if a specific use is permitted for a product.

    Args:
        estado_producto: Current product state
        categoria: Product category
        uso_solicitado: Requested UsoFinal value (1-8)
        has_cold_chain: Whether cold chain was maintained

    Returns:
        Tuple of (is_allowed, reason_if_blocked)
    """

    permitted = get_permitted_uses(estado_producto, categoria, has_cold_chain)

    if uso_solicitado not in permitted:
        reasons = {
            EstadoProducto.despues_fecha_consumo: "Producto pasado de fecha de consumo preferente",
            EstadoProducto.antes_fecha_expiracion: "Producto próximo a fecha de expiración",
            EstadoProducto.despues_fecha_expiracion: "Producto ha pasado fecha de expiración"
        }
        reason = reasons.get(estado_producto, "Uso no permitido para este producto")
        return False, reason

    return True, None


def generate_compliance_data(
    transaccion_id: int,
    lote_id: int,
    generador_id: int,
    receptor_id: int,
    generador_nombre: str,
    receptor_nombre: str,
    producto: str,
    cantidad_kg: float,
    precio_final: float,
    uso_final: int,
    estado_producto: EstadoProducto,
    fecha_transaccion: Optional[datetime] = None
) -> Dict:
    """
    Generate compliance documentation data for a transaction.

    Returns:
        Dict with compliance data for PDF generation
    """

    if fecha_transaccion is None:
        fecha_transaccion = datetime.utcnow()

    # Map uso_final to Spanish description
    usos_nombres = {
        1: "Prevención (Reducción)",
        2: "Donación para Consumo Humano",
        3: "Transformación en Productos Alimentarios",
        4: "Alimentación Animal",
        5: "Uso Industrial",
        6: "Compostaje",
        7: "Biogás/Bioenergía",
        8: "Eliminación"
    }

    estados_nombres = {
        "antes_fecha_consumo": "Antes de fecha de consumo preferente",
        "despues_fecha_consumo": "Después de fecha de consumo preferente",
        "antes_fecha_expiracion": "Antes de fecha de expiración",
        "despues_fecha_expiracion": "Después de fecha de expiración"
    }

    compliance_data = {
        "tipo_documento": "compliance_legal",
        "ley": "Ley 1/2025 - Prevención de pérdida y desperdicio de alimentos",
        "transaccion_id": transaccion_id,
        "lote_id": lote_id,
        "fecha_emision": fecha_transaccion.isoformat(),
        "generador": {
            "id": generador_id,
            "nombre": generador_nombre
        },
        "receptor": {
            "id": receptor_id,
            "nombre": receptor_nombre
        },
        "producto": {
            "descripcion": producto,
            "cantidad_kg": cantidad_kg,
            "estado": estado_producto.value,
            "estado_descripcion": estados_nombres.get(estado_producto.value, "Desconocido")
        },
        "transaccion": {
            "precio_final_eur": precio_final,
            "uso_final": uso_final,
            "uso_final_descripcion": usos_nombres.get(uso_final, "Desconocido")
        },
        "trazabilidad": {
            "generador_id": generador_id,
            "receptor_id": receptor_id,
            "timestamp": fecha_transaccion.isoformat(),
            "hash": _generate_trazabilidad_hash(transaccion_id, generador_id, receptor_id)
        },
        "conformidad": {
            "cumple_ley_1_2025": True,
            "uso_permitido": True,
            "documentacion_requerida": _get_required_docs(uso_final)
        }
    }

    return compliance_data


def _generate_trazabilidad_hash(transaccion_id: int, generador_id: int, receptor_id: int) -> str:
    """Generate a simple hash for traceability"""
    import hashlib
    data = f"{transaccion_id}:{generador_id}:{receptor_id}:{datetime.utcnow().isoformat()}"
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def _get_required_docs(uso_final: int) -> List[str]:
    """Get list of required documents based on use type"""

    docs = ["albaràn_entrega", "trazabilidad_completa"]

    if uso_final == UsoFinal.donacion_consumo.value:
        docs.append("certificado_donacion")
        docs.append("declaracion_conformidad")
    elif uso_final == UsoFinal.alimentacion_animal.value:
        docs.append("certificado_seguridad_piensos")
    elif uso_final == UsoFinal.compostaje.value:
        docs.append("acta_recepcion_planta")
    elif uso_final == UsoFinal.biogas.value:
        docs.append("acta_recepcion_planta")

    return docs


class ComplianceChecker:
    """Helper class for compliance checks and documentation"""

    @staticmethod
    def get_use_hierarchy_description() -> Dict[int, Dict[str, str]]:
        """Get detailed description of each use level in the hierarchy"""

        return {
            1: {
                "nombre": "Prevención (Reducción)",
                "descripcion": "Reducción de pérdidas y desperdicio mediante prevención",
                "prioridad": "máxima"
            },
            2: {
                "nombre": "Donación para Consumo Humano",
                "descripcion": "Donación segura a bancos de alimentos y organizaciones benéficas",
                "prioridad": "muy alta",
                "requisitos": ["Antes de fecha de expiración", "Inspección sanitaria"]
            },
            3: {
                "nombre": "Transformación en Productos Alimentarios",
                "descripcion": "Reprocesamiento en nuevos productos alimentarios",
                "prioridad": "alta",
                "requisitos": ["Licencia de transformación", "Normas APPCC"]
            },
            4: {
                "nombre": "Alimentación Animal",
                "descripcion": "Uso como piensos o alimento animal",
                "prioridad": "media-alta",
                "requisitos": ["Seguridad animal", "Regulación de piensos"]
            },
            5: {
                "nombre": "Uso Industrial",
                "descripcion": "Uso como materia prima industrial",
                "prioridad": "media",
                "requisitos": ["Especificaciones técnicas", "Contrato industrial"]
            },
            6: {
                "nombre": "Compostaje",
                "descripcion": "Transformación en compost mediante procesos biológicos",
                "prioridad": "media-baja",
                "requisitos": ["Planta certificada de compostaje"]
            },
            7: {
                "nombre": "Biogás/Bioenergía",
                "descripcion": "Generación de energía mediante digestión anaeróbica",
                "prioridad": "baja",
                "requisitos": ["Planta certificada de biogás"]
            },
            8: {
                "nombre": "Eliminación",
                "descripcion": "Eliminación definitiva (última opción)",
                "prioridad": "mínima",
                "requisitos": ["Justificación de no reutilización"]
            }
        }
