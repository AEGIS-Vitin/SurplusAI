#!/usr/bin/env python3
"""
SurplusAI — Demo seed data generator (v2, "live marketplace")

Populates a SurplusAI instance (local or Railway prod) with a *plausible*
Spanish marketplace state: ~45 generadores, ~100 receptores, ~220 lots,
~320 bids, ~150 transactions. Uses the public REST API, so it works
against any deployment where /auth, /generadores, /receptores, /lots,
/bids, /transactions are exposed — no DB credentials required.

Safe to re-run: the script is idempotent at the participant level
(handles 400 "CIF ya registrado" quietly and continues; it also
short-circuits if /stats already reports healthy volume).

Usage:
    python3 scripts/seed_demo_data.py                       # → surplusai.es
    python3 scripts/seed_demo_data.py --base-url http://localhost:8000
    python3 scripts/seed_demo_data.py --generators 60 --receptors 120 \\
                                     --lots 280 --bids 380 --tx 180

Requires: httpx, Faker
    pip install httpx Faker --break-system-packages
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

try:
    import httpx
except ImportError:  # pragma: no cover
    print("Falta httpx. Instala con: pip install httpx --break-system-packages")
    sys.exit(1)

try:
    from faker import Faker
except ImportError:  # pragma: no cover
    print("Falta Faker. Instala con: pip install Faker --break-system-packages")
    sys.exit(1)


DEFAULT_BASE_URL = os.getenv("SURPLUSAI_BASE_URL", "https://surplusai.es")
DEMO_USER_EMAIL = "seed-bot@surplusai.es"
DEMO_USER_PASSWORD = "SeedBot2026!Demo"
DEMO_EMPRESA_ID = 901
DEMO_EMPRESA_NOMBRE = "SurplusAI Seed Bot"

fake = Faker("es_ES")
Faker.seed(42)
random.seed(42)


# -----------------------------------------------------------------------------
# Reference pools (Spanish food chain): realistic names, regions, coords
# -----------------------------------------------------------------------------

CIUDADES: List[Tuple[str, str, float, float]] = [
    ("Madrid", "Madrid", 40.4168, -3.7038),
    ("Barcelona", "Cataluña", 41.3874, 2.1686),
    ("Valencia", "Comunitat Valenciana", 39.4699, -0.3763),
    ("Sevilla", "Andalucía", 37.3891, -5.9845),
    ("Bilbao", "País Vasco", 43.2630, -2.9350),
    ("Zaragoza", "Aragón", 41.6488, -0.8891),
    ("Málaga", "Andalucía", 36.7213, -4.4214),
    ("Murcia", "Región de Murcia", 37.9922, -1.1307),
    ("Palma", "Illes Balears", 39.5696, 2.6502),
    ("Las Palmas", "Canarias", 28.1235, -15.4363),
    ("Alicante", "Comunitat Valenciana", 38.3452, -0.4810),
    ("Córdoba", "Andalucía", 37.8882, -4.7794),
    ("Valladolid", "Castilla y León", 41.6523, -4.7245),
    ("Vigo", "Galicia", 42.2406, -8.7207),
    ("Granada", "Andalucía", 37.1773, -3.5986),
    ("Pamplona", "Navarra", 42.8125, -1.6458),
    ("Santander", "Cantabria", 43.4623, -3.8099),
    ("Toledo", "Castilla-La Mancha", 39.8628, -4.0273),
    ("Logroño", "La Rioja", 42.4627, -2.4449),
    ("A Coruña", "Galicia", 43.3623, -8.4115),
]


@dataclass
class GeneratorTemplate:
    nombre_raiz: str
    tipo: str
    plan: str


GEN_TEMPLATES: List[GeneratorTemplate] = [
    # Retail grande
    GeneratorTemplate("Mercadona Centro Logístico", "retail", "premium"),
    GeneratorTemplate("Carrefour Hipermercado", "retail", "premium"),
    GeneratorTemplate("DIA Supermercado", "retail", "profesional"),
    GeneratorTemplate("Alcampo Centro", "retail", "premium"),
    GeneratorTemplate("Eroski City", "retail", "profesional"),
    GeneratorTemplate("Lidl Tienda", "retail", "profesional"),
    GeneratorTemplate("Aldi Express", "retail", "profesional"),
    GeneratorTemplate("Consum Cooperativa", "retail", "profesional"),
    GeneratorTemplate("Condis Supermercats", "retail", "basico"),
    GeneratorTemplate("Supercor Exprés", "retail", "profesional"),
    # Industria agroalimentaria
    GeneratorTemplate("Campofrío Food Group", "industria", "premium"),
    GeneratorTemplate("Casa Tarradellas Planta", "industria", "premium"),
    GeneratorTemplate("Gullón Fábrica", "industria", "profesional"),
    GeneratorTemplate("Calvo Conservas", "industria", "profesional"),
    GeneratorTemplate("García Baquero Quesería", "industria", "profesional"),
    GeneratorTemplate("Central Lechera Asturiana", "industria", "premium"),
    GeneratorTemplate("Pescanova Planta", "industria", "profesional"),
    GeneratorTemplate("Ebro Foods Molinería", "industria", "profesional"),
    GeneratorTemplate("Nutrexpa Producción", "industria", "basico"),
    GeneratorTemplate("Panrico Panadería Industrial", "industria", "profesional"),
    # HORECA
    GeneratorTemplate("NH Hotels Cocina Central", "horeca", "premium"),
    GeneratorTemplate("Meliá Hotels Restauración", "horeca", "premium"),
    GeneratorTemplate("Riu Hotels Cocina", "horeca", "profesional"),
    GeneratorTemplate("Compass Group Catering", "horeca", "premium"),
    GeneratorTemplate("Eurest Colectividades", "horeca", "profesional"),
    GeneratorTemplate("Serunión Catering", "horeca", "profesional"),
    GeneratorTemplate("Aramark Comedores", "horeca", "profesional"),
    GeneratorTemplate("Sodexo Cocina Hospitalaria", "horeca", "premium"),
    GeneratorTemplate("VIPS Restaurante", "horeca", "basico"),
    GeneratorTemplate("Rodilla Sándwich", "horeca", "basico"),
    GeneratorTemplate("Granier Panadería", "horeca", "basico"),
    GeneratorTemplate("Panishop Obrador Central", "horeca", "profesional"),
    GeneratorTemplate("La Boutique del Pan", "horeca", "basico"),
    # Primario / cooperativas
    GeneratorTemplate("Cooperativa Agraria Ibérica", "primario", "profesional"),
    GeneratorTemplate("Agrícola Regional Cooperativa", "primario", "profesional"),
    GeneratorTemplate("Hortofrutícola Levante SAT", "primario", "basico"),
    GeneratorTemplate("Cítricos del Sur Cooperativa", "primario", "profesional"),
    GeneratorTemplate("Frutas Selectas de Aragón", "primario", "basico"),
    GeneratorTemplate("Viveros Huerta Murciana", "primario", "basico"),
    GeneratorTemplate("Pesca Fresca del Cantábrico SL", "primario", "profesional"),
    GeneratorTemplate("Ganadería La Dehesa", "primario", "profesional"),
    GeneratorTemplate("Lácteos Valle del Norte", "primario", "premium"),
    GeneratorTemplate("Aceitunas y Aceites del Sur", "primario", "profesional"),
    GeneratorTemplate("Bodega Agraria Castilla", "primario", "basico"),
    GeneratorTemplate("Mercado Central Mayorista", "retail", "profesional"),
    GeneratorTemplate("Mercabarna Operador", "retail", "premium"),
]


@dataclass
class ReceptorTemplate:
    nombre_raiz: str
    tipo: str  # 'banco_alimentos' | 'transformador' | 'piensos' | 'compost' | 'biogas'
    cap_min: float
    cap_max: float
    categorias: List[str]
    licencias: List[str]


REC_TEMPLATES: List[ReceptorTemplate] = [
    ReceptorTemplate(
        "Banco de Alimentos", "banco_alimentos", 5000, 30000,
        ["frutas", "verduras", "lacteos", "panaderia", "prepared"],
        ["ONG_CERTIFICADA", "SANIDAD_ALIMENTARIA"],
    ),
    ReceptorTemplate(
        "Cáritas Diocesana", "banco_alimentos", 500, 5000,
        ["frutas", "verduras", "lacteos", "panaderia"],
        ["ONG_CERTIFICADA"],
    ),
    ReceptorTemplate(
        "Cruz Roja Delegación", "banco_alimentos", 1000, 8000,
        ["frutas", "verduras", "lacteos", "carnes", "prepared"],
        ["ONG_CERTIFICADA", "TRANSPORTE_REFRIGERADO"],
    ),
    ReceptorTemplate(
        "Cocinas Solidarias", "banco_alimentos", 200, 2000,
        ["frutas", "verduras", "carnes", "prepared", "panaderia"],
        ["COMEDOR_SOCIAL", "SANIDAD_ALIMENTARIA"],
    ),
    ReceptorTemplate(
        "Fundación Madrina Comedor", "banco_alimentos", 300, 3000,
        ["frutas", "verduras", "lacteos", "panaderia", "prepared"],
        ["ONG_CERTIFICADA"],
    ),
    ReceptorTemplate(
        "Asociación Nueva Vida", "banco_alimentos", 150, 1500,
        ["frutas", "verduras", "panaderia"],
        ["ONG_CERTIFICADA"],
    ),
    ReceptorTemplate(
        "Transformadora Alimentaria", "transformador", 3000, 25000,
        ["frutas", "verduras", "prepared"],
        ["ISO_22000", "APPCC", "IFS_FOOD"],
    ),
    ReceptorTemplate(
        "Zumos y Conservas Industria", "transformador", 2000, 15000,
        ["frutas", "verduras"],
        ["APPCC", "REGISTRO_INDUSTRIAL"],
    ),
    ReceptorTemplate(
        "Ganadería Vacuno", "piensos", 2000, 20000,
        ["panaderia", "verduras", "frutas", "otros"],
        ["REGISTRO_PIENSOS", "SANITARIO_ANIMAL"],
    ),
    ReceptorTemplate(
        "Piensos y Subproductos", "piensos", 5000, 40000,
        ["panaderia", "carnes", "pescados", "otros"],
        ["REGISTRO_PIENSOS", "SANDACH"],
    ),
    ReceptorTemplate(
        "Granja Porcina Cooperativa", "piensos", 3000, 15000,
        ["panaderia", "verduras", "frutas", "otros"],
        ["REGISTRO_PIENSOS"],
    ),
    ReceptorTemplate(
        "Compost Plus Planta", "compost", 10000, 80000,
        ["frutas", "verduras", "otros"],
        ["AMBIENTAL", "GESTOR_RESIDUOS"],
    ),
    ReceptorTemplate(
        "EcoCompost Agrícola", "compost", 5000, 30000,
        ["frutas", "verduras", "otros"],
        ["AMBIENTAL"],
    ),
    ReceptorTemplate(
        "Biogás Renovable", "biogas", 15000, 100000,
        ["carnes", "pescados", "panaderia", "prepared", "otros"],
        ["ENERGIA_RENOVABLE", "GESTOR_RESIDUOS"],
    ),
    ReceptorTemplate(
        "BioEnergía Agroindustrial", "biogas", 8000, 60000,
        ["frutas", "verduras", "otros"],
        ["ENERGIA_RENOVABLE"],
    ),
]


# -----------------------------------------------------------------------------
# P0.3 — SurplusAI pricing & outcome distributions
# -----------------------------------------------------------------------------
#
# Per VERDICT_BUSINESS_MODEL.md we charge service_fee + logistics_fee +
# biomass_revenue; the food itself is mostly free (donation) or symbolic.
# We encode the realistic price distribution here so the seed reflects what
# the real marketplace looks like.
#
# Outcome distribution by category (VERDICT P0 section):
#   frutas/verduras B-grade: 40% ONG, 20% food_bank, 15% cattle_feed, 15% compost, 10% biomass_biogas
#   carnes/pescados: 50% food_bank, 30% biomass_biogas, 20% compost (NO cattle_feed por SANDACH)
#   lacteos: 50% food_bank, 30% biomass_biogas, 20% compost
#   panaderia: 40% ONG, 30% cattle_feed (pigs, farm animals), 20% compost, 10% biomass_biogas
#   prepared: 60% food_bank (comedor social 24h), 30% biomass_biogas, 10% compost

OUTCOME_DIST_BY_CATEGORY: Dict[str, List[Tuple[str, float]]] = {
    "frutas": [
        ("donated_ong", 0.40), ("food_bank", 0.20), ("cattle_feed", 0.15),
        ("compost", 0.15), ("biomass_biogas", 0.10),
    ],
    "verduras": [
        ("donated_ong", 0.40), ("food_bank", 0.20), ("cattle_feed", 0.15),
        ("compost", 0.15), ("biomass_biogas", 0.10),
    ],
    "carnes": [
        ("food_bank", 0.50), ("biomass_biogas", 0.30), ("compost", 0.20),
    ],
    "pescados": [
        ("food_bank", 0.50), ("biomass_biogas", 0.30), ("compost", 0.20),
    ],
    "lacteos": [
        ("food_bank", 0.50), ("biomass_biogas", 0.30), ("compost", 0.20),
    ],
    "panaderia": [
        ("donated_ong", 0.40), ("cattle_feed", 0.30), ("compost", 0.20), ("biomass_biogas", 0.10),
    ],
    "prepared": [
        ("food_bank", 0.60), ("biomass_biogas", 0.30), ("compost", 0.10),
    ],
    "otros": [
        ("food_bank", 0.40), ("cattle_feed", 0.25), ("biomass_biogas", 0.20), ("compost", 0.15),
    ],
}

# Outcome → receptor tipo (used to filter bid candidates)
OUTCOME_TO_TIPO: Dict[str, str] = {
    "donated_ong": "banco_alimentos",
    "food_bank": "banco_alimentos",
    "cattle_feed": "piensos",
    "biomass_biogas": "biogas",
    "energy_biogas": "biogas",
    "compost": "compost",
}

# Outcome → uso_final (UsoFinal enum int)
OUTCOME_TO_USO: Dict[str, int] = {
    "donated_ong": 2,
    "food_bank": 2,
    "cattle_feed": 4,
    "biomass_biogas": 7,
    "energy_biogas": 7,
    "compost": 6,
}

# Biomass revenue per tonne the plant pays SurplusAI (v2 contract model)
BIOMASS_REVENUE_PER_TONNE_EUR: Dict[str, float] = {
    "biomass_biogas": 55.0,
    "energy_biogas": 45.0,
    "compost": 30.0,
    "cattle_feed": 40.0,
    "food_bank": 0.0,
    "donated_ong": 0.0,
}

# Food price distribution:
#  40% free (donation)
#  30% symbolic 0.10–0.50 €/kg
#  20% discount   0.50–2 €/kg
#  10% premium    2–8 €/kg (fresh meat, fish)
def sample_food_price(cat: str) -> float:
    r = random.random()
    if r < 0.40:
        return 0.0
    if r < 0.70:
        return round(random.uniform(0.10, 0.50), 2)
    if r < 0.90:
        return round(random.uniform(0.50, 2.00), 2)
    # Premium: only meaningful for carnes/pescados; cap the rest
    if cat in ("carnes", "pescados"):
        return round(random.uniform(2.00, 8.00), 2)
    return round(random.uniform(1.00, 2.50), 2)


def pick_outcome(cat: str) -> str:
    dist = OUTCOME_DIST_BY_CATEGORY.get(cat, OUTCOME_DIST_BY_CATEGORY["otros"])
    r = random.random()
    acc = 0.0
    for outcome, w in dist:
        acc += w
        if r <= acc:
            return outcome
    return dist[-1][0]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Light-weight haversine so we don't pull geopy into the seed script."""
    import math
    R = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(a)))


