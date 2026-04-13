#!/usr/bin/env python3
"""
Seed demo data for SurplusAI production instance.
Creates realistic generators, receptors, lots, and bids for demo purposes.

Usage:
    python3 seed_demo_data.py [--base-url URL]
"""

import httpx
import sys
from datetime import datetime, timedelta

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "https://surplusai-backend-production.up.railway.app"

# Demo generators (food surplus producers)
GENERATORS = [
    {
        "nombre": "Mercadona Distribución S.A.",
        "tipo": "retail",
        "cif": "A46103834",
        "direccion": "C/ Valencia 5, 46016 Tavernes Blanques, Valencia",
        "ubicacion_lat": 39.5055,
        "ubicacion_lon": -0.3569,
        "contacto_email": "excedentes@mercadona-demo.es",
        "contacto_telefono": "+34961032600",
        "plan_suscripcion": "premium"
    },
    {
        "nombre": "Grupo Calvo S.L.",
        "tipo": "industria",
        "cif": "B36609925",
        "direccion": "Polígono Industrial A Pasaxe, 36600 Vilagarcía de Arousa, Pontevedra",
        "ubicacion_lat": 42.5971,
        "ubicacion_lon": -8.7644,
        "contacto_email": "surplus@grupocalvo-demo.es",
        "contacto_telefono": "+34986511100",
        "plan_suscripcion": "profesional"
    },
    {
        "nombre": "Panadería Artesanal El Horno de Leña",
        "tipo": "horeca",
        "cif": "B87654321",
        "direccion": "C/ Gran Vía 45, 28013 Madrid",
        "ubicacion_lat": 40.4203,
        "ubicacion_lon": -3.7026,
        "contacto_email": "info@hornolena-demo.es",
        "contacto_telefono": "+34915551234",
        "plan_suscripcion": "basico"
    },
    {
        "nombre": "Cooperativa Agrícola La Huerta",
        "tipo": "primario",
        "cif": "F12345678",
        "direccion": "Camino de la Huerta s/n, 30820 Alcantarilla, Murcia",
        "ubicacion_lat": 37.9691,
        "ubicacion_lon": -1.2237,
        "contacto_email": "coop@lahuerta-demo.es",
        "contacto_telefono": "+34968801234",
        "plan_suscripcion": "profesional"
    },
    {
        "nombre": "Hotel Ritz Madrid",
        "tipo": "horeca",
        "cif": "B28765432",
        "direccion": "Plaza de la Lealtad 5, 28014 Madrid",
        "ubicacion_lat": 40.4146,
        "ubicacion_lon": -3.6932,
        "contacto_email": "cocina@ritz-demo.es",
        "contacto_telefono": "+34917016767",
        "plan_suscripcion": "premium"
    }
]

# Demo receptors (food surplus receivers)
RECEPTORS = [
    {
        "nombre": "Banco de Alimentos de Madrid",
        "tipo": "banco_alimentos",
        "cif": "G81098505",
        "direccion": "C/ Peña Gorbea 11, 28018 Madrid",
        "ubicacion_lat": 40.3855,
        "ubicacion_lon": -3.6623,
        "capacidad_kg_dia": 15000.0,
        "categorias_interes": ["frutas", "verduras", "lacteos", "panaderia"],
        "licencias": ["manipulacion_alimentos", "transporte_refrigerado"]
    },
    {
        "nombre": "BioEnergía Renovable S.L.",
        "tipo": "biogas",
        "cif": "B91234567",
        "direccion": "Polígono Eco-Industrial, 45200 Illescas, Toledo",
        "ubicacion_lat": 40.1264,
        "ubicacion_lon": -3.8478,
        "capacidad_kg_dia": 50000.0,
        "categorias_interes": ["frutas", "verduras", "otros"],
        "licencias": ["gestion_residuos", "planta_biogas"]
    },
    {
        "nombre": "Piensos Naturales García S.A.",
        "tipo": "piensos",
        "cif": "A28567890",
        "direccion": "Carretera Nacional IV km 35, 28340 Valdemoro, Madrid",
        "ubicacion_lat": 40.1911,
        "ubicacion_lon": -3.6800,
        "capacidad_kg_dia": 8000.0,
        "categorias_interes": ["panaderia", "prepared", "carnes"],
        "licencias": ["fabricacion_piensos", "transporte"]
    },
    {
        "nombre": "Compostaje Ecológico Levante",
        "tipo": "compost",
        "cif": "B46789012",
        "direccion": "Partida La Serreta s/n, 03801 Alcoy, Alicante",
        "ubicacion_lat": 38.6985,
        "ubicacion_lon": -0.4737,
        "capacidad_kg_dia": 25000.0,
        "categorias_interes": ["frutas", "verduras", "otros"],
        "licencias": ["gestion_residuos", "compostaje"]
    },
    {
        "nombre": "Transformados Alimentarios del Sur",
        "tipo": "transformador",
        "cif": "B41098765",
        "direccion": "Polígono Calonge, 41007 Sevilla",
        "ubicacion_lat": 37.3891,
        "ubicacion_lon": -5.9845,
        "capacidad_kg_dia": 12000.0,
        "categorias_interes": ["frutas", "verduras", "lacteos"],
        "licencias": ["industria_alimentaria", "transporte_refrigerado"]
    }
]

