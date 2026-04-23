"""
Automatic matching engine for SurplusAI lots.

This replaces the Dutch-auction / descending-price model that the Gemini leg
of the VERDICT_BUSINESS_MODEL.md review ("kill the Dutch auction, match
instantly on geography + category + urgency + receiver priority") flagged as
a strategic dead-end for a disposal-guarantee + logistics business.

The new model:

1. On lot creation, we score every receptor whose `categorias_interes`
   contains the lot's category.
2. Score = (1 / distance_km) * peso_factor * urgency_factor *
   receiver_priority_factor.
3. Top N receptors are notified in descending score order. In the real
   system, if the top receiver doesn't accept in 2h we roll down the list;
   if nobody accepts in 24h we trigger `fallback_destination` (pienso,
   biomass/biogás or compost depending on category).
4. Food price stays at whatever the generator set (symbolic / 0€ / small
   recovery fee for fresh protein). It is **not** recomputed as a Dutch
   auction.

This module only contains the scoring + fallback logic; the FastAPI wire-up
lives in main.py (`auto_match_lot`, `fallback_destination`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

import database
import models


# --- Receiver priority (ONG > banco alimentos > ganadería > biogás > compostaje)
# In our domain model, "banco_alimentos" covers both ONGs and food banks.
# We split by inspecting the receptor name / licenses if we want finer granularity,
# but the high-level tier ordering below is what the VERDICT doc mandates.
RECEIVER_PRIORITY: dict[str, float] = {
    # Human consumption (priority)
    "banco_alimentos": 1.00,
    # Reprocessing into human-food (4ª gama, zumos, conservas)
    "transformador": 0.85,
    # Animal feed (cattle, pigs — SANDACH / REGISTRO_PIENSOS)
    "piensos": 0.60,
    # Industrial biogas valorization
    "biogas": 0.40,
    # Aerobic composting
    "compost": 0.30,
}


# Category → fallback tier when no human / animal destination accepts in 24h.
# Per VERDICT: carnes/pescados cannot go to cattle_feed (SANDACH restriction),
# so they fall to biogas; vegetables fall to biogas first, then compost.
FALLBACK_BY_CATEGORY: dict[str, List[str]] = {
    "frutas": ["biogas", "compost", "piensos"],
    "verduras": ["biogas", "compost", "piensos"],
    "lacteos": ["biogas", "compost"],
    "carnes": ["biogas", "compost"],          # NOT piensos (sanitary)
    "pescados": ["biogas", "compost"],        # NOT piensos (sanitary)
    "panaderia": ["piensos", "biogas", "compost"],
    "prepared": ["biogas", "compost"],
    "otros": ["biogas", "compost", "piensos"],
}


@dataclass
class MatchCandidate:
    receptor_id: int
    receptor_nombre: str
    receptor_tipo: str
    distance_km: float
    score: float
    priority_factor: float
    urgency_factor: float
    weight_factor: float
    contacto_email: Optional[str] = None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km (shared with main.py)."""
    R = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(a)))


def _weight_factor(kg: float) -> float:
    """Heavier lots are more urgent to place — but capped so a 5t lot doesn't
    dominate the ranking against a perfectly-located 200kg banco."""
    if kg <= 0:
        return 1.0
    # log scaling: 100kg → ~1.0, 1000kg → ~1.7, 10 000kg → ~2.4
    return 1.0 + math.log10(max(kg, 10) / 100.0) * 0.7


def _urgency_factor(fecha_limite: datetime) -> float:
    """Closer to expiry → higher urgency multiplier."""
    if fecha_limite is None:
        return 1.0
    hours_left = (fecha_limite - datetime.utcnow()).total_seconds() / 3600.0
    if hours_left < 6:
        return 2.5
    if hours_left < 12:
        return 2.0
    if hours_left < 24:
        return 1.5
    if hours_left < 72:
        return 1.2
    return 1.0


def _priority_factor(receptor_tipo: str) -> float:
    tipo = receptor_tipo.value if hasattr(receptor_tipo, "value") else str(receptor_tipo)
    return RECEIVER_PRIORITY.get(tipo, 0.5)