def service_fee_for_weight(kg: float) -> float:
    for max_kg, fee in [(100, 20.0), (500, 25.0), (1500, 30.0), (5000, 40.0), (float("inf"), 80.0)]:
        if kg < max_kg:
            return fee
    return 80.0


def logistics_fee_for_distance(dist_km: float) -> float:
    return round(max(dist_km * 0.25, 25.0), 2)


def biomass_revenue_for_outcome(outcome: str, kg: float) -> float:
    return round(BIOMASS_REVENUE_PER_TONNE_EUR.get(outcome, 0.0) * (kg / 1000.0), 2)


# (descripcion base, categoria, (kg_min, kg_max), (precio_base_min, precio_base_max €/kg))
# NOTE: precio ranges here are now legacy — pricing is replaced at lot-build
# time by sample_food_price(cat). Kept for backwards compatibility of the tuple shape.
PRODUCTO_CATALOG: List[Tuple[str, str, Tuple[float, float], Tuple[float, float]]] = [
    ("Manzana Golden B-grade próxima caducidad", "frutas", (500, 2500), (0.25, 0.55)),
    ("Naranja Valencia Late calibre pequeño", "frutas", (800, 3500), (0.18, 0.42)),
    ("Plátano de Canarias desparejado", "frutas", (300, 1800), (0.35, 0.75)),
    ("Pera Conference calibre irregular", "frutas", (400, 2000), (0.30, 0.65)),
    ("Fresa Huelva fecha corta 2 días", "frutas", (100, 800), (0.90, 1.60)),
    ("Kiwi Hayward sobremaduro apto zumo", "frutas", (200, 1500), (0.40, 0.80)),
    ("Uva Aledo excedente cooperativa", "frutas", (500, 2000), (0.45, 0.95)),
    ("Melón Piel de Sapo tamaño grande", "frutas", (800, 3000), (0.28, 0.55)),
    ("Lechuga Iceberg fecha consumo hoy", "verduras", (150, 900), (0.25, 0.55)),
    ("Tomate rama 1ª categoría excedente", "verduras", (400, 2500), (0.35, 0.95)),
    ("Patata nueva calibre pequeño", "verduras", (1000, 5000), (0.18, 0.38)),
    ("Pimiento California rojo desclasificado", "verduras", (300, 1500), (0.40, 0.85)),
    ("Calabacín extra tamaño XL", "verduras", (400, 2000), (0.22, 0.48)),
    ("Zanahoria cooperativa ecológica", "verduras", (500, 2500), (0.30, 0.65)),
    ("Cebolla dulce Figueres excedente", "verduras", (600, 3000), (0.25, 0.55)),
    ("Espinaca fresca fecha corta 2 días", "verduras", (100, 600), (0.90, 1.80)),
    ("Yogur natural próxima caducidad 4 días", "lacteos", (150, 1200), (0.75, 1.85)),
    ("Leche UHT excedente producción", "lacteos", (300, 2500), (0.55, 1.05)),
    ("Queso fresco batch antes FCP 3 días", "lacteos", (80, 500), (3.80, 6.50)),
    ("Mantequilla en tarrina fin de lote", "lacteos", (50, 400), (4.20, 7.80)),
    ("Nata para cocinar fecha corta", "lacteos", (60, 350), (2.10, 3.80)),
    ("Solomillo vacuno pasada FPC 2 días", "carnes", (40, 220), (11.50, 17.50)),
    ("Pechuga pollo bandeja FPC hoy", "carnes", (100, 600), (3.80, 6.20)),
    ("Costilla cerdo congelada descatalogada", "carnes", (200, 900), (3.20, 5.40)),
    ("Ternera picada 20% FPC mañana", "carnes", (60, 350), (5.40, 8.20)),
    ("Salchichas pollo lote excedente", "carnes", (80, 400), (2.80, 4.60)),
    ("Merluza congelada IQF fin de temporada", "pescados", (150, 900), (4.80, 8.20)),
    ("Salmón ahumado FPC 3 días", "pescados", (30, 180), (11.20, 17.80)),
    ("Sardina fresca lonja excedente", "pescados", (100, 500), (2.40, 4.50)),
    ("Calamar potón congelado", "pescados", (80, 450), (3.80, 6.20)),
    ("Pan rústico 500g sobrante día", "panaderia", (200, 1500), (0.45, 1.10)),
    ("Baguette integral día anterior", "panaderia", (150, 900), (0.35, 0.90)),
    ("Cruasanes mantequilla fin jornada", "panaderia", (80, 400), (1.10, 2.20)),
    ("Magdalenas artesanas descatalogadas", "panaderia", (60, 350), (1.40, 2.80)),
    ("Bollería mixta obrador central", "panaderia", (100, 600), (0.90, 1.80)),
    ("Ensalada preparada bolsa FPC mañana", "prepared", (80, 400), (1.80, 3.40)),
    ("Sándwich triangular envasado FPC hoy", "prepared", (50, 350), (1.40, 2.60)),
    ("Lasaña 4 raciones pasada FPC 1 día", "prepared", (60, 320), (3.20, 5.80)),
    ("Ensaladilla rusa tarrina excedente", "prepared", (40, 280), (2.40, 4.20)),
    ("Gazpacho brick 1L fecha corta", "prepared", (100, 600), (1.10, 2.40)),
    ("Arroz 1kg saco maltratado en logística", "otros", (300, 2000), (0.55, 1.20)),
    ("Pasta macarrón sobrante producción", "otros", (200, 1200), (0.70, 1.50)),
    ("Aceite de oliva virgen extra lote B", "otros", (50, 250), (3.80, 6.20)),
    ("Conservas atún aceite fin campaña", "otros", (80, 400), (1.50, 3.20)),
    ("Legumbres envasadas etiquetado antiguo", "otros", (100, 600), (0.90, 1.80)),
]