# Demo lots (food surplus listings) - will be created after generators
LOTS_TEMPLATES = [
    {
        "producto": "Naranjas Valencia Late calibre 6-7",
        "categoria": "frutas",
        "cantidad_kg": 2500.0,
        "precio_base": 0.35,
        "temperatura_conservacion": 8.0,
        "lote_origen": "LOT-NAR-2026-0413",
        "gen_idx": 3  # Cooperativa
    },
    {
        "producto": "Yogures naturales fecha próxima (3 días)",
        "categoria": "lacteos",
        "cantidad_kg": 800.0,
        "precio_base": 0.90,
        "temperatura_conservacion": 4.0,
        "lote_origen": "LOT-YOG-2026-0413",
        "gen_idx": 0  # Mercadona
    },
    {
        "producto": "Pan de molde integral sin corteza",
        "categoria": "panaderia",
        "cantidad_kg": 350.0,
        "precio_base": 0.50,
        "temperatura_conservacion": 20.0,
        "lote_origen": "LOT-PAN-2026-0413",
        "gen_idx": 2  # Panadería
    },
    {
        "producto": "Merluza congelada corte mariposa",
        "categoria": "pescados",
        "cantidad_kg": 1200.0,
        "precio_base": 2.80,
        "temperatura_conservacion": -18.0,
        "lote_origen": "LOT-MER-2026-0413",
        "gen_idx": 1  # Calvo
    },
    {
        "producto": "Tomates rama excedente cosecha",
        "categoria": "verduras",
        "cantidad_kg": 5000.0,
        "precio_base": 0.20,
        "temperatura_conservacion": 12.0,
        "lote_origen": "LOT-TOM-2026-0413",
        "gen_idx": 3  # Cooperativa
    },
    {
        "producto": "Platos preparados buffet (ensaladas, guarniciones)",
        "categoria": "prepared",
        "cantidad_kg": 200.0,
        "precio_base": 1.50,
        "temperatura_conservacion": 4.0,
        "lote_origen": "LOT-BUF-2026-0413",
        "gen_idx": 4  # Hotel Ritz
    },
    {
        "producto": "Lechugas iceberg calibre grande",
        "categoria": "verduras",
        "cantidad_kg": 3000.0,
        "precio_base": 0.15,
        "temperatura_conservacion": 6.0,
        "lote_origen": "LOT-LEC-2026-0413",
        "gen_idx": 0  # Mercadona
    },
    {
        "producto": "Filetes de pollo fecha corta (2 días)",
        "categoria": "carnes",
        "cantidad_kg": 600.0,
        "precio_base": 2.20,
        "temperatura_conservacion": 2.0,
        "lote_origen": "LOT-POL-2026-0413",
        "gen_idx": 0  # Mercadona
    }
]


