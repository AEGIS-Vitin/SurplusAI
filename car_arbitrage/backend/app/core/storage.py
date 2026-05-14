"""Persistencia SQLite para histórico de análisis y oportunidades.

Sin dependencias externas (sqlite3 builtin). Para producción real considera
postgres + alembic, pero esto es suficiente para auditoría y calibración.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Iterator, Optional

DEFAULT_DB_PATH = os.environ.get("CAR_ARBITRAGE_DB", "car_arbitrage.sqlite3")


SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    make TEXT, model TEXT, version TEXT, year INTEGER, km INTEGER,
    fuel TEXT, origin_country TEXT, origin TEXT,
    purchase_eur REAL, expected_sale_eur REAL, max_bid_eur REAL,
    margin_eur REAL, margin_pct REAL, roi_annualized REAL,
    risk_score INTEGER, label TEXT,
    days_to_sell REAL, segment TEXT,
    raw_request TEXT, raw_verdict TEXT
);
CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses(created_at);
CREATE INDEX IF NOT EXISTS idx_analyses_label ON analyses(label);
CREATE INDEX IF NOT EXISTS idx_analyses_make_model ON analyses(make, model);

CREATE TABLE IF NOT EXISTS sale_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER REFERENCES analyses(id),
    sold_at REAL,
    actual_sale_eur REAL,
    actual_days_to_sell REAL,
    actual_margin_eur REAL,
    notes TEXT
);
"""


@contextmanager
def connect(db_path: str = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_analysis(req_dict: dict, verdict_dict: dict, db_path: str = DEFAULT_DB_PATH) -> int:
    v = req_dict.get("vehicle") or {}
    s = verdict_dict.get("summary") or {}
    rot = verdict_dict.get("rotation") or {}
    risk = verdict_dict.get("risk") or {}

    row = (
        time.time(),
        v.get("make"), v.get("model"), v.get("version"), v.get("year"), v.get("km"),
        (v.get("fuel") or "").lower() if v.get("fuel") else None,
        v.get("origin_country"), req_dict.get("origin"),
        req_dict.get("purchase_price"),
        s.get("recommended_sale_eur") or verdict_dict.get("expected_sale_eur"),
        s.get("max_bid_eur") or verdict_dict.get("max_bid_eur"),
        s.get("expected_margin_eur") or verdict_dict.get("margin_eur"),
        verdict_dict.get("margin_pct"),
        s.get("annualized_roi_pct"),
        risk.get("score"), s.get("verdict") or verdict_dict.get("label"),
        s.get("expected_days_to_sell") or rot.get("median_days"),
        rot.get("segment"),
        json.dumps(req_dict, default=str), json.dumps(verdict_dict, default=str),
    )
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO analyses
            (created_at, make, model, version, year, km, fuel, origin_country, origin,
             purchase_eur, expected_sale_eur, max_bid_eur, margin_eur, margin_pct, roi_annualized,
             risk_score, label, days_to_sell, segment, raw_request, raw_verdict)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            row,
        )
        return cur.lastrowid


def list_recent(limit: int = 20, label_prefix: Optional[str] = None,
                db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    with connect(db_path) as conn:
        if label_prefix:
            rows = conn.execute(
                "SELECT * FROM analyses WHERE label LIKE ? ORDER BY created_at DESC LIMIT ?",
                (label_prefix + "%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM analyses ORDER BY created_at DESC LIMIT ?", (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def top_opportunities(min_margin_eur: float = 1500, max_risk: int = 35,
                      limit: int = 20, db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT id, created_at, make, model, version, year, km,
                      purchase_eur, expected_sale_eur, max_bid_eur, margin_eur, margin_pct,
                      roi_annualized, risk_score, label, days_to_sell, segment
               FROM analyses
               WHERE margin_eur >= ? AND (risk_score IS NULL OR risk_score <= ?)
                 AND label LIKE '🟢%'
               ORDER BY margin_eur DESC
               LIMIT ?""",
            (min_margin_eur, max_risk, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def record_sale_outcome(analysis_id: int, actual_sale_eur: float,
                        actual_days_to_sell: float, notes: str = "",
                        db_path: str = DEFAULT_DB_PATH) -> int:
    with connect(db_path) as conn:
        analysis = conn.execute(
            "SELECT purchase_eur, expected_sale_eur FROM analyses WHERE id = ?", (analysis_id,)
        ).fetchone()
        if not analysis:
            raise ValueError(f"analysis {analysis_id} not found")
        actual_margin = actual_sale_eur - (analysis["purchase_eur"] or 0)
        cur = conn.execute(
            """INSERT INTO sale_outcomes
            (analysis_id, sold_at, actual_sale_eur, actual_days_to_sell, actual_margin_eur, notes)
            VALUES (?,?,?,?,?,?)""",
            (analysis_id, time.time(), actual_sale_eur, actual_days_to_sell, actual_margin, notes),
        )
        return cur.lastrowid


def calibration_stats(db_path: str = DEFAULT_DB_PATH) -> dict:
    """Diferencia entre estimación y realidad para calibrar el modelo."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT a.expected_sale_eur, a.days_to_sell, a.margin_eur,
                      o.actual_sale_eur, o.actual_days_to_sell, o.actual_margin_eur,
                      a.segment
               FROM sale_outcomes o JOIN analyses a ON a.id = o.analysis_id
               WHERE o.actual_sale_eur IS NOT NULL"""
        ).fetchall()

    if not rows:
        return {"n": 0}
    n = len(rows)
    sale_errs = [r["actual_sale_eur"] - r["expected_sale_eur"] for r in rows if r["expected_sale_eur"]]
    days_errs = [r["actual_days_to_sell"] - r["days_to_sell"] for r in rows if r["days_to_sell"]]
    margin_errs = [r["actual_margin_eur"] - r["margin_eur"] for r in rows if r["margin_eur"] is not None]

    def _avg(xs):
        return sum(xs) / len(xs) if xs else 0.0

    return {
        "n": n,
        "avg_sale_error_eur": _avg(sale_errs),
        "avg_days_error": _avg(days_errs),
        "avg_margin_error_eur": _avg(margin_errs),
    }