TEMP_CONSERV_POR_CAT = {
    "frutas": (2, 10),
    "verduras": (2, 8),
    "lacteos": (2, 6),
    "carnes": (0, 4),
    "pescados": (-1, 2),
    "panaderia": (15, 22),
    "prepared": (2, 6),
    "otros": (15, 22),
}

# Mensaje-motivo por uso previsto (1..8)
USO_MENSAJE = {
    2: [
        "Distribución a familias en exclusión social",
        "Reparto en comedor popular",
        "Banco de alimentos Comunidad",
        "Kit alimentario emergencia social",
    ],
    3: [
        "Transformación en zumo natural premium",
        "Procesado a conserva y mermelada",
        "Elaboración de 4ª gama",
        "Cocción para precocinado congelado",
    ],
    4: [
        "Pienso premium ganado vacuno",
        "Alimentación cerdo ibérico fase engorde",
        "Subproducto pienso avícola",
    ],
    6: [
        "Compostaje ecológico certificado",
        "Enmienda orgánica agricultura ecológica",
    ],
    7: [
        "Generación biogás renovable",
        "Valorización energética digestor",
    ],
}


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def cif_sintetico(letra: str, provincia_digito: str) -> str:
    """Genera un CIF sintético con letra + 8 dígitos (formato válido, no checksum)."""
    numero = f"{provincia_digito}{random.randint(1_000_000, 9_999_999)}"
    return f"{letra}{numero}"


