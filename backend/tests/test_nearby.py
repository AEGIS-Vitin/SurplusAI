"""Tests for GET /lots/nearby — proximity search with logistics-aware radius caps.

These tests exercise the Python/haversine fallback path (no PostGIS).
conftest.py runs on in-memory SQLite, so ``USE_POSTGIS`` is never set.
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import database
import models


# Reference points (real Spanish cities)
MADRID = (40.4168, -3.7038)
BARCELONA = (41.3851, 2.1734)
VALENCIA = (39.4699, -0.3763)
# ~55 km north-west of central Madrid (inside "mediano" cap, outside "pequeño" cap)
ALCOBENDAS_FAR = (40.6200, -4.3800)


def _make_lote(
    db: Session,
    generador_id: int,
    *,
    producto: str,
    lat: float,
    lon: float,
    cantidad_kg: float = 100.0,
    categoria: models.Categoria = models.Categoria.frutas,
    dias_caducidad: int = 3,
):
    lote = database.LoteDB(
        generador_id=generador_id,
        producto=producto,
        categoria=categoria,
        cantidad_kg=cantidad_kg,
        # Use POINT(lon lat) — same format the create endpoint writes.
        ubicacion=f"POINT({lon} {lat})",
        fecha_publicacion=datetime.utcnow(),
        fecha_limite=datetime.utcnow() + timedelta(days=dias_caducidad),
        precio_base=50.0,
        precio_actual=50.0,
        temperatura_conservacion=4.0,
        estado=models.EstadoLote.activo,
        lote_origen="LOT_NEARBY",
    )
    db.add(lote)
    db.commit()
    db.refresh(lote)
    return lote


@pytest.fixture
def lots_spain(db: Session, test_generador):
    """Seed one lot per major city + a small/medium/large trio in Madrid."""
    gid = test_generador.id
    return {
        "madrid_small": _make_lote(db, gid, producto="Manzanas local", lat=MADRID[0], lon=MADRID[1], cantidad_kg=20.0),
        "madrid_medium": _make_lote(db, gid, producto="Lechugas", lat=MADRID[0] + 0.01, lon=MADRID[1], cantidad_kg=200.0, categoria=models.Categoria.verduras),
        "madrid_large": _make_lote(db, gid, producto="Patatas industria", lat=MADRID[0] - 0.01, lon=MADRID[1], cantidad_kg=1500.0, categoria=models.Categoria.verduras),
        "alcobendas": _make_lote(db, gid, producto="Leche", lat=ALCOBENDAS_FAR[0], lon=ALCOBENDAS_FAR[1], cantidad_kg=30.0, categoria=models.Categoria.lacteos),
        "barcelona": _make_lote(db, gid, producto="Pescado BCN", lat=BARCELONA[0], lon=BARCELONA[1], cantidad_kg=80.0, categoria=models.Categoria.pescados),
        "valencia": _make_lote(db, gid, producto="Naranjas VLC", lat=VALENCIA[0], lon=VALENCIA[1], cantidad_kg=500.0),
    }


def test_nearby_requires_lat_lon(client: TestClient):
    r = client.get("/lots/nearby")
    assert r.status_code == 422


def test_nearby_default_radius_50km(client: TestClient, lots_spain):
    """No radius + no weight → default 50 km. Madrid center must match all
    three Madrid lots but neither BCN nor Valencia."""
    r = client.get(f"/lots/nearby?lat={MADRID[0]}&lon={MADRID[1]}")
    assert r.status_code == 200
    body = r.json()
    assert body["query"]["radius_km"] == 50.0
    ids = {lot["id"] for lot in body["lots"]}
    assert lots_spain["madrid_small"].id in ids
    assert lots_spain["madrid_medium"].id in ids
    assert lots_spain["madrid_large"].id in ids
    assert lots_spain["barcelona"].id not in ids
    assert lots_spain["valencia"].id not in ids


def test_nearby_sorted_by_distance(client: TestClient, lots_spain):
    r = client.get(f"/lots/nearby?lat={MADRID[0]}&lon={MADRID[1]}&radius_km=2000")
    body = r.json()
    distances = [lot["distancia_km"] for lot in body["lots"]]
    assert distances == sorted(distances), "Lots must be sorted by distance ASC"
    # First result must be Madrid (≈0 km), last of the four reachable lots
    # within 2000 km should be BCN or VLC, not Madrid.
    assert body["lots"][0]["distancia_km"] < 5.0


def test_nearby_category_filter(client: TestClient, lots_spain):
    r = client.get(f"/lots/nearby?lat={MADRID[0]}&lon={MADRID[1]}&radius_km=2000&category=pescados")
    body = r.json()
    assert body["count"] == 1
    assert body["lots"][0]["id"] == lots_spain["barcelona"].id
    assert body["lots"][0]["categoria"] == "pescados"


def test_nearby_small_lot_cap_25km(client: TestClient, lots_spain):
    """max_weight_kg < 50 → radius auto-capped at 25 km.

    Alcobendas lot (55 km away) must NOT appear; Madrid lots (< 2 km) must.
    """
    r = client.get(f"/lots/nearby?lat={MADRID[0]}&lon={MADRID[1]}&max_weight_kg=30")
    body = r.json()
    assert body["query"]["radius_km"] == 25.0
    assert body["query"]["weight_tier"] == "pequeno"
    ids = {lot["id"] for lot in body["lots"]}
    assert lots_spain["madrid_small"].id in ids
    # alcobendas lot is 30 kg → passes weight filter, but 55 km > 25 km cap
    assert lots_spain["alcobendas"].id not in ids


def test_nearby_medium_lot_cap_100km(client: TestClient, lots_spain):
    """50 ≤ max_weight_kg ≤ 500 → radius cap 100 km. Alcobendas (55 km) in,
    BCN (~500 km) out."""
    r = client.get(f"/lots/nearby?lat={MADRID[0]}&lon={MADRID[1]}&max_weight_kg=300")
    body = r.json()
    assert body["query"]["radius_km"] == 100.0
    assert body["query"]["weight_tier"] == "mediano"
    ids = {lot["id"] for lot in body["lots"]}
    assert lots_spain["madrid_small"].id in ids  # 20 kg ≤ 300
    assert lots_spain["madrid_medium"].id in ids  # 200 kg ≤ 300
    assert lots_spain["barcelona"].id not in ids  # out of 100 km
    # Large lot (1500 kg) excluded by weight filter
    assert lots_spain["madrid_large"].id not in ids


def test_nearby_large_lot_no_cap(client: TestClient, lots_spain):
    """max_weight_kg > 500 → radius tier='grande' + national reach."""
    r = client.get(f"/lots/nearby?lat={MADRID[0]}&lon={MADRID[1]}&max_weight_kg=2000")
    body = r.json()
    assert body["query"]["weight_tier"] == "grande"
    assert body["query"]["radius_km"] >= 1000
    ids = {lot["id"] for lot in body["lots"]}
    # All lots ≤ 2000 kg should be reachable nationally
    assert lots_spain["barcelona"].id in ids
    assert lots_spain["valencia"].id in ids


def test_nearby_explicit_radius_overridden_by_small_cap(client: TestClient, lots_spain):
    """If client asks for 200 km AND small weight, the 25 km cap must win
    (logistics-aware override)."""
    r = client.get(f"/lots/nearby?lat={MADRID[0]}&lon={MADRID[1]}&radius_km=200&max_weight_kg=30")
    body = r.json()
    assert body["query"]["radius_km"] == 25.0
    assert body["query"]["radius_km_requested"] == 200.0


def test_nearby_limit(client: TestClient, lots_spain):
    r = client.get(f"/lots/nearby?lat={MADRID[0]}&lon={MADRID[1]}&radius_km=2000&limit=2")
    body = r.json()
    assert body["count"] == 2
    assert len(body["lots"]) == 2


def test_nearby_invalid_lat(client: TestClient):
    r = client.get("/lots/nearby?lat=91&lon=0")
    assert r.status_code == 422


def test_nearby_response_shape(client: TestClient, lots_spain):
    r = client.get(f"/lots/nearby?lat={MADRID[0]}&lon={MADRID[1]}")
    body = r.json()
    assert set(body.keys()) >= {"query", "count", "lots"}
    if body["lots"]:
        lot = body["lots"][0]
        for k in (
            "id", "generador_id", "generador_nombre", "producto", "categoria",
            "cantidad_kg", "ubicacion_lat", "ubicacion_lon", "precio_actual",
            "estado", "num_bids", "distancia_km",
        ):
            assert k in lot, f"Missing field {k} in /lots/nearby response"
