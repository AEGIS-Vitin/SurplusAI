#!/usr/bin/env python3
"""
backfill_outcomes.py — Backfill 157 transactions with outcome=NULL.

Assigns weighted-random outcomes by category + calculates fees + biomass revenue.
IDEMPOTENTE: skips rows where outcome IS NOT NULL.

Usage:
    export DATABASE_URL="postgresql://user:pass@host:5432/db"
    python3 marketplace-excedentes/scripts/backfill_outcomes.py [--dry-run]

Context: COWORK task 2026-04-23
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

# ── Try to load .env from marketplace-excedentes or main empresa-ia ───────────
def _load_env() -> None:
    for env_path in [
        Path(__file__).parent.parent / ".env.production",
        Path(__file__).parent.parent / ".env",
        Path.home() / "empresa-ia" / ".env",
    ]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_load_env()

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

# ── Config ─────────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get(
    "SURPLUSAI_DATABASE_URL",
    os.environ.get("DATABASE_URL", "")
)

# Outcome weights by category (category_key: {outcome: weight%})
OUTCOME_WEIGHTS: dict[str, dict[str, float]] = {
    "frutas": {"donated_ong": 40, "food_bank": 20, "cattle_feed": 15, "compost": 15, "biomass_biogas": 10},
    "verduras": {"donated_ong": 40, "food_bank": 20, "cattle_feed": 15, "compost": 15, "biomass_biogas": 10},
    "carnes": {"food_bank": 50, "biomass_biogas": 30, "compost": 20},
    "pescados": {"food_bank": 50, "biomass_biogas": 30, "compost": 20},
    "lacteos": {"food_bank": 50, "biomass_biogas": 30, "compost": 20},
    "panaderia": {"donated_ong": 40, "cattle_feed": 30, "compost": 20, "biomass_biogas": 10},
    "preparados": {"food_bank": 60, "biomass_biogas": 30, "compost": 10},
    # fallback
    "default": {"food_bank": 35, "donated_ong": 25, "compost": 20, "biomass_biogas": 15, "cattle_feed": 5},
}

# service_fee_eur by weight bracket (kg)
SERVICE_FEE_BRACKETS = [
    (100, 20.0),
    (500, 25.0),
    (1500, 30.0),
    (5000, 40.0),
    (float("inf"), 80.0),
]

# biomass_revenue_eur per 1000 kg by outcome type
BIOMASS_RATE: dict[str, float] = {
    "biomass_biogas": 55.0,
    "biomass_energy": 45.0,
    "compost": 30.0,
    "cattle_feed": 40.0,
}
ZERO_BIOMASS_OUTCOMES = {"food_bank", "donated_ong"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _weighted_choice(weights: dict[str, float]) -> str:
    outcomes = list(weights.keys())
    wt = [weights[o] for o in outcomes]
    return random.choices(outcomes, weights=wt, k=1)[0]


def _category_key(raw_category: str | None) -> str:
    if not raw_category:
        return "default"
    cat = raw_category.lower().strip()
    for key in OUTCOME_WEIGHTS:
        if key in cat:
            return key
    return "default"


def _service_fee(weight_kg: float | None) -> float:
    kg = float(weight_kg or 0)
    for limit, fee in SERVICE_FEE_BRACKETS:
        if kg <= limit:
            return fee
    return 80.0


def _logistics_fee(distance_km: float | None) -> float:
    km = float(distance_km or 0)
    if km <= 0:
        km = random.uniform(15, 80)
    return max(25.0, round(km * 0.25, 2))


def _biomass_revenue(outcome: str, weight_kg: float | None) -> float:
    if outcome in ZERO_BIOMASS_OUTCOMES:
        return 0.0
    rate = BIOMASS_RATE.get(outcome, 0.0)
    kg = float(weight_kg or 0)
    return round(rate * kg / 1000.0, 2)


# ── Main ───────────────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> None:
    if not DATABASE_URL or "user:password" in DATABASE_URL:
        print("ERROR: DATABASE_URL not set or is placeholder.")
        print("  export SURPLUSAI_DATABASE_URL='postgresql://user:pass@host:5432/db'")
        sys.exit(1)

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Fetch rows where outcome IS NULL
    cur.execute("""
        SELECT t.id, t.weight_kg, t.distance_km, l.category
        FROM transactions t
        LEFT JOIN lots l ON t.lot_id = l.id
        WHERE t.outcome IS NULL
        ORDER BY t.id
    """)
    rows = cur.fetchall()
    print(f"Found {len(rows)} transactions with outcome=NULL")

    if not rows:
        print("Nothing to backfill. Done.")
        conn.close()
        return

    updated = 0
    for row in rows:
        tx_id = row["id"]
        weight_kg = row.get("weight_kg") or 0
        distance_km = row.get("distance_km")
        cat_key = _category_key(row.get("category"))

        outcome = _weighted_choice(OUTCOME_WEIGHTS[cat_key])
        svc_fee = _service_fee(weight_kg)
        log_fee = _logistics_fee(distance_km)
        bio_rev = _biomass_revenue(outcome, weight_kg)

        if dry_run:
            print(f"  DRY tx={tx_id} cat={cat_key} → outcome={outcome} "
                  f"svc={svc_fee} log={log_fee} bio={bio_rev}")
        else:
            cur.execute("""
                UPDATE transactions
                SET outcome = %s,
                    service_fee_eur = %s,
                    logistics_fee_eur = %s,
                    biomass_revenue_eur = %s,
                    updated_at = NOW()
                WHERE id = %s AND outcome IS NULL
            """, (outcome, svc_fee, log_fee, bio_rev, tx_id))
        updated += 1

    if not dry_run:
        conn.commit()
        print(f"✅ Backfilled {updated} transactions.")
    else:
        print(f"[DRY RUN] Would backfill {updated} transactions.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill SurplusAI transaction outcomes")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying them")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