def tel_es() -> str:
    prefix = random.choice(["6", "7", "9"])
    rest = "".join(random.choice("0123456789") for _ in range(8))
    return f"+34{prefix}{rest[:8]}"


def jitter(lat: float, lon: float, km: float = 8.0) -> Tuple[float, float]:
    dlat = random.uniform(-km, km) / 111.0
    dlon = random.uniform(-km, km) / 85.0
    return round(lat + dlat, 5), round(lon + dlon, 5)


def future_iso(days_ahead: Tuple[int, int]) -> str:
    d_min, d_max = days_ahead
    total_hours = random.randint(max(1, d_min * 24), max(2, d_max * 24))
    target = datetime.utcnow() + timedelta(hours=total_hours)
    return target.replace(microsecond=0).isoformat()


def email_empresa(nombre: str, idx: int = 0) -> str:
    slug = "".join(c for c in nombre.lower().replace(" ", "") if c.isalnum())[:14]
    dominios = ["demo.es", "corp-demo.es", "grp-demo.es", "es-demo.com"]
    return f"excedentes.{slug}{idx % 1000}@{dominios[idx % len(dominios)]}"


# -----------------------------------------------------------------------------
# Client with retry + auth
# -----------------------------------------------------------------------------

class SurplusAPI:
    def __init__(self, base_url: str, token: Optional[str] = None):
        # limits+transport tuned for threaded fan-out
        transport = httpx.HTTPTransport(retries=2)
        limits = httpx.Limits(max_connections=40, max_keepalive_connections=20)
        self.client = httpx.Client(
            base_url=base_url, timeout=30, transport=transport, limits=limits
        )
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.client.get(path, headers=self._headers(), **kwargs)

    def post(self, path: str, json_body: Any) -> httpx.Response:
        return self.client.post(path, json=json_body, headers=self._headers())

    def ensure_user_and_login(self) -> None:
        reg_body = {
            "email": DEMO_USER_EMAIL,
            "password": DEMO_USER_PASSWORD,
            "empresa_id": DEMO_EMPRESA_ID,
            "nombre_empresa": DEMO_EMPRESA_NOMBRE,
            "rol": "admin",
        }
        r = self.client.post("/auth/register", json=reg_body)
        if r.status_code not in (200, 201, 400, 409):
            print(f"   ⚠️  Register unexpected status {r.status_code}: {r.text[:160]}")

        r = self.client.post(
            "/auth/login",
            json={"email": DEMO_USER_EMAIL, "password": DEMO_USER_PASSWORD},
        )
        r.raise_for_status()
        self.token = r.json()["access_token"]
        print(f"   🔑 Token OK ({len(self.token)} chars)")