def seed():
    client = httpx.Client(base_url=BASE_URL, timeout=30)

    print(f"🌱 Seeding demo data to {BASE_URL}")
    print("=" * 60)

    # Check if data already exists
    stats = client.get("/stats").json()
    if stats.get("num_generadores", 0) > 0:
        print("⚠️  Data already exists! Skipping seed to avoid duplicates.")
        print(f"   Generators: {stats['num_generadores']}, Receptors: {stats['num_receptores']}")
        return

    # 1. Create generators
    print("\n📦 Creating generators...")
    gen_ids = []
    for g in GENERATORS:
        r = client.post("/generadores", json=g)
        if r.status_code in (200, 201):
            data = r.json()
            gen_id = data.get("id")
            gen_ids.append(gen_id)
            print(f"   ✅ {g['nombre']} (ID: {gen_id})")
        else:
            print(f"   ❌ {g['nombre']}: {r.status_code} - {r.text[:100]}")
            gen_ids.append(None)

    # 2. Create receptors
    print("\n🏭 Creating receptors...")
    rec_ids = []
    for r_data in RECEPTORS:
        r = client.post("/receptores", json=r_data)
        if r.status_code in (200, 201):
            data = r.json()
            rec_id = data.get("id")
            rec_ids.append(rec_id)
            print(f"   ✅ {r_data['nombre']} (ID: {rec_id})")
        else:
            print(f"   ❌ {r_data['nombre']}: {r.status_code} - {r.text[:100]}")
            rec_ids.append(None)

    # 3. Create lots
    print("\n📋 Creating surplus lots...")
    lot_ids = []
    now = datetime.utcnow()
    for lot in LOTS_TEMPLATES:
        gen_idx = lot.pop("gen_idx")
        gen_id = gen_ids[gen_idx] if gen_idx < len(gen_ids) else gen_ids[0]
        if gen_id is None:
            print(f"   ⏭️  Skipping {lot['producto']} (no generator)")
            lot["gen_idx"] = gen_idx
            continue

        # Add required fields
        lot_data = {
            **lot,
            "generador_id": gen_id,
            "ubicacion_lat": GENERATORS[gen_idx]["ubicacion_lat"],
            "ubicacion_lon": GENERATORS[gen_idx]["ubicacion_lon"],
            "fecha_limite": (now + timedelta(days=3)).isoformat(),
        }

        r = client.post("/lots", json=lot_data)
        if r.status_code in (200, 201):
            data = r.json()
            lot_id = data.get("id")
            lot_ids.append(lot_id)
            print(f"   ✅ {lot['producto']} ({lot['cantidad_kg']}kg @ €{lot['precio_base']}/kg) → ID: {lot_id}")
        else:
            print(f"   ❌ {lot['producto']}: {r.status_code} - {r.text[:200]}")
            lot_ids.append(None)

        lot["gen_idx"] = gen_idx

    # 4. Create some bids
    print("\n💰 Creating bids...")
    bids = [
        {"lot_idx": 0, "rec_idx": 0, "precio": 0.30, "uso": 2, "msg": "Para distribución a familias en riesgo de exclusión social"},
        {"lot_idx": 0, "rec_idx": 4, "precio": 0.28, "uso": 3, "msg": "Para elaboración de zumo natural y mermelada"},
        {"lot_idx": 1, "rec_idx": 0, "precio": 0.80, "uso": 2, "msg": "Yogures para programa de meriendas infantiles"},
        {"lot_idx": 2, "rec_idx": 2, "precio": 0.40, "uso": 4, "msg": "Para fabricación de pienso animal premium"},
        {"lot_idx": 4, "rec_idx": 3, "precio": 0.12, "uso": 6, "msg": "Compostaje ecológico certificado"},
        {"lot_idx": 4, "rec_idx": 1, "precio": 0.10, "uso": 7, "msg": "Generación de biogás renovable"},
        {"lot_idx": 6, "rec_idx": 0, "precio": 0.12, "uso": 2, "msg": "Para bancos de alimentos de la Comunidad de Madrid"},
        {"lot_idx": 7, "rec_idx": 2, "precio": 1.80, "uso": 4, "msg": "Pienso proteico para ganado"},
    ]

    for bid in bids:
        lot_id = lot_ids[bid["lot_idx"]] if bid["lot_idx"] < len(lot_ids) else None
        rec_id = rec_ids[bid["rec_idx"]] if bid["rec_idx"] < len(rec_ids) else None
        if not lot_id or not rec_id:
            print(f"   ⏭️  Skipping bid (missing lot/receptor)")
            continue

        bid_data = {
            "receptor_id": rec_id,
            "precio_oferta": bid["precio"],
            "uso_previsto": bid["uso"],
            "mensaje": bid["msg"]
        }
        r = client.post(f"/bids/{lot_id}", json=bid_data)
        if r.status_code in (200, 201):
            print(f"   ✅ Bid €{bid['precio']}/kg on lot {lot_id} from receptor {rec_id}")
        else:
            print(f"   ❌ Bid on lot {lot_id}: {r.status_code} - {r.text[:200]}")

    # 5. Final stats
    print("\n📊 Final stats:")
    stats = client.get("/stats").json()
    for k, v in stats.items():
        print(f"   {k}: {v}")

    print("\n✅ Demo data seeded successfully!")
    print(f"🌐 API Docs: {BASE_URL}/docs")
    print(f"📊 Dashboard: {BASE_URL}/dashboard")

    client.close()


if __name__ == "__main__":
    seed()