def rank_receivers(
    db,
    lot: "database.LoteDB",
    lot_lat: float,
    lot_lon: float,
    max_radius_km: float = 150.0,
    limit: int = 20,
) -> List[MatchCandidate]:
    """Return receptors sorted by descending match score.

    We filter at the Python level (no PostGIS dependency) so this works on
    the Railway vanilla Postgres + the SQLite test path uniformly.
    """
    from main import parse_ubicacion  # avoid circular import at module load

    categoria_val = lot.categoria.value if hasattr(lot.categoria, "value") else str(lot.categoria)

    receptores = db.query(database.ReceptorDB).all()
    candidates: List[MatchCandidate] = []

    uf = _urgency_factor(lot.fecha_limite)
    wf = _weight_factor(lot.cantidad_kg or 0)

    for r in receptores:
        cats = r.categorias_interes or []
        if cats and categoria_val not in cats:
            continue  # doesn't handle this category

        r_lat, r_lon = parse_ubicacion(r.ubicacion)
        if r_lat == 0.0 and r_lon == 0.0:
            continue  # receptor not geolocated
        dist = haversine_km(lot_lat, lot_lon, r_lat, r_lon)
        if dist > max_radius_km:
            continue

        pf = _priority_factor(r.tipo)
        # Distance contribution: 1/(dist+0.5) so within 0.5km ≈ 2.0, 10km ≈ 0.095
        dist_component = 1.0 / max(dist + 0.5, 0.5)

        score = dist_component * wf * uf * pf

        candidates.append(
            MatchCandidate(
                receptor_id=r.id,
                receptor_nombre=r.nombre,
                receptor_tipo=r.tipo.value if hasattr(r.tipo, "value") else str(r.tipo),
                distance_km=round(dist, 2),
                score=round(score, 4),
                priority_factor=pf,
                urgency_factor=uf,
                weight_factor=round(wf, 3),
                contacto_email=getattr(r, "contacto_email", None),
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:limit]


def pick_fallback_receptor(
    db,
    categoria: str,
    lot_lat: float,
    lot_lon: float,
    max_radius_km: float = 500.0,
) -> Optional[MatchCandidate]:
    """Pick a fallback (biogas/compost/piensos) receiver when nobody human-grade
    accepted within the SLA window.

    Returns the closest eligible receptor for the first tier in
    FALLBACK_BY_CATEGORY[categoria] that has any match; `None` if even biogás
    and compost are out of range (which is an operational red flag — a disposal
    guarantee MVP must always find *something*).
    """
    from main import parse_ubicacion

    fallback_tiers = FALLBACK_BY_CATEGORY.get(categoria, ["biogas", "compost"])
    receptores = db.query(database.ReceptorDB).all()

    for tier in fallback_tiers:
        best: Optional[MatchCandidate] = None
        for r in receptores:
            tipo_val = r.tipo.value if hasattr(r.tipo, "value") else str(r.tipo)
            if tipo_val != tier:
                continue
            r_lat, r_lon = parse_ubicacion(r.ubicacion)
            if r_lat == 0.0 and r_lon == 0.0:
                continue
            dist = haversine_km(lot_lat, lot_lon, r_lat, r_lon)
            if dist > max_radius_km:
                continue
            cand = MatchCandidate(
                receptor_id=r.id,
                receptor_nombre=r.nombre,
                receptor_tipo=tipo_val,
                distance_km=round(dist, 2),
                score=1.0 / max(dist + 0.5, 0.5),
                priority_factor=RECEIVER_PRIORITY.get(tipo_val, 0.3),
                urgency_factor=1.0,
                weight_factor=1.0,
                contacto_email=getattr(r, "contacto_email", None),
            )
            if best is None or cand.distance_km < best.distance_km:
                best = cand
        if best is not None:
            return best

    return None


# Outcome enum string values — kept in sync with OutcomeEnum in models.py.
# Used by the fallback helper and by reporting.
OUTCOME_DONATED_ONG = "donated_ong"
OUTCOME_FOOD_BANK = "food_bank"
OUTCOME_CATTLE_FEED = "cattle_feed"
OUTCOME_BIOMASS_BIOGAS = "biomass_biogas"
OUTCOME_COMPOST = "compost"
OUTCOME_ENERGY_BIOGAS = "energy_biogas"


TIPO_TO_OUTCOME: dict[str, str] = {
    # Default mapping when the receptor tipo is the only signal we have.
    # The real call site should cross-check with categoria (see main.py).
    "banco_alimentos": OUTCOME_FOOD_BANK,
    "transformador": OUTCOME_FOOD_BANK,
    "piensos": OUTCOME_CATTLE_FEED,
    "biogas": OUTCOME_BIOMASS_BIOGAS,
    "compost": OUTCOME_COMPOST,
}