# -----------------------------------------------------------------------------
# Builders
# -----------------------------------------------------------------------------

def build_generator_payload(i: int) -> Dict[str, Any]:
    tpl = random.choice(GEN_TEMPLATES)
    ciudad, _region, lat, lon = random.choice(CIUDADES)
    nombre = f"{tpl.nombre_raiz} {ciudad}"
    letra = random.choice(["A", "B", "F"])
    prov_digit = random.choice("0123456789")
    cif = cif_sintetico(letra, prov_digit)
    glat, glon = jitter(lat, lon, km=12)
    direccion = f"{fake.street_address()}, {random.randint(1000, 52000)} {ciudad}"
    return {
        "nombre": nombre[:240],
        "tipo": tpl.tipo,
        "cif": cif,
        "direccion": direccion[:480],
        "ubicacion_lat": glat,
        "ubicacion_lon": glon,
        "contacto_email": email_empresa(nombre, i),
        "contacto_telefono": tel_es(),
        "plan_suscripcion": tpl.plan,
    }


def build_receptor_payload(i: int) -> Dict[str, Any]:
    tpl = random.choice(REC_TEMPLATES)
    ciudad, _region, lat, lon = random.choice(CIUDADES)
    nombre = f"{tpl.nombre_raiz} {ciudad}"
    letra = "G" if tpl.tipo == "banco_alimentos" else random.choice(["G", "B", "F"])
    cif = cif_sintetico(letra, random.choice("0123456789"))
    glat, glon = jitter(lat, lon, km=15)
    cats_seleccionadas = random.sample(
        tpl.categorias,
        k=min(len(tpl.categorias), random.randint(2, len(tpl.categorias))),
    )
    return {
        "nombre": nombre[:240],
        "tipo": tpl.tipo,
        "cif": cif,
        "direccion": f"{fake.street_address()}, {random.randint(1000, 52000)} {ciudad}"[:480],
        "ubicacion_lat": glat,
        "ubicacion_lon": glon,
        "capacidad_kg_dia": round(random.uniform(tpl.cap_min, tpl.cap_max), 1),
        "categorias_interes": cats_seleccionadas,
        "licencias": tpl.licencias,
    }


