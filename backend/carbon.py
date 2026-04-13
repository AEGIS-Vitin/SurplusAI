"""
Carbon footprint calculation for food transactions.
Estimates CO2 avoided when food is saved from waste.
"""

from typing import Dict, Tuple, Any
from enum import Enum


class TipoProducto(str, Enum):
    """Product types for CO2 calculation"""
    carnes = "carnes"
    pescados = "pescados"
    lacteos = "lacteos"
    panaderia = "panaderia"
    frutas = "frutas"
    verduras = "verduras"
    prepared = "prepared"
    otros = "otros"


# CO2 footprint data per kg (in kg CO2e)
# Based on lifecycle analysis studies
CO2_FOOTPRINTS = {
    "carnes": 27.0,          # Beef is most carbon-intensive
    "pescados": 12.0,        # Fish/seafood
    "lacteos": 2.5,          # Dairy products
    "panaderia": 1.2,        # Bread/pastry
    "frutas": 0.8,           # Fruits
    "verduras": 0.6,         # Vegetables
    "prepared": 3.5,         # Prepared meals (avg)
    "otros": 2.0              # Others (average)
}


def calculate_co2_avoided(
    cantidad_kg: float,
    categoria: str,
    uso_final: int
) -> Tuple[float, Dict[str, Any]]:
    """
    Calculate CO2 avoided by keeping food out of waste.

    Logic:
    1. Get base CO2 footprint for product category
    2. Multiply by quantity
    3. Adjust based on final use (less credit if going to biogas vs. donation)

    Args:
        cantidad_kg: Quantity in kg
        categoria: Product category
        uso_final: Final use (1-8 from compliance hierarchy)

    Returns:
        Tuple of (co2_avoided_kg, details_dict)
    """

    # Get base CO2 footprint
    footprint = CO2_FOOTPRINTS.get(categoria, 2.0)

    # Base CO2 avoided = footprint * quantity
    co2_base = footprint * cantidad_kg

    # Adjustment factors based on final use
    # Higher-value uses (donation, animal feed) = full credit
    # Lower-value uses (biogas, composting) = partial credit
    uso_factors = {
        1: 1.0,      # Prevención: full credit
        2: 1.0,      # Donación consumo: full credit
        3: 0.95,     # Transformación: nearly full
        4: 0.80,     # Alimentación animal: 80%
        5: 0.70,     # Uso industrial: 70%
        6: 0.60,     # Compostaje: 60%
        7: 0.50,     # Biogás: 50%
        8: 0.30      # Eliminación: minimal credit
    }

    uso_factor = uso_factors.get(uso_final, 0.50)
    co2_adjusted = co2_base * uso_factor

    # Build details dict
    details = {
        "cantidad_kg": cantidad_kg,
        "categoria": categoria,
        "co2_footprint_por_kg": footprint,
        "co2_base": round(co2_base, 2),
        "uso_final": uso_final,
        "uso_factor": uso_factor,
        "co2_evitado": round(co2_adjusted, 2),
        "equivalencias": _calculate_equivalencias(co2_adjusted)
    }

    return round(co2_adjusted, 2), details


def _calculate_equivalencias(co2_kg: float) -> Dict[str, Any]:
    """
    Calculate real-world equivalencies for CO2 amount.

    Shows user the impact in intuitive terms.

    Args:
        co2_kg: CO2 amount in kg

    Returns:
        Dict with various equivalencies
    """

    return {
        "km_coche_gasolina": round(co2_kg / 0.23, 1),  # Average car: 230g CO2/km
        "kWh_electricidad": round(co2_kg / 0.42, 1),   # Average grid: 420g CO2/kWh
        "arboles_plantados_1_ano": round(co2_kg / 20, 1),  # Tree absorbs ~20kg CO2/year
        "viaje_madrid_barcelona_avion": round(co2_kg / 110, 1),  # Flight: 110kg CO2
        "kg_co2": co2_kg
    }


def get_carbon_report(
    transacciones: list
) -> Dict[str, Any]:
    """
    Generate carbon impact report from list of transactions.

    Args:
        transacciones: List of TransaccionDB objects

    Returns:
        Aggregated report dict
    """

    total_co2 = 0.0
    total_kg = 0.0
    por_categoria = {}
    por_uso = {}

    for trans in transacciones:
        if trans.co2_evitado_kg:
            total_co2 += trans.co2_evitado_kg

        total_kg += trans.cantidad_kg

        # Group by category
        # Note: need to fetch lote to get category
        # This is simplified - in real code would join

    equivalencias = _calculate_equivalencias(total_co2)

    return {
        "periodo": "all_time",
        "total_transacciones": len(transacciones),
        "total_kg_salvados": round(total_kg, 1),
        "total_co2_evitado_kg": round(total_co2, 2),
        "equivalencias": equivalencias,
        "impacto_promedio_por_transaccion_kg": round(total_co2 / max(len(transacciones), 1), 2),
        "impacto_promedio_por_kg": round(total_co2 / max(total_kg, 1), 2)
    }


def get_sector_footprints() -> Dict[str, Dict[str, Any]]:
    """
    Return CO2 footprint data for all sectors.

    Useful for educational materials and dashboards.

    Returns:
        Dict mapping category to CO2 kg per kg of product
    """

    return {
        "carnes": {
            "valor": CO2_FOOTPRINTS["carnes"],
            "descripcion": "Carne (principalmente vacuno)",
            "rango": "25-30 kg CO2e/kg"
        },
        "pescados": {
            "valor": CO2_FOOTPRINTS["pescados"],
            "descripcion": "Pescado y mariscos",
            "rango": "10-15 kg CO2e/kg"
        },
        "lacteos": {
            "valor": CO2_FOOTPRINTS["lacteos"],
            "descripcion": "Productos lácteos",
            "rango": "2-3 kg CO2e/kg"
        },
        "panaderia": {
            "valor": CO2_FOOTPRINTS["panaderia"],
            "descripcion": "Pan y productos de panadería",
            "rango": "1-1.5 kg CO2e/kg"
        },
        "frutas": {
            "valor": CO2_FOOTPRINTS["frutas"],
            "descripcion": "Frutas",
            "rango": "0.5-1 kg CO2e/kg"
        },
        "verduras": {
            "valor": CO2_FOOTPRINTS["verduras"],
            "descripcion": "Verduras",
            "rango": "0.3-0.8 kg CO2e/kg"
        },
        "prepared": {
            "valor": CO2_FOOTPRINTS["prepared"],
            "descripcion": "Comidas preparadas",
            "rango": "3-4 kg CO2e/kg"
        },
        "otros": {
            "valor": CO2_FOOTPRINTS["otros"],
            "descripcion": "Otros productos",
            "rango": "1-3 kg CO2e/kg"
        }
    }
