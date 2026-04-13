"""
Dynamic pricing engine for food surplus lots.
Implements automatic price adjustment based on time to expiry and demand.
"""

from datetime import datetime, timedelta
from typing import Tuple
import math


def calculate_dynamic_price(
    precio_base: float,
    fecha_limite: datetime,
    fecha_publicacion: datetime,
    num_bids: int = 0,
    categoria: str = "otros"
) -> float:
    """
    Calculate dynamic price based on:
    1. Days remaining until expiry (time decay)
    2. Number of bids (demand factor)
    3. Product category scarcity

    Formula: precio = precio_base * (dias_restantes / dias_totales) * factor_demanda
    Floor: minimum 10% of base price

    Args:
        precio_base: Starting price in EUR
        fecha_limite: Expiry/best-before date
        fecha_publicacion: Lot publication date
        num_bids: Current number of bids
        categoria: Product category for scarcity adjustment

    Returns:
        Calculated price (minimum 10% of base)

    Raises:
        ValueError: If input values are invalid
    """

    # Validate inputs
    if precio_base < 0:
        raise ValueError("precio_base must be non-negative")
    if num_bids < 0:
        raise ValueError("num_bids must be non-negative")

    now = datetime.utcnow()

    # Ensure fecha_limite and fecha_publicacion are timezone-naive
    if fecha_limite.tzinfo is not None:
        fecha_limite = fecha_limite.replace(tzinfo=None)
    if fecha_publicacion.tzinfo is not None:
        fecha_publicacion = fecha_publicacion.replace(tzinfo=None)

    # If already expired, return minimum price
    if now >= fecha_limite:
        return max(precio_base * 0.10, 0.01)

    # Calculate time decay factor
    dias_restantes = (fecha_limite - now).days + 1
    dias_totales = max((fecha_limite - fecha_publicacion).days, 1)

    # Prevent division by zero
    if dias_totales == 0:
        dias_totales = 1

    tiempo_factor = dias_restantes / dias_totales
    tiempo_factor = max(0.1, min(1.0, tiempo_factor))  # Clamp between 10% and 100%

    # Calculate demand factor based on number of bids
    # More bids = higher price (scarcity effect)
    # 0 bids = 1.0x, 3+ bids = 1.3x
    demanda_factor = 1.0 + (min(num_bids, 5) * 0.06)

    # Category-based scarcity adjustment
    scarcity_factors = {
        "carnes": 1.15,
        "pescados": 1.12,
        "lacteos": 1.10,
        "panaderia": 0.95,
        "frutas": 1.05,
        "verduras": 1.05,
        "prepared": 1.08,
        "otros": 1.0
    }
    scarcity_factor = scarcity_factors.get(categoria, 1.0)

    # Calculate final price
    precio_calculado = precio_base * tiempo_factor * demanda_factor * scarcity_factor

    # Apply floor at 10% of base price
    precio_minimo = precio_base * 0.10
    precio_final = max(precio_calculado, precio_minimo)

    # Round to 2 decimal places
    return round(precio_final, 2)


def get_price_breakdown(
    precio_base: float,
    fecha_limite: datetime,
    fecha_publicacion: datetime,
    num_bids: int = 0,
    categoria: str = "otros"
) -> dict:
    """
    Get detailed breakdown of price calculation factors.
    Useful for frontend display of why the price is what it is.

    Returns:
        Dict with all calculation components
    """

    now = datetime.utcnow()

    if fecha_limite.tzinfo is not None:
        fecha_limite = fecha_limite.replace(tzinfo=None)
    if fecha_publicacion.tzinfo is not None:
        fecha_publicacion = fecha_publicacion.replace(tzinfo=None)

    dias_restantes = max((fecha_limite - now).days + 1, 0)
    dias_totales = max((fecha_limite - fecha_publicacion).days, 1)

    if dias_totales == 0:
        dias_totales = 1

    tiempo_factor = dias_restantes / dias_totales
    tiempo_factor = max(0.1, min(1.0, tiempo_factor))

    demanda_factor = 1.0 + (min(num_bids, 5) * 0.06)

    scarcity_factors = {
        "carnes": 1.15,
        "pescados": 1.12,
        "lacteos": 1.10,
        "panaderia": 0.95,
        "frutas": 1.05,
        "verduras": 1.05,
        "prepared": 1.08,
        "otros": 1.0
    }
    scarcity_factor = scarcity_factors.get(categoria, 1.0)

    precio_final = calculate_dynamic_price(
        precio_base, fecha_limite, fecha_publicacion, num_bids, categoria
    )

    return {
        "precio_base": precio_base,
        "precio_final": precio_final,
        "dias_restantes": dias_restantes,
        "tiempo_factor": round(tiempo_factor, 3),
        "num_bids": num_bids,
        "demanda_factor": round(demanda_factor, 3),
        "categoria": categoria,
        "scarcity_factor": round(scarcity_factor, 3),
        "descuento_porcentaje": round((1 - precio_final / precio_base) * 100, 1) if precio_base > 0 else 0
    }


def suggest_price_for_generator(
    categoria: str,
    cantidad_kg: float,
    tipo_generador: str,
    dias_hasta_expiry: int = 7
) -> float:
    """
    Suggest a base price for generators when creating a new lot.
    Based on typical market prices and product characteristics.

    Args:
        categoria: Product category
        cantidad_kg: Quantity in kg
        tipo_generador: Generator type (retail, industria, horeca, primario)
        dias_hasta_expiry: Days until expiry/best-before

    Returns:
        Suggested base price in EUR per kg

    Raises:
        ValueError: If input values are invalid
    """

    # Validate inputs
    if cantidad_kg <= 0:
        raise ValueError("cantidad_kg must be positive")
    if dias_hasta_expiry <= 0:
        raise ValueError("dias_hasta_expiry must be positive")

    # Base prices per kg by category (wholesale/surplus prices, not retail)
    base_prices = {
        "carnes": 4.50,
        "pescados": 5.00,
        "lacteos": 1.50,
        "panaderia": 0.80,
        "frutas": 0.60,
        "verduras": 0.50,
        "prepared": 2.00,
        "otros": 1.00
    }

    # Type-based discounts (surplus is cheaper than fresh)
    type_discounts = {
        "retail": 0.30,      # 30% of normal wholesale
        "horeca": 0.35,
        "industria": 0.25,
        "primario": 0.20
    }

    base = base_prices.get(categoria, 1.00)
    discount = type_discounts.get(tipo_generador, 0.30)

    suggested_price = base * discount

    # Bulk discount for large quantities
    if cantidad_kg > 500:
        suggested_price *= 0.90
    elif cantidad_kg > 200:
        suggested_price *= 0.95

    return round(suggested_price, 2)