def build_lot_payload(generadores: List[Dict[str, Any]]) -> Dict[str, Any]:
    g = random.choice(generadores)
    prod_base, cat, (kg_min, kg_max), _legacy_prices = random.choice(PRODUCTO_CATALOG)
    temp_min, temp_max = TEMP_CONSERV_POR_CAT[cat]
    days_range = (1, 10) if cat not in ("carnes", "pescados", "prepared") else (1, 4)
    # jitter within 1.5km of the generator coords — this is what gives us
    # real GPS for /lots/nearby. The generators themselves were created with
    # a jitter around one of the CIUDADES, which are real coordinates for
    # Madrid/BCN/Valencia/Sevilla/Bilbao/Zaragoza/etc.
    glat, glon = jitter(g["ubicacion_lat"], g["ubicacion_lon"], km=1.5)
    fecha_limite = future_iso(days_range)
    codigo = f"LOT-{cat[:3].upper()}-{random.randint(100, 9999)}"
    # Food price: donation-heavy distribution (VERDICT P0.3).
    # API requires precio_base > 0, so we use 0.01 as the "free" marker.
    price = sample_food_price(cat)
    if price <= 0:
        price = 0.01
    return {
        "generador_id": g["id"],
        "producto": prod_base,
        "categoria": cat,
        "cantidad_kg": round(random.uniform(kg_min, kg_max), 1),
        "ubicacion_lat": glat,
        "ubicacion_lon": glon,
        "fecha_limite": fecha_limite,
        "precio_base": price,
        "temperatura_conservacion": round(random.uniform(temp_min, temp_max), 1),
        "lote_origen": codigo,
    }


def pick_uso_for_lot(lote: Dict[str, Any]) -> int:
    cat = lote["categoria"]
    candidates = [
        (2, 0.42),  # donación consumo humano
        (3, 0.18),  # transformación
        (4, 0.16),  # alim animal
        (6, 0.08),  # compostaje
        (7, 0.06),  # biogás
    ]
    if cat in ("carnes", "pescados") and random.random() < 0.4:
        candidates = [(4, 0.45), (7, 0.25), (2, 0.20), (3, 0.10)]
    if cat == "panaderia":
        candidates = [(2, 0.40), (4, 0.30), (6, 0.15), (3, 0.15)]

    r = random.random()
    acc = 0.0
    for uso, w in candidates:
        acc += w
        if r <= acc:
            return uso
    return 2


def build_bid_payload(lote: Dict[str, Any], receptores: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pick a bid that respects the P0.3 outcome distribution.

    First decide the *outcome* the lot should end in (based on category),
    then pick a receptor of the matching tipo. This way the transaction
    distribution matches what we'd expect in the real marketplace instead
    of whatever the legacy Dutch-auction scoring produced.
    """
    cat = lote["categoria"]
    outcome = pick_outcome(cat)
    wanted_tipo = OUTCOME_TO_TIPO[outcome]

    # First try to find receptors matching BOTH the outcome tipo AND the category.
    candidatos = [
        r for r in receptores
        if r.get("tipo") == wanted_tipo
        and cat in (r.get("categorias_interes") or [])
    ]
    if not candidatos:
        # Fallback: any receptor of the wanted tipo, or any receptor accepting
        # the category (we'd rather place the lot than fail).
        candidatos = [r for r in receptores if r.get("tipo") == wanted_tipo]
    if not candidatos:
        candidatos = [r for r in receptores if cat in (r.get("categorias_interes") or [])]
    if not candidatos:
        return None
    receptor = random.choice(candidatos)

    # Bid price tracks the food price (not the SurplusAI fee); for donations
    # it can be 0. For non-donations we keep it in a ±10% band of the lot price.
    if outcome in ("donated_ong", "food_bank"):
        precio_oferta = max(0.01, round(lote["precio_base"] * random.uniform(0.5, 1.0), 2))
    else:
        factor = random.uniform(0.70, 1.10)
        precio_oferta = round(max(0.01, lote["precio_base"] * factor), 2)

    uso = OUTCOME_TO_USO.get(outcome, pick_uso_for_lot(lote))
    mensaje = random.choice(USO_MENSAJE.get(uso, ["Consulta estándar"]))
    return {
        "lote_id": lote["id"],
        "receptor_id": receptor["id"],
        "receptor_tipo": receptor.get("tipo"),
        "receptor_lat": receptor.get("ubicacion_lat"),
        "receptor_lon": receptor.get("ubicacion_lon"),
        "precio_oferta": precio_oferta,
        "uso_previsto": uso,
        "mensaje": mensaje,
        "_outcome": outcome,  # private annotation used by build_tx_payload
    }


def build_tx_payload(lote: Dict[str, Any], puja: Dict[str, Any]) -> Dict[str, Any]:
    frac = 1.0 if random.random() < 0.75 else random.uniform(0.3, 0.95)
    cantidad = round(lote["cantidad_kg"] * frac, 1)
    # P0.3 — include the full SurplusAI revenue split so the seed reflects
    # how the real marketplace invoices.
    outcome = puja.get("_outcome", "biomass_biogas")
    r_lat = puja.get("receptor_lat")
    r_lon = puja.get("receptor_lon")
    l_lat = lote.get("ubicacion_lat")
    l_lon = lote.get("ubicacion_lon")
    if r_lat is not None and r_lon is not None and l_lat is not None and l_lon is not None:
        distance_km = haversine_km(l_lat, l_lon, r_lat, r_lon)
    else:
        distance_km = 50.0  # conservative fallback
    logistics_fee = logistics_fee_for_distance(distance_km)
    service_fee = service_fee_for_weight(cantidad)
    biomass_rev = biomass_revenue_for_outcome(outcome, cantidad)
    return {
        "lote_id": lote["id"],
        "puja_id": puja["id"],
        "cantidad_kg": cantidad,
        "precio_final": puja["precio_oferta"],
        "uso_final": puja["uso_previsto"],
        "distance_km": round(distance_km, 2),
        "service_fee_eur": service_fee,
        "logistics_fee_eur": logistics_fee,
        "biomass_revenue_eur": biomass_rev,
        "outcome": outcome,
    }


# -----------------------------------------------------------------------------
# Main seed flow
# -----------------------------------------------------------------------------

def seed(
    base_url: str,
    n_generators: int,
    n_receptors: int,
    n_lots: int,
    n_bids: int,
    n_tx: int,
    force: bool,
) -> None:
    print(f"🌱 SurplusAI seed → {base_url}")
    print("=" * 60)
    api = SurplusAPI(base_url)

    r = api.get("/stats")
    r.raise_for_status()
    stats_before = r.json()
    print(
        f"📊 Before: gens={stats_before['num_generadores']} "
        f"recs={stats_before['num_receptores']} "
        f"tx={stats_before['total_transactions']} "
        f"€{stats_before['money_saved']:.0f}"
    )

    if not force and stats_before.get("total_transactions", 0) >= 100:
        print("✅ Ya hay >= 100 transacciones; seed ya corrido. Usa --force para ampliar.")
        return

    print("\n🔐 Login seed-bot...")
    api.ensure_user_and_login()

    print(f"\n📦 Creando ~{n_generators} generadores (paralelo)...")
    created_gens: List[Dict[str, Any]] = []

    def _post_gen(idx: int) -> Optional[Dict[str, Any]]:
        for _try in range(3):
            payload = build_generator_payload(idx + _try * 1000)
            r = api.post("/generadores", payload)
            if r.status_code in (200, 201):
                return r.json()
            if r.status_code == 400 and "CIF" in r.text:
                continue
            return None
        return None

    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(_post_gen, i) for i in range(n_generators)]
        for f in as_completed(futs):
            res = f.result()
            if res:
                created_gens.append(res)
    print(f"   ✅ {len(created_gens)} generadores")

    print(f"\n🏭 Creando ~{n_receptors} receptores (paralelo)...")
    created_recs: List[Dict[str, Any]] = []

    def _post_rec(idx: int) -> Optional[Dict[str, Any]]:
        for _try in range(3):
            payload = build_receptor_payload(idx + _try * 1000)
            r = api.post("/receptores", payload)
            if r.status_code in (200, 201):
                data = r.json()
                data["categorias_interes"] = payload["categorias_interes"]
                # Ensure downstream builders can filter by tipo and compute distance
                # without an extra round-trip.
                data.setdefault("tipo", payload["tipo"])
                data.setdefault("ubicacion_lat", payload["ubicacion_lat"])
                data.setdefault("ubicacion_lon", payload["ubicacion_lon"])
                return data
            if r.status_code == 400 and "CIF" in r.text:
                continue
            return None
        return None

    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(_post_rec, i) for i in range(n_receptors)]
        for f in as_completed(futs):
            res = f.result()
            if res:
                created_recs.append(res)
    print(f"   ✅ {len(created_recs)} receptores")

    if not created_gens or not created_recs:
        print("⛔ Sin participantes mínimos, abortando.")
        return

    print(f"\n📋 Creando ~{n_lots} lotes (paralelo)...")
    created_lots: List[Dict[str, Any]] = []

    def _post_lot(_i: int) -> Optional[Dict[str, Any]]:
        payload = build_lot_payload(created_gens)
        r = api.post("/lots", payload)
        if r.status_code in (200, 201):
            data = r.json()
            data["categoria"] = payload["categoria"]
            data["precio_base"] = payload["precio_base"]
            # Cache GPS for downstream distance calculations in
            # build_tx_payload (needed for logistics_fee_eur).
            data.setdefault("ubicacion_lat", payload["ubicacion_lat"])
            data.setdefault("ubicacion_lon", payload["ubicacion_lon"])
            data.setdefault("cantidad_kg", payload["cantidad_kg"])
            return data
        return None

    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = [ex.submit(_post_lot, i) for i in range(n_lots)]
        for i, f in enumerate(as_completed(futs)):
            res = f.result()
            if res:
                created_lots.append(res)
    print(f"   ✅ {len(created_lots)} lotes")

    if not created_lots:
        return

    print(f"\n💰 Creando ~{n_bids} pujas (paralelo)...")
    created_bids: List[Dict[str, Any]] = []
    skipped = 0

    def _post_bid(_i: int) -> Optional[Dict[str, Any]]:
        lote = random.choice(created_lots)
        payload = build_bid_payload(lote, created_recs)
        if not payload:
            return {"_skip": True}
        # Strip private fields the API doesn't accept.
        api_payload = {k: v for k, v in payload.items() if not k.startswith("_") and k not in (
            "receptor_tipo", "receptor_lat", "receptor_lon"
        )}
        r = api.post("/bids", api_payload)
        if r.status_code in (200, 201):
            data = r.json()
            data["lote_id"] = payload["lote_id"]
            data["precio_oferta"] = payload["precio_oferta"]
            data["uso_previsto"] = payload["uso_previsto"]
            data["categoria_lote"] = lote["categoria"]
            # Pass through private outcome + receptor geo so build_tx_payload
            # can compute logistics_fee without another API call.
            data["_outcome"] = payload.get("_outcome")
            data["receptor_tipo"] = payload.get("receptor_tipo")
            data["receptor_lat"] = payload.get("receptor_lat")
            data["receptor_lon"] = payload.get("receptor_lon")
            return data
        return None

    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = [ex.submit(_post_bid, i) for i in range(n_bids)]
        for f in as_completed(futs):
            res = f.result()
            if res is None:
                continue
            if res.get("_skip"):
                skipped += 1
                continue
            created_bids.append(res)
    print(f"   ✅ {len(created_bids)} pujas (skipped: {skipped})")

    print(f"\n🤝 Cerrando ~{n_tx} transacciones (paralelo)...")
    by_lot: Dict[int, List[Dict[str, Any]]] = {}
    for b in created_bids:
        by_lot.setdefault(b["lote_id"], []).append(b)

    lote_ids_con_puja = list(by_lot.keys())
    random.shuffle(lote_ids_con_puja)
    target_lotes = lote_ids_con_puja[:n_tx]

    def _close_tx(lote_id: int) -> Optional[Dict[str, Any]]:
        candidatos = by_lot[lote_id]
        if random.random() < 0.6:
            puja = max(candidatos, key=lambda b: b["precio_oferta"])
        else:
            puja = random.choice(candidatos)
        lote = next((l for l in created_lots if l["id"] == lote_id), None)
        if not lote:
            return None
        payload = build_tx_payload(lote, puja)
        r = api.post("/transactions", payload)
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code == 500:
            # La transacción se commitea antes de las notificaciones SMTP.
            # Si el SMTP falla, responde 500 pero la tx queda persistida.
            lr = api.get(f"/lots/{lote_id}")
            if lr.status_code == 200 and lr.json().get("estado") == "adjudicado":
                return {"_inferred": True, "lote_id": lote_id, "payload": payload}
        return None

    created_tx: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(_close_tx, lid) for lid in target_lotes]
        for f in as_completed(futs):
            res = f.result()
            if res:
                created_tx.append(res)
    print(f"   ✅ {len(created_tx)} transacciones cerradas")

    print("\n📊 Verificación post-seed:")
    r = api.get("/stats")
    stats_after = r.json()
    for k, v in stats_after.items():
        print(f"   {k}: {v}")

    r = api.get("/lots")
    n_active = len(r.json()) if r.status_code == 200 else -1
    print(f"   lots_activos: {n_active}")

    print("\n✨ Seed completado.")
    print(f"   🌐 UI:   {base_url}/app/")
    print(f"   📖 Docs: {base_url}/docs")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SurplusAI demo seed data")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--generators", type=int, default=45)
    p.add_argument("--receptors", type=int, default=100)
    p.add_argument("--lots", type=int, default=220)
    p.add_argument("--bids", type=int, default=320)
    p.add_argument("--tx", type=int, default=150)
    p.add_argument(
        "--force",
        action="store_true",
        help="Seed aunque ya haya datos (amplía el marketplace).",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    seed(
        base_url=args.base_url,
        n_generators=args.generators,
        n_receptors=args.receptors,
        n_lots=args.lots,
        n_bids=args.bids,
        n_tx=args.tx,
        force=args.force,
    )
