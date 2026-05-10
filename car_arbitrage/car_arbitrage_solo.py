#!/usr/bin/env python3
"""
Car Arbitrage Pro — single-file edition.

Calculadora de rentabilidad para compraventa de coches con arbitraje
multi-mercado. TODO incluido en este archivo: backend FastAPI, motor fiscal
español (IEDMT, IVA REBU/general/import), aduanas extra-UE, transporte,
homologación, escenarios de venta, ROI, riesgo, rotación, Monte Carlo,
SQLite persistente, notificador Telegram y frontend SPA embebido.

Uso:
    python3 car_arbitrage_solo.py
    # → abre http://localhost:8000

El script auto-instala dependencias Python si faltan. No requiere nada
más que Python 3.10+ y conexión a internet la primera vez.

Variables de entorno (todas opcionales):
    CAR_ARBITRAGE_TELEGRAM_BOT_TOKEN
    CAR_ARBITRAGE_TELEGRAM_CHAT_ID
    CAR_ARBITRAGE_DB                       # default ./car_arbitrage.sqlite3
    PORT                                   # default 8000

Aviso legal: ayuda de cálculo. Verifica con tu asesor fiscal antes de
operar. Importar coches extra-UE requiere homologación individual.
"""
from __future__ import annotations

# ────────────────────────────────────────────────────────────────────
# 0. Bootstrap: auto-install dependencies if missing
# ────────────────────────────────────────────────────────────────────
import subprocess
import sys


def _ensure_deps() -> None:
    required = {
        "fastapi": "fastapi==0.115.0",
        "uvicorn": "uvicorn[standard]==0.32.0",
        "pydantic": "pydantic==2.9.2",
        "httpx": "httpx==0.27.2",
        "numpy": "numpy>=1.26",
    }
    missing = []
    for mod, spec in required.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(spec)
    if missing:
        print(f"[bootstrap] Instalando dependencias: {missing}", flush=True)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", *missing])


_ensure_deps()


# ────────────────────────────────────────────────────────────────────
# 1. Imports
# ────────────────────────────────────────────────────────────────────
import asyncio
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date
from enum import Enum
from typing import Any, Iterator, Literal, Optional

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


# ════════════════════════════════════════════════════════════════════
# 2. MODELS
# ════════════════════════════════════════════════════════════════════

class FuelType(str, Enum):
    GASOLINE = "gasoline"
    DIESEL = "diesel"
    HEV = "hev"
    MHEV = "mhev"
    PHEV = "phev"
    BEV = "bev"
    LPG = "lpg"
    CNG = "cng"
    H2 = "hydrogen"


class Origin(str, Enum):
    EU_AUCTION = "eu_auction"
    EU_RETAIL_PRO = "eu_retail_pro"
    EU_RETAIL_PRO_REBU = "eu_retail_pro_rebu"
    EU_RETAIL_PRIVATE = "eu_retail_private"
    EXTRA_EU = "extra_eu"


class VATRegime(str, Enum):
    REBU = "rebu"
    GENERAL = "general"
    IMPORT_EXTRA_EU = "import_extra_eu"


class Vehicle(BaseModel):
    make: str
    model: str
    version: Optional[str] = None
    year: int = Field(ge=1950, le=2100)
    km: int = Field(ge=0)
    fuel: FuelType
    power_kw: Optional[float] = None
    power_cv: Optional[float] = None
    displacement_cc: Optional[int] = None
    co2_wltp: Optional[float] = None
    co2_nedc: Optional[float] = None
    euro_norm: Optional[str] = None
    transmission: Optional[Literal["manual", "automatic"]] = None
    drive: Optional[Literal["fwd", "rwd", "awd"]] = None
    seats: Optional[int] = 5
    vin: Optional[str] = None
    origin_country: str
    declared_damages: Optional[str] = None
    has_coc: bool = True
    has_service_book: bool = True
    previous_owners: Optional[int] = None

    @property
    def age_years(self) -> int:
        return max(0, date.today().year - self.year)

    @property
    def co2_effective(self) -> Optional[float]:
        if self.co2_wltp is not None:
            return self.co2_wltp
        if self.co2_nedc is not None:
            return self.co2_nedc * 1.21
        return None


class Comparable(BaseModel):
    source: str
    market: Literal["ES", "DE", "FR", "IT", "PT", "NL", "AE", "US", "UK", "JP"]
    price_eur: float
    km: int
    year: int
    url: Optional[str] = None
    days_listed: Optional[int] = None
    accident: bool = False


class AnalysisRequest(BaseModel):
    vehicle: Vehicle
    origin: Origin
    purchase_price: float
    purchase_currency: str = "EUR"
    fx_rate_to_eur: float = 1.0
    auction_fee_pct: float = 0.055
    auction_flat_fee: float = 150.0
    transport_eur: Optional[float] = None
    reconditioning_eur: Optional[float] = None
    target_margin_pct: float = 0.12
    sell_market: Literal["ES", "DE"] = "ES"
    vat_regime: VATRegime = VATRegime.REBU
    canary_islands: bool = False
    comparables: list[Comparable] = []
    days_in_stock: int = 35
    capital_cost_annual: float = 0.08
    income_tax_rate: float = 0.25
    extra_options: dict = {}


# ════════════════════════════════════════════════════════════════════
# 3. FX
# ════════════════════════════════════════════════════════════════════

FX_DEFAULT = {"EUR": 1.0, "USD": 0.92, "AED": 0.25, "GBP": 1.17, "JPY": 0.0061, "CHF": 1.04}


def to_eur(amount: float, currency: str, override: float | None = None) -> float:
    if override is not None:
        return amount * override
    rate = FX_DEFAULT.get(currency.upper())
    if rate is None:
        raise ValueError(f"Unknown currency {currency}")
    return amount * rate


# ════════════════════════════════════════════════════════════════════
# 4. IEDMT
# ════════════════════════════════════════════════════════════════════

DEPRECIATION = [(1, 1.0), (2, 0.84), (3, 0.67), (4, 0.56), (5, 0.47), (6, 0.39),
                (7, 0.34), (8, 0.28), (9, 0.24), (10, 0.19), (11, 0.17), (12, 0.13)]
DEPR_FLOOR = 0.10


def depreciation_coef(age: int) -> float:
    for cap, c in DEPRECIATION:
        if age < cap:
            return c
    return DEPR_FLOOR


def iedmt_rate(co2: Optional[float], canary: bool = False) -> float:
    if co2 is None:
        co2 = 200.0
    if canary:
        if co2 < 120: return 0.0
        if co2 < 160: return 0.0375
        if co2 < 200: return 0.0875
        return 0.1375
    if co2 < 120: return 0.0
    if co2 < 160: return 0.0475
    if co2 < 200: return 0.0975
    return 0.1475


@dataclass
class IEDMTResult:
    rate: float
    base_eur: float
    tax_eur: float
    exemption_reason: Optional[str] = None
    notes: list[str] = field(default_factory=list)


def compute_iedmt(v: Vehicle, fiscal_value_new_eur: float, canary: bool = False,
                  historic: bool = False, large_family: bool = False,
                  disability: bool = False, ceuta_melilla: bool = False) -> IEDMTResult:
    notes: list[str] = []
    if ceuta_melilla:
        return IEDMTResult(0, 0, 0, "Ceuta/Melilla exento", notes)
    if disability:
        return IEDMTResult(0, 0, 0, "Discapacidad ≥33%", notes)
    if historic and v.age_years >= 30:
        return IEDMTResult(0, 0, 0, "Vehículo histórico >30 años", notes)
    if v.fuel == FuelType.BEV:
        return IEDMTResult(0, 0, 0, "BEV tipo 0%", notes)
    co2 = v.co2_effective
    if co2 is None:
        notes.append("Sin CO2: asume 200 g/km (tipo máximo).")
    rate = iedmt_rate(co2, canary)
    coef = depreciation_coef(v.age_years)
    base = fiscal_value_new_eur * coef
    notes.append(f"Coef depreciación {v.age_years} años: {coef:.2f}")
    tax = base * rate
    if large_family:
        tax *= 0.5
        notes.append("Bonificación 50% familia numerosa.")
    return IEDMTResult(rate, base, tax, None, notes)


# ════════════════════════════════════════════════════════════════════
# 5. IVA / REBU
# ════════════════════════════════════════════════════════════════════

VAT_RATE_ES = 0.21


@dataclass
class VATBreakdown:
    regime: str
    vat_charged: float
    vat_deductible: float
    net_vat_to_pay: float
    notes: list[str]


def rebu_vat(sale: float, total_purchase_vat_incl: float) -> VATBreakdown:
    margin = max(0.0, sale - total_purchase_vat_incl)
    vat = margin * (VAT_RATE_ES / (1 + VAT_RATE_ES))
    return VATBreakdown("REBU", vat, 0.0, vat, [
        f"Base IVA (margen): {margin:,.2f} €",
        "Factura SIN IVA al cliente (art. 135 Ley 37/1992).",
        "IVA soportado en gastos NO deducible.",
    ])


def general_vat(sale_net: float, deductible_input_vat: float) -> VATBreakdown:
    vat_out = sale_net * VAT_RATE_ES
    return VATBreakdown("General", vat_out, deductible_input_vat, vat_out - deductible_input_vat, [
        f"IVA repercutido (21%): {vat_out:,.2f} €",
        f"IVA soportado deducible: {deductible_input_vat:,.2f} €",
    ])


# ════════════════════════════════════════════════════════════════════
# 6. ADUANAS extra-UE
# ════════════════════════════════════════════════════════════════════

DUTY_PASSENGER_CAR = 0.10
IGIC_CANARY = 0.07


@dataclass
class CustomsBreakdown:
    cif_eur: float
    duty_eur: float
    vat_eur: float
    dua_fee_eur: float
    inspection_fee_eur: float
    total_eur: float
    notes: list[str]


def compute_customs(purchase_eur: float, freight_eur: float, insurance_eur: float,
                    canary: bool = False, historic: bool = False,
                    dua_fee: float = 380.0, inspection_prob: float = 0.15,
                    inspection_cost: float = 220.0) -> CustomsBreakdown:
    cif = purchase_eur + freight_eur + insurance_eur
    duty_rate = 0.0 if historic else DUTY_PASSENGER_CAR
    duty = cif * duty_rate
    vat_rate = IGIC_CANARY if canary else VAT_RATE_ES
    vat = (cif + duty) * vat_rate
    inspection_expected = inspection_cost * inspection_prob
    notes = [
        f"CIF: {cif:,.2f} €",
        f"Arancel TARIC {duty_rate*100:.1f}%: {duty:,.2f} €",
        f"{'IGIC' if canary else 'IVA importación'} {vat_rate*100:.1f}%: {vat:,.2f} €",
        f"DUA: {dua_fee:,.2f} €",
    ]
    if historic:
        notes.append("Vehículo histórico: arancel 0%.")
    return CustomsBreakdown(cif, duty, vat, dua_fee, inspection_expected,
                            duty + vat + dua_fee + inspection_expected, notes)


# ════════════════════════════════════════════════════════════════════
# 7. TRANSPORTE
# ════════════════════════════════════════════════════════════════════

EU_TRUCK = {"DE": (600, 900), "FR": (400, 650), "IT": (500, 800), "NL": (700, 950),
            "BE": (700, 950), "PL": (850, 1100), "AT": (700, 950), "PT": (250, 400),
            "SE": (1100, 1500), "DK": (900, 1200), "CZ": (800, 1050), "CH": (700, 950)}
EXTRA_EU = {"AE": {"roro": (1500, 2500), "container": (3000, 4500), "transit": 23},
            "JP": {"roro": (1800, 2800), "container": (3500, 5500), "transit": 42},
            "US": {"roro": (1300, 2200), "container": (2800, 4200), "transit": 24},
            "GB": {"roro": (500, 800), "container": (1500, 2400), "transit": 5}}


@dataclass
class TransportEstimate:
    mode: str
    cost_eur: float
    transit_days: float
    notes: list[str]


def estimate_eu_truck(origin: str) -> TransportEstimate:
    rng = EU_TRUCK.get(origin, (700, 950))
    cost = sum(rng) / 2
    return TransportEstimate(f"camión UE ({origin})", cost, 4, [])


def estimate_extra_eu(origin: str, container: bool, declared_value_eur: float,
                      fx_usd_eur: float = 0.92) -> TransportEstimate:
    cfg = EXTRA_EU.get(origin)
    if cfg is None:
        return TransportEstimate("extra-UE genérico", 2500, 25,
                                 [f"Origen {origin} no parametrizado."])
    rng = cfg["container"] if container else cfg["roro"]
    pick_usd = sum(rng) / 2
    shipping = pick_usd * fx_usd_eur
    insurance = declared_value_eur * 0.015
    port_fees = 475
    total = shipping + insurance + port_fees
    return TransportEstimate(
        "contenedor" if container else "RoRo", total, cfg["transit"],
        [f"USD {pick_usd:,.0f} × {fx_usd_eur:.3f}",
         f"Seguro 1.5%: {insurance:,.0f} €",
         f"Tasas portuarias: {port_fees:,.0f} €"]
    )


# ════════════════════════════════════════════════════════════════════
# 8. HOMOLOGACIÓN
# ════════════════════════════════════════════════════════════════════

EU_COUNTRIES = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
                "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
                "SI", "ES", "SE"}


@dataclass
class HomologationCost:
    total_eur: float
    breakdown: dict
    risk_provision_eur: float
    notes: list[str]


def estimate_homologation(origin: str, has_coc: bool, declared_value_eur: float,
                          is_premium: bool = False, is_us: bool = False,
                          gestoria: float = 350.0) -> HomologationCost:
    notes: list[str] = []
    breakdown: dict = {"tasa_trafico_9050": 99.77, "gestoria": gestoria, "placas": 25.0}
    risk = 0.0
    if origin in EU_COUNTRIES:
        breakdown["itv_ficha_reducida"] = 150.0
        if not has_coc:
            breakdown["coc_request"] = 200.0
            notes.append("Sin COC: pedir al fabricante 50-300€.")
    else:
        base_homol = 2500.0 if is_premium else 1500.0
        breakdown["homologacion_individual"] = base_homol
        breakdown["itv_ficha_completa"] = 250.0
        adapt = 1500.0 if is_us else 500.0
        breakdown["adaptaciones"] = adapt
        notes.append("Spec USA: faros DOT→E, intermitentes ámbar." if is_us
                     else "Spec GCC/AE: marcado E faros, antiniebla trasera.")
        risk = declared_value_eur * 0.15
        notes.append(f"Provisión riesgo homologación: {risk:,.0f} €. Verificar Euro 6d.")
    return HomologationCost(sum(breakdown.values()), breakdown, risk, notes)


# ════════════════════════════════════════════════════════════════════
# 9. REACONDICIONADO
# ════════════════════════════════════════════════════════════════════

@dataclass
class ReconditioningEstimate:
    total_eur: float
    breakdown: dict
    notes: list[str]


def estimate_reconditioning(v: Vehicle, is_premium: bool = False,
                            cosmetic: str = "average") -> ReconditioningEstimate:
    notes: list[str] = []
    bd: dict = {}
    if v.km < 60_000:
        mech = 220.0
    elif v.km < 120_000:
        mech = 600.0
    else:
        mech = 1300.0
    if is_premium and v.km > 100_000:
        mech += 1000
        notes.append("Premium >100k: provisión cadenas/EGR/turbos.")
    bd["mecanica_preventiva"] = mech
    if v.fuel == FuelType.DIESEL and v.km > 150_000:
        bd["dpf_adblue"] = 800.0
        notes.append("Diesel >150k: provisión DPF/AdBlue.")
    if v.fuel in (FuelType.HEV, FuelType.PHEV):
        bd["test_bateria_traccion"] = 100.0
    bd["neumaticos"] = 450.0 if v.age_years > 4 else 0.0
    bd["frenos"] = 320.0
    bd["distribucion"] = 600.0 if v.km > 110_000 else 0.0
    bd["estetica"] = {"good": 200.0, "average": 500.0, "poor": 950.0}.get(cosmetic, 500.0)
    bd["documentacion_llaves"] = 80.0
    sub = sum(bd.values())
    buf = sub * 0.15
    bd["buffer_imprevistos_15pct"] = buf
    return ReconditioningEstimate(sub + buf, bd, notes)


# ════════════════════════════════════════════════════════════════════
# 10. PRICER (sin scikit-learn — usamos mediana + ajuste por km/año)
# ════════════════════════════════════════════════════════════════════

@dataclass
class MarketStats:
    market: str
    n: int
    p25: float
    p50: float
    p75: float
    mean: float
    std: float
    fair_price: float
    notes: list[str]


def market_stats(comps: list[Comparable], target: Vehicle, market: str,
                 min_n: int = 5) -> Optional[MarketStats]:
    sample = [c for c in comps if c.market == market and not c.accident
              and c.price_eur > 0 and c.km >= 0]
    if len(sample) < min_n:
        return None
    prices = np.array([c.price_eur for c in sample], float)
    kms = np.array([c.km for c in sample], float)
    years = np.array([c.year for c in sample], float)
    p25, p50, p75 = np.percentile(prices, [25, 50, 75])
    notes: list[str] = []
    fair = float(p50)
    if len(sample) >= 6:
        # Regresión lineal robusta simple: ajuste por covarianza km y año
        try:
            X = np.column_stack([kms, years, np.ones(len(prices))])
            beta, *_ = np.linalg.lstsq(X, prices, rcond=None)
            fair = float(beta[0] * target.km + beta[1] * target.year + beta[2])
            fair = float(np.clip(fair, p25 * 0.85, p75 * 1.15))
            notes.append("Fair price ajustado por OLS (km, año).")
        except Exception as e:
            notes.append(f"OLS falló, fair=P50: {e}")
    else:
        notes.append("n<6: fair price = mediana.")
    return MarketStats(market, len(sample), float(p25), float(p50), float(p75),
                       float(prices.mean()), float(prices.std()), fair, notes)


# ════════════════════════════════════════════════════════════════════
# 11. ROTACIÓN
# ════════════════════════════════════════════════════════════════════

SEGMENT_DAYS = {
    "premium_german": 35, "premium_german_high": 55, "premium_other": 45,
    "exotic": 90, "suv_large": 50, "suv_compact": 30, "compact_mainstream": 25,
    "sedan_mainstream": 35, "city": 22, "ev_premium": 50, "ev_compact": 45,
    "phev": 55, "mpv_van": 45, "pickup": 40, "youngtimer": 75, "classic": 120,
}
PREMIUM_GERMAN = {"bmw", "mercedes", "mercedes-benz", "audi"}
PREMIUM_OTHER = {"volvo", "lexus", "jaguar", "land rover", "range rover",
                 "infiniti", "acura", "genesis"}
EXOTIC = {"porsche", "maserati", "ferrari", "lamborghini", "aston martin",
          "bentley", "rolls-royce", "mclaren"}
PICKUP_M = {"hilux", "ranger", "l200", "amarok", "navara", "d-max", "frontier"}
SUV_L = {"x5", "x6", "x7", "q7", "q8", "gle", "gls", "cayenne", "rx", "lx",
         "land cruiser", "patrol", "range rover", "discovery", "touareg"}
SUV_C = {"tiguan", "tucson", "sportage", "qashqai", "kuga", "cr-v", "rav4",
         "ateca", "kadjar", "captur", "hr-v", "yaris cross", "x1", "x3", "q3", "q5"}
CITY_M = {"polo", "ibiza", "yaris", "corsa", "208", "clio", "fiesta", "i10",
          "i20", "fabia", "panda", "up!", "fox", "twingo", "aygo", "c1", "108"}
COMPACT_M = {"golf", "focus", "astra", "megane", "civic", "leon", "i30", "mazda3",
             "auris", "corolla", "308", "1 series", "a3", "a-class"}


def _has(text: str, words: set) -> bool:
    return any(w in text.lower() for w in words)


def classify_segment(v: Vehicle) -> str:
    make = v.make.lower().strip()
    full = f"{v.model} {v.version or ''}".lower()
    if v.age_years >= 25: return "classic"
    if v.age_years >= 15: return "youngtimer"
    if v.fuel == FuelType.BEV:
        return "ev_premium" if make in PREMIUM_GERMAN | PREMIUM_OTHER | EXOTIC | {"tesla"} else "ev_compact"
    if v.fuel == FuelType.PHEV: return "phev"
    if make in EXOTIC: return "exotic"
    if _has(full, PICKUP_M): return "pickup"
    if _has(full, SUV_L): return "suv_large"
    if _has(full, SUV_C): return "suv_compact"
    if make in PREMIUM_GERMAN:
        if any(b in full for b in [" m3", " m4", " m5", " m8", "amg", " rs",
                                    " s3", " s4", " s5", " s6", " s8"]):
            return "premium_german_high"
        return "premium_german"
    if make in PREMIUM_OTHER: return "premium_other"
    if _has(full, CITY_M): return "city"
    if _has(full, COMPACT_M): return "compact_mainstream"
    return "sedan_mainstream"


@dataclass
class RotationEstimate:
    segment: str
    median_days: float
    mean_days: float
    p25_days: float
    p75_days: float
    p90_days: float
    velocity_score: int
    velocity_label: str
    prob_sell_within_30d: float
    prob_sell_within_60d: float
    prob_sell_within_90d: float
    notes: list[str]


def _velocity(median: float) -> tuple[int, str]:
    if median <= 25: return 1, "Muy rápida"
    if median <= 35: return 2, "Rápida"
    if median <= 50: return 3, "Normal"
    if median <= 75: return 4, "Lenta"
    return 5, "Muy lenta"


def estimate_rotation(v: Vehicle, sigma: float = 0.4,
                      override_days: float | None = None) -> RotationEstimate:
    seg = classify_segment(v)
    median = override_days if override_days is not None else SEGMENT_DAYS[seg]
    rng = np.random.default_rng(7)
    samples = rng.lognormal(mean=np.log(median), sigma=sigma, size=20000)
    p25, p50, p75, p90 = np.percentile(samples, [25, 50, 75, 90])
    score, label = _velocity(float(p50))
    notes = [f"Segmento: {seg} (mediana {median}d)."]
    if v.km > 200_000:
        notes.append("Km muy alto: rotación más lenta probable.")
    return RotationEstimate(
        seg, float(p50), float(samples.mean()), float(p25), float(p75), float(p90),
        score, label,
        float((samples <= 30).mean()), float((samples <= 60).mean()),
        float((samples <= 90).mean()), notes,
    )


# ════════════════════════════════════════════════════════════════════
# 12. RISK SCORE
# ════════════════════════════════════════════════════════════════════

@dataclass
class RiskScore:
    score: int
    label: str
    factors: dict[str, int]
    notes: list[str]


def compute_risk(v: Vehicle, origin: Origin, expected_days: float,
                 has_market_sample: bool) -> RiskScore:
    f: dict[str, int] = {}
    notes: list[str] = []
    if origin == Origin.EXTRA_EU:
        f["homologation"] = 25
        notes.append("Origen extra-UE: homologación individual; verificar Euro 6d.")
    elif not v.has_coc:
        f["homologation"] = 8
    else:
        f["homologation"] = 0
    if v.km < 30_000 and v.age_years > 5:
        f["mileage_rollback"] = 20
        notes.append("Km muy bajo para edad: sospecha rollback.")
    elif v.km < 50_000 and v.age_years > 7:
        f["mileage_rollback"] = 10
    else:
        f["mileage_rollback"] = 0
    dd = (v.declared_damages or "").lower()
    if "estructur" in dd:
        f["structural_damage"] = 35
        notes.append("Daño estructural declarado.")
    elif "siniestr" in dd or "accident" in dd:
        f["structural_damage"] = 18
    elif dd and "cosmétic" not in dd and "sin" not in dd:
        f["structural_damage"] = 6
    else:
        f["structural_damage"] = 0
    po = v.previous_owners or 0
    f["many_owners"] = 12 if po >= 5 else 6 if po >= 4 else 0
    f["no_service_book"] = 0 if v.has_service_book else 8
    f["low_liquidity"] = 12 if expected_days >= 90 else 6 if expected_days >= 60 else 0
    f["insufficient_market_data"] = 0 if has_market_sample else 15
    if not has_market_sample:
        notes.append("Sin comparables suficientes.")
    f["age_mileage"] = 10 if (v.age_years >= 12 and v.km > 200_000) else 0
    score = min(100, sum(f.values()))
    label = ("Crítico" if score >= 60 else "Alto" if score >= 35
             else "Medio" if score >= 15 else "Bajo")
    return RiskScore(score, label, f, notes)


# ════════════════════════════════════════════════════════════════════
# 13. SCORER
# ════════════════════════════════════════════════════════════════════

@dataclass
class CostBreakdown:
    purchase: float = 0.0
    auction_fees: float = 0.0
    transport: float = 0.0
    customs: float = 0.0
    iedmt: float = 0.0
    homologation: float = 0.0
    reconditioning: float = 0.0
    capital_cost: float = 0.0
    operational: float = 0.0
    homologation_risk_provision: float = 0.0
    total: float = 0.0


@dataclass
class SaleScenario:
    name: str
    label: str
    sale_price_eur: float
    days_to_sell: float
    margin_eur: float
    margin_pct: float
    margin_after_tax_eur: float
    annualized_roi_pct: float
    npv_eur: float


@dataclass
class Verdict:
    label: str
    margin_eur: float
    margin_pct: float
    margin_after_tax_eur: float
    expected_sale_eur: float
    cost_total_eur: float
    cost_breakdown: CostBreakdown
    market_stats_es: Optional[MarketStats]
    market_stats_de: Optional[MarketStats]
    monte_carlo: dict
    max_bid_eur: float
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    iedmt_detail: Optional[dict] = None
    customs_detail: Optional[dict] = None
    vat_detail: Optional[dict] = None
    reconditioning_detail: Optional[dict] = None
    homologation_detail: Optional[dict] = None
    transport_detail: Optional[dict] = None
    rotation: Optional[dict] = None
    risk: Optional[dict] = None
    scenarios: list[dict] = field(default_factory=list)
    annualized_roi_pct: float = 0.0
    recommended_sale_eur: float = 0.0
    summary: dict = field(default_factory=dict)


def _flag_vehicle(v: Vehicle) -> list[str]:
    flags = []
    if v.km < 30_000 and v.age_years > 5:
        flags.append("Sospecha rollback: <30k km con >5 años.")
    if v.previous_owners and v.previous_owners > 4:
        flags.append(f"{v.previous_owners} propietarios anteriores.")
    if v.declared_damages and "estructur" in v.declared_damages.lower():
        flags.append("Daños estructurales declarados.")
    if not v.has_service_book:
        flags.append("Sin libro de mantenimiento.")
    return flags


def _is_premium(v: Vehicle) -> bool:
    return v.make.lower() in {"bmw", "mercedes-benz", "mercedes", "audi", "porsche",
                              "lexus", "land rover", "range rover", "jaguar", "volvo",
                              "tesla", "maserati", "bentley", "ferrari", "lamborghini",
                              "aston martin"}


def _build_scenario(name: str, label: str, sale: float, days: float,
                    fixed_no_capital: float, capital_employed: float,
                    capital_cost_annual: float, income_tax_rate: float,
                    discount_rate: float = 0.08) -> SaleScenario:
    cap_cost = capital_employed * capital_cost_annual * (days / 365)
    total = fixed_no_capital + cap_cost
    margin = sale - total
    pct = margin / total if total > 0 else 0.0
    annualized = (margin / capital_employed) * (365 / days) if capital_employed > 0 and days > 0 else 0.0
    discount = 1 / ((1 + discount_rate) ** (days / 365))
    npv = (sale * discount) - fixed_no_capital - cap_cost
    after_tax = margin * (1 - income_tax_rate) if margin > 0 else margin
    return SaleScenario(name, label, sale, days, margin, pct, after_tax, annualized, npv)


def analyze(req: AnalysisRequest) -> Verdict:
    v = req.vehicle
    flags = _flag_vehicle(v)
    notes: list[str] = []

    purchase_eur = to_eur(req.purchase_price, req.purchase_currency,
                          req.fx_rate_to_eur if req.fx_rate_to_eur != 1.0 else None)
    auction_fees = 0.0
    if req.origin == Origin.EU_AUCTION:
        auction_fees = (purchase_eur * req.auction_fee_pct + req.auction_flat_fee) * 1.21
    cost = CostBreakdown(purchase=purchase_eur, auction_fees=auction_fees)

    if req.transport_eur is not None:
        transport_cost = req.transport_eur
        transport_detail = {"override": req.transport_eur}
    else:
        if req.origin == Origin.EXTRA_EU:
            est = estimate_extra_eu(v.origin_country, container=False, declared_value_eur=purchase_eur)
        else:
            est = estimate_eu_truck(v.origin_country)
        transport_cost = est.cost_eur
        transport_detail = {"mode": est.mode, "transit_days": est.transit_days, "notes": est.notes}
    cost.transport = transport_cost

    customs_detail: Optional[dict] = None
    if req.origin == Origin.EXTRA_EU:
        cb = compute_customs(purchase_eur, transport_cost * 0.7, purchase_eur * 0.015,
                             canary=req.canary_islands, historic=v.age_years >= 30)
        cost.customs = cb.total_eur
        customs_detail = {"cif": cb.cif_eur, "duty": cb.duty_eur, "vat": cb.vat_eur,
                          "dua": cb.dua_fee_eur, "inspection": cb.inspection_fee_eur,
                          "notes": cb.notes}

    fiscal_value = (purchase_eur * 1.25) / max(0.10, depreciation_coef(v.age_years))
    iedmt_res = compute_iedmt(v, fiscal_value, canary=req.canary_islands,
                              historic=v.age_years >= 30)
    cost.iedmt = iedmt_res.tax_eur
    iedmt_detail = {"rate": iedmt_res.rate, "base": iedmt_res.base_eur,
                    "tax": iedmt_res.tax_eur, "exemption": iedmt_res.exemption_reason,
                    "notes": iedmt_res.notes}

    is_us = v.origin_country == "US"
    hom = estimate_homologation(v.origin_country, v.has_coc, purchase_eur,
                                 _is_premium(v), is_us)
    cost.homologation = hom.total_eur
    cost.homologation_risk_provision = hom.risk_provision_eur
    homologation_detail = {"breakdown": hom.breakdown,
                           "risk_provision": hom.risk_provision_eur,
                           "notes": hom.notes}

    if req.reconditioning_eur is not None:
        cost.reconditioning = req.reconditioning_eur
        recond_detail = {"override": req.reconditioning_eur}
    else:
        rc = estimate_reconditioning(v, _is_premium(v))
        cost.reconditioning = rc.total_eur
        recond_detail = {"breakdown": rc.breakdown, "notes": rc.notes}

    stats_es = market_stats(req.comparables, v, "ES")
    stats_de = market_stats(req.comparables, v, "DE")
    if stats_es is None:
        notes.append("Muestra ES <5: veredicto sin solidez estadística.")
        expected_sale = purchase_eur * 1.25
    else:
        expected_sale = stats_es.fair_price

    rot = estimate_rotation(v, override_days=float(req.days_in_stock) if req.days_in_stock else None)
    rotation_detail = asdict(rot)

    operational = expected_sale * 0.025 + 30
    cost.operational = operational

    days_recommended = rot.median_days
    fixed_no_capital = (cost.purchase + cost.auction_fees + cost.transport + cost.customs
                       + cost.iedmt + cost.homologation + cost.reconditioning
                       + cost.operational + cost.homologation_risk_provision)
    capital_employed = fixed_no_capital
    cost.capital_cost = capital_employed * req.capital_cost_annual * (days_recommended / 365)
    cost.total = fixed_no_capital + cost.capital_cost

    if req.vat_regime == VATRegime.REBU:
        vat = rebu_vat(expected_sale, cost.total)
        net_revenue = expected_sale - vat.net_vat_to_pay
    elif req.vat_regime == VATRegime.GENERAL:
        sale_net = expected_sale / 1.21
        deductible = (cost.transport + cost.reconditioning + cost.operational) * 0.21 / 1.21
        vat = general_vat(sale_net, deductible)
        net_revenue = sale_net
        cost.total -= deductible
        fixed_no_capital -= deductible
    else:
        sale_net = expected_sale / 1.21
        vat_imp = customs_detail["vat"] if customs_detail else 0.0
        vat = general_vat(sale_net, vat_imp)
        cost.total -= vat_imp
        fixed_no_capital -= vat_imp
        net_revenue = sale_net

    if stats_es:
        rec_price = stats_es.fair_price
        quick_price = min(stats_es.p25 * 1.05, rec_price * 0.96)
        patient_price = max(stats_es.p75, rec_price * 1.04)
    else:
        rec_price = expected_sale
        quick_price = expected_sale * 0.93
        patient_price = expected_sale * 1.07

    scenarios = [
        _build_scenario("quick", "Venta rápida (P25×1.05)", quick_price,
                        max(15, rot.p25_days * 0.85), fixed_no_capital, capital_employed,
                        req.capital_cost_annual, req.income_tax_rate),
        _build_scenario("recommended", "Recomendada (precio justo)", rec_price,
                        rot.median_days, fixed_no_capital, capital_employed,
                        req.capital_cost_annual, req.income_tax_rate),
        _build_scenario("patient", "Paciente (P75)", patient_price, rot.p75_days,
                        fixed_no_capital, capital_employed, req.capital_cost_annual,
                        req.income_tax_rate),
    ]
    rec = scenarios[1]

    margin_eur = net_revenue - cost.total
    margin_pct = margin_eur / cost.total if cost.total > 0 else 0.0
    margin_after_tax = margin_eur * (1 - req.income_tax_rate) if margin_eur > 0 else margin_eur

    rng = np.random.default_rng(42)
    sigma_p = stats_es.std if stats_es else expected_sale * 0.08
    sales_mc = rng.normal(expected_sale, sigma_p, 1000)
    if stats_es:
        sales_mc = np.clip(sales_mc, stats_es.p25 * 0.95, stats_es.p75 * 1.15)
    days_mc = rng.lognormal(mean=np.log(rot.median_days), sigma=0.4, size=1000)
    cap_costs_mc = capital_employed * req.capital_cost_annual * (days_mc / 365)
    margins_mc = sales_mc - fixed_no_capital - cap_costs_mc
    mc = {
        "n": 1000,
        "expected_margin_eur": float(margins_mc.mean()),
        "std_margin_eur": float(margins_mc.std()),
        "p5_margin_eur": float(np.percentile(margins_mc, 5)),
        "p50_margin_eur": float(np.percentile(margins_mc, 50)),
        "p95_margin_eur": float(np.percentile(margins_mc, 95)),
        "prob_loss": float((margins_mc < 0).mean()),
        "prob_margin_above_1500": float((margins_mc >= 1500).mean()),
        "prob_margin_above_3000": float((margins_mc >= 3000).mean()),
        "var95_eur": float(np.percentile(margins_mc, 5)),
        "expected_days_to_sell": float(days_mc.mean()),
        "p90_days_to_sell": float(np.percentile(days_mc, 90)),
    }

    floor_sale = stats_es.p25 if stats_es else expected_sale * 0.92
    target_total = floor_sale / (1 + req.target_margin_pct)
    fixed_no_purch = cost.total - cost.purchase - cost.auction_fees
    auction_factor = 1 + req.auction_fee_pct * 1.21
    max_bid = max(0.0, (target_total - fixed_no_purch - req.auction_flat_fee * 1.21) / auction_factor)

    risk_obj = compute_risk(v, req.origin, rot.median_days, has_market_sample=stats_es is not None)

    if any("estructur" in f.lower() for f in flags):
        label = "⚫ VETO"
    elif risk_obj.score >= 60:
        label = "⚫ VETO (riesgo crítico)"
    elif req.origin == Origin.EXTRA_EU and not v.euro_norm:
        label = "🟡 AMARILLO (Euro no verificada)"
        flags.append("Verificar Euro 6d antes de comprar (extra-UE).")
    elif margin_pct >= 0.12 and margin_eur >= 1500 and risk_obj.score < 35:
        label = "🟢 VERDE"
    elif margin_pct >= 0.06 and risk_obj.score < 50:
        label = "🟡 AMARILLO"
    else:
        label = "🔴 ROJO"

    summary = {
        "vehicle": f"{v.make} {v.model} {v.version or ''} {v.year} · {v.km:,} km".strip(),
        "verdict": label,
        "recommended_sale_eur": rec.sale_price_eur,
        "expected_margin_eur": rec.margin_eur,
        "expected_days_to_sell": rec.days_to_sell,
        "annualized_roi_pct": rec.annualized_roi_pct,
        "max_bid_eur": max_bid,
        "risk_score": risk_obj.score,
        "risk_label": risk_obj.label,
        "velocity": rot.velocity_label,
    }

    return Verdict(
        label=label, margin_eur=margin_eur, margin_pct=margin_pct,
        margin_after_tax_eur=margin_after_tax, expected_sale_eur=expected_sale,
        cost_total_eur=cost.total, cost_breakdown=cost,
        market_stats_es=stats_es, market_stats_de=stats_de,
        monte_carlo=mc, max_bid_eur=max_bid, flags=flags, notes=notes,
        iedmt_detail=iedmt_detail, customs_detail=customs_detail,
        vat_detail={"regime": vat.regime, "charged": vat.vat_charged,
                    "deductible": vat.vat_deductible, "net_to_pay": vat.net_vat_to_pay,
                    "notes": vat.notes},
        reconditioning_detail=recond_detail, homologation_detail=homologation_detail,
        transport_detail=transport_detail, rotation=rotation_detail,
        risk={"score": risk_obj.score, "label": risk_obj.label,
              "factors": risk_obj.factors, "notes": risk_obj.notes},
        scenarios=[asdict(s) for s in scenarios],
        annualized_roi_pct=rec.annualized_roi_pct,
        recommended_sale_eur=rec.sale_price_eur, summary=summary,
    )


# ════════════════════════════════════════════════════════════════════
# 14. TELEGRAM
# ════════════════════════════════════════════════════════════════════

def _tg_esc(t: str) -> str:
    if t is None: return ""
    s = str(t)
    for ch in ("_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|",
                "{", "}", ".", "!"):
        s = s.replace(ch, "\\" + ch)
    return s


def _fmt_eur(n: Optional[float]) -> str:
    return "—" if n is None else f"{n:,.0f} €".replace(",", ".")


def format_telegram_message(v: dict, source_url: Optional[str] = None) -> str:
    s = v.get("summary", {}) or {}
    veh = s.get("vehicle", "Vehículo")
    label = s.get("verdict", v.get("label", "—"))
    lines = [
        f"*{_tg_esc(label)}* · {_tg_esc(veh)}", "",
        f"💰 Venta recomendada: *{_tg_esc(_fmt_eur(s.get('recommended_sale_eur')))}*",
        f"📈 Margen esperado: *{_tg_esc(_fmt_eur(s.get('expected_margin_eur')))}*",
        f"⏱  Rotación: *{_tg_esc(round(s.get('expected_days_to_sell') or 0))} días* \\({_tg_esc(s.get('velocity', '—'))}\\)",
        f"🎯 Puja máx: *{_tg_esc(_fmt_eur(s.get('max_bid_eur')))}*",
        f"📊 ROI an\\.: *{_tg_esc(round((s.get('annualized_roi_pct') or 0) * 100, 1))}%*",
        f"⚠️ Riesgo: *{_tg_esc(s.get('risk_label', '—'))}* \\({_tg_esc(s.get('risk_score', 0))}/100\\)",
    ]
    mc = v.get("monte_carlo", {}) or {}
    if mc:
        lines += ["", "_Monte Carlo \\(1000 sims\\)_",
                  f"  • Prob\\. pérdida: {_tg_esc(round((mc.get('prob_loss') or 0)*100, 1))}%",
                  f"  • VaR 95%: {_tg_esc(_fmt_eur(mc.get('var95_eur')))}"]
    flags = v.get("flags") or []
    if flags:
        lines += ["", "_Avisos:_"] + [f"  • {_tg_esc(f)}" for f in flags[:4]]
    if source_url:
        lines += ["", f"🔗 {_tg_esc(source_url)}"]
    return "\n".join(lines)


async def telegram_send(text: str, parse_mode: str = "MarkdownV2") -> dict:
    token = os.environ.get("CAR_ARBITRAGE_TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("CAR_ARBITRAGE_TELEGRAM_CHAT_ID")
    if not token or not chat:
        return {"ok": False, "error": "CAR_ARBITRAGE_TELEGRAM_* no configuradas."}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            r = await c.post(url, json={"chat_id": chat, "text": text,
                                        "parse_mode": parse_mode,
                                        "disable_web_page_preview": True})
            return {"ok": r.status_code == 200 and r.json().get("ok", False),
                    "response": r.json()}
        except Exception as e:
            return {"ok": False, "error": str(e)}


# ════════════════════════════════════════════════════════════════════
# 15. STORAGE (SQLite)
# ════════════════════════════════════════════════════════════════════

DB_PATH = os.environ.get("CAR_ARBITRAGE_DB", "car_arbitrage.sqlite3")
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
def db_conn(path: str = DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_analysis(req_dict: dict, verdict_dict: dict) -> int:
    v = req_dict.get("vehicle") or {}
    s = verdict_dict.get("summary") or {}
    rot = verdict_dict.get("rotation") or {}
    risk = verdict_dict.get("risk") or {}
    row = (
        time.time(), v.get("make"), v.get("model"), v.get("version"),
        v.get("year"), v.get("km"),
        (v.get("fuel") or "").lower() if v.get("fuel") else None,
        v.get("origin_country"), req_dict.get("origin"),
        req_dict.get("purchase_price"),
        s.get("recommended_sale_eur") or verdict_dict.get("expected_sale_eur"),
        s.get("max_bid_eur") or verdict_dict.get("max_bid_eur"),
        s.get("expected_margin_eur") or verdict_dict.get("margin_eur"),
        verdict_dict.get("margin_pct"), s.get("annualized_roi_pct"),
        risk.get("score"), s.get("verdict") or verdict_dict.get("label"),
        s.get("expected_days_to_sell") or rot.get("median_days"),
        rot.get("segment"),
        json.dumps(req_dict, default=str), json.dumps(verdict_dict, default=str),
    )
    with db_conn() as c:
        cur = c.execute("""INSERT INTO analyses
            (created_at, make, model, version, year, km, fuel, origin_country, origin,
             purchase_eur, expected_sale_eur, max_bid_eur, margin_eur, margin_pct,
             roi_annualized, risk_score, label, days_to_sell, segment,
             raw_request, raw_verdict)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
        return cur.lastrowid


def list_recent(limit: int = 20, label_prefix: Optional[str] = None) -> list[dict]:
    with db_conn() as c:
        if label_prefix:
            rows = c.execute("SELECT * FROM analyses WHERE label LIKE ? ORDER BY created_at DESC LIMIT ?",
                             (label_prefix + "%", limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM analyses ORDER BY created_at DESC LIMIT ?",
                             (limit,)).fetchall()
    return [dict(r) for r in rows]


def top_opportunities(min_margin: float = 1500, max_risk: int = 35,
                      limit: int = 20) -> list[dict]:
    with db_conn() as c:
        rows = c.execute("""SELECT id, created_at, make, model, version, year, km,
                                  purchase_eur, expected_sale_eur, max_bid_eur,
                                  margin_eur, margin_pct, roi_annualized,
                                  risk_score, label, days_to_sell, segment
                           FROM analyses
                           WHERE margin_eur >= ? AND (risk_score IS NULL OR risk_score <= ?)
                             AND label LIKE '🟢%'
                           ORDER BY margin_eur DESC LIMIT ?""",
                         (min_margin, max_risk, limit)).fetchall()
    return [dict(r) for r in rows]


def record_sale_outcome(aid: int, actual_sale: float, actual_days: float,
                        notes: str = "") -> int:
    with db_conn() as c:
        a = c.execute("SELECT purchase_eur FROM analyses WHERE id = ?", (aid,)).fetchone()
        if not a:
            raise ValueError(f"analysis {aid} not found")
        actual_margin = actual_sale - (a["purchase_eur"] or 0)
        cur = c.execute("""INSERT INTO sale_outcomes
            (analysis_id, sold_at, actual_sale_eur, actual_days_to_sell,
             actual_margin_eur, notes) VALUES (?,?,?,?,?,?)""",
            (aid, time.time(), actual_sale, actual_days, actual_margin, notes))
        return cur.lastrowid


# ════════════════════════════════════════════════════════════════════
# 16. FastAPI app
# ════════════════════════════════════════════════════════════════════

app = FastAPI(title="Car Arbitrage Pro (solo)", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _ser(obj: Any) -> Any:
    if is_dataclass(obj):
        return {k: _ser(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _ser(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_ser(x) for x in obj]
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    return obj


@app.get("/health")
async def health():
    return {"status": "ok", "service": "car_arbitrage_solo"}


@app.post("/analyze")
async def analyze_endpoint(req: AnalysisRequest, save: bool = True):
    try:
        verdict = analyze(req)
        out = _ser(verdict)
        if save:
            try:
                aid = save_analysis(req.model_dump(), out)
                out["_analysis_id"] = aid
            except Exception:
                pass
        return out
    except Exception as e:
        raise HTTPException(500, f"analyze failed: {e}")


class NotifyRequest(BaseModel):
    verdict: dict
    source_url: Optional[str] = None


@app.post("/notify")
async def notify_endpoint(req: NotifyRequest):
    text = format_telegram_message(req.verdict, source_url=req.source_url)
    return await telegram_send(text)


@app.get("/opportunities")
async def opportunities(min_margin: float = 1500, max_risk: int = 35, limit: int = 20):
    return {"results": top_opportunities(min_margin, max_risk, limit)}


@app.get("/recent")
async def recent(limit: int = 20):
    return {"results": list_recent(limit)}


class OutcomeRequest(BaseModel):
    analysis_id: int
    actual_sale_eur: float
    actual_days_to_sell: float
    notes: str = ""


@app.post("/outcome")
async def outcome(req: OutcomeRequest):
    oid = record_sale_outcome(req.analysis_id, req.actual_sale_eur,
                              req.actual_days_to_sell, req.notes)
    return {"outcome_id": oid}


# ════════════════════════════════════════════════════════════════════
# 17. EMBEDDED FRONTEND
# ════════════════════════════════════════════════════════════════════

FRONTEND_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Car Arbitrage Pro</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}.num{font-variant-numeric:tabular-nums}</style>
</head>
<body class="bg-slate-50 text-slate-800">
<div id="root"></div>
<script type="text/babel">
const {useState} = React;
const fmtEur=(n)=>n==null||isNaN(n)?"—":new Intl.NumberFormat("es-ES",{style:"currency",currency:"EUR",maximumFractionDigits:0}).format(n);
const fmtPct=(n)=>n==null||isNaN(n)?"—":(n*100).toFixed(1)+"%";
const FUELS=[["gasoline","Gasolina"],["diesel","Diésel"],["hev","HEV"],["mhev","MHEV"],["phev","PHEV"],["bev","BEV"],["lpg","GLP"],["cng","GNC"]];
const ORIGINS=[["eu_auction","Subasta UE (OpenLane/BCA)"],["eu_retail_pro","Retail UE pro"],["eu_retail_pro_rebu","Retail UE pro REBU"],["eu_retail_private","Retail UE particular"],["extra_eu","Extra-UE (Dubái/JP/US/UK)"]];
const VAT=[["rebu","REBU"],["general","General 21%"],["import_extra_eu","Importación extra-UE"]];

function App(){
  const [tab,setTab]=useState("vehicle");
  const [loading,setLoading]=useState(false);
  const [verdict,setVerdict]=useState(null);
  const [error,setError]=useState(null);
  const [v,setV]=useState({make:"BMW",model:"Serie 3",version:"320d",year:2020,km:95000,fuel:"diesel",power_cv:190,co2_wltp:145,euro_norm:"6d",origin_country:"DE",has_coc:true,has_service_book:true,previous_owners:2,declared_damages:""});
  const [req,setReq]=useState({origin:"eu_auction",purchase_price:14500,purchase_currency:"EUR",fx_rate_to_eur:1,auction_fee_pct:0.055,auction_flat_fee:150,target_margin_pct:0.12,vat_regime:"rebu",canary_islands:false,days_in_stock:35,capital_cost_annual:0.08,income_tax_rate:0.25});
  const [comps,setComps]=useState([
    {source:"coches.net",market:"ES",price_eur:22500,km:88000,year:2020},
    {source:"coches.net",market:"ES",price_eur:21000,km:105000,year:2020},
    {source:"coches.net",market:"ES",price_eur:23500,km:75000,year:2021},
    {source:"autoscout24.es",market:"ES",price_eur:22000,km:92000,year:2020},
    {source:"autoscout24.es",market:"ES",price_eur:24000,km:70000,year:2021},
    {source:"mobile.de",market:"DE",price_eur:19500,km:88000,year:2020},
    {source:"mobile.de",market:"DE",price_eur:18900,km:96000,year:2020},
  ]);
  const upd=(s,k)=>(e)=>{const val=e.target.type==="checkbox"?e.target.checked:e.target.type==="number"?Number(e.target.value):e.target.value;s(p=>({...p,[k]:val}));};
  const analyze=async()=>{
    setLoading(true);setError(null);setVerdict(null);
    try{
      const r=await fetch("/analyze",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...req,vehicle:v,comparables:comps})});
      if(!r.ok)throw new Error(await r.text());
      setVerdict(await r.json());setTab("verdict");
    }catch(e){setError(String(e));}finally{setLoading(false);}
  };
  const notify=async()=>{
    if(!verdict)return;
    const r=await fetch("/notify",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({verdict})});
    const j=await r.json();
    alert(j.ok?"✓ Telegram enviado":"✗ "+JSON.stringify(j));
  };
  const Tab=({id,children})=><button onClick={()=>setTab(id)} className={"px-4 py-2 rounded-t-lg font-medium "+(tab===id?"bg-white border-b-2 border-blue-600 text-blue-700":"text-slate-500")}>{children}</button>;
  const F=({label,children,hint})=><label className="block text-sm"><span className="text-slate-600">{label}</span>{children}{hint&&<span className="block text-xs text-slate-400 mt-0.5">{hint}</span>}</label>;
  const I=(p)=><input {...p} className="mt-1 w-full rounded border-slate-300 border px-2 py-1.5 num focus:ring-2 focus:ring-blue-500 outline-none"/>;
  const S=({children,...p})=><select {...p} className="mt-1 w-full rounded border-slate-300 border px-2 py-1.5 bg-white">{children}</select>;
  return (
    <div className="max-w-6xl mx-auto p-4">
      <header className="mb-6"><h1 className="text-3xl font-bold">🚗 Car Arbitrage Pro</h1><p className="text-sm text-slate-500">IEDMT · IVA/REBU · Aduanas extra-UE · Comparables · Monte Carlo · Telegram</p></header>
      <div className="border-b border-slate-200 mb-4 flex gap-1">
        <Tab id="vehicle">1. Vehículo</Tab><Tab id="purchase">2. Compra</Tab><Tab id="market">3. Mercado</Tab><Tab id="verdict">4. Veredicto</Tab>
      </div>
      {tab==="vehicle"&&(<div className="bg-white p-5 rounded-lg shadow-sm grid grid-cols-2 md:grid-cols-3 gap-4">
        <F label="Marca"><I value={v.make} onChange={upd(setV,"make")}/></F>
        <F label="Modelo"><I value={v.model} onChange={upd(setV,"model")}/></F>
        <F label="Versión"><I value={v.version||""} onChange={upd(setV,"version")}/></F>
        <F label="Año"><I type="number" value={v.year} onChange={upd(setV,"year")}/></F>
        <F label="Km"><I type="number" value={v.km} onChange={upd(setV,"km")}/></F>
        <F label="Combustible"><S value={v.fuel} onChange={upd(setV,"fuel")}>{FUELS.map(([id,l])=><option key={id} value={id}>{l}</option>)}</S></F>
        <F label="CV"><I type="number" value={v.power_cv||""} onChange={upd(setV,"power_cv")}/></F>
        <F label="CO₂ WLTP" hint="Clave para IEDMT"><I type="number" value={v.co2_wltp||""} onChange={upd(setV,"co2_wltp")}/></F>
        <F label="Norma Euro"><I value={v.euro_norm||""} onChange={upd(setV,"euro_norm")}/></F>
        <F label="País origen"><I value={v.origin_country} onChange={upd(setV,"origin_country")}/></F>
        <F label="Propietarios"><I type="number" value={v.previous_owners||0} onChange={upd(setV,"previous_owners")}/></F>
        <F label="Daños declarados"><I value={v.declared_damages||""} onChange={upd(setV,"declared_damages")}/></F>
        <label className="flex items-center gap-2 mt-6"><input type="checkbox" checked={v.has_coc} onChange={upd(setV,"has_coc")}/><span className="text-sm">Tiene COC</span></label>
        <label className="flex items-center gap-2 mt-6"><input type="checkbox" checked={v.has_service_book} onChange={upd(setV,"has_service_book")}/><span className="text-sm">Libro mantenimiento</span></label>
      </div>)}
      {tab==="purchase"&&(<div className="bg-white p-5 rounded-lg shadow-sm grid grid-cols-2 md:grid-cols-3 gap-4">
        <F label="Origen / canal"><S value={req.origin} onChange={upd(setReq,"origin")}>{ORIGINS.map(([id,l])=><option key={id} value={id}>{l}</option>)}</S></F>
        <F label="Régimen IVA"><S value={req.vat_regime} onChange={upd(setReq,"vat_regime")}>{VAT.map(([id,l])=><option key={id} value={id}>{l}</option>)}</S></F>
        <F label="Canarias"><S value={req.canary_islands} onChange={(e)=>setReq(s=>({...s,canary_islands:e.target.value==="true"}))}><option value="false">No</option><option value="true">Sí (IGIC 7%)</option></S></F>
        <F label="Precio adjudicación"><I type="number" value={req.purchase_price} onChange={upd(setReq,"purchase_price")}/></F>
        <F label="Moneda"><S value={req.purchase_currency} onChange={upd(setReq,"purchase_currency")}><option>EUR</option><option>USD</option><option>AED</option><option>GBP</option><option>JPY</option></S></F>
        <F label="FX a EUR" hint="1 = default"><I type="number" step="0.0001" value={req.fx_rate_to_eur} onChange={upd(setReq,"fx_rate_to_eur")}/></F>
        <F label="Comisión subasta %"><I type="number" step="0.001" value={req.auction_fee_pct} onChange={upd(setReq,"auction_fee_pct")}/></F>
        <F label="Fee fijo (€)"><I type="number" value={req.auction_flat_fee} onChange={upd(setReq,"auction_flat_fee")}/></F>
        <F label="Margen objetivo %"><I type="number" step="0.01" value={req.target_margin_pct} onChange={upd(setReq,"target_margin_pct")}/></F>
        <F label="Días stock"><I type="number" value={req.days_in_stock} onChange={upd(setReq,"days_in_stock")}/></F>
        <F label="Coste capital anual"><I type="number" step="0.01" value={req.capital_cost_annual} onChange={upd(setReq,"capital_cost_annual")}/></F>
        <F label="Tipo IRPF/IS"><I type="number" step="0.01" value={req.income_tax_rate} onChange={upd(setReq,"income_tax_rate")}/></F>
      </div>)}
      {tab==="market"&&(<div className="bg-white p-5 rounded-lg shadow-sm">
        <h3 className="font-semibold mb-2">Comparables ({comps.length})</h3>
        <p className="text-xs text-slate-500 mb-3">Mín 5 ES recomendado.</p>
        <table className="w-full text-sm"><thead className="text-left text-slate-500"><tr><th>Fuente</th><th>Mercado</th><th>Precio €</th><th>Km</th><th>Año</th><th></th></tr></thead><tbody>
          {comps.map((c,i)=>(<tr key={i} className="border-t">
            <td><input className="w-32 px-1 py-1" value={c.source} onChange={(e)=>setComps(cs=>cs.map((x,j)=>j===i?{...x,source:e.target.value}:x))}/></td>
            <td><select className="px-1 py-1" value={c.market} onChange={(e)=>setComps(cs=>cs.map((x,j)=>j===i?{...x,market:e.target.value}:x))}><option>ES</option><option>DE</option><option>FR</option><option>IT</option><option>AE</option></select></td>
            <td><input type="number" className="w-24 px-1 py-1 num" value={c.price_eur} onChange={(e)=>setComps(cs=>cs.map((x,j)=>j===i?{...x,price_eur:Number(e.target.value)}:x))}/></td>
            <td><input type="number" className="w-24 px-1 py-1 num" value={c.km} onChange={(e)=>setComps(cs=>cs.map((x,j)=>j===i?{...x,km:Number(e.target.value)}:x))}/></td>
            <td><input type="number" className="w-20 px-1 py-1 num" value={c.year} onChange={(e)=>setComps(cs=>cs.map((x,j)=>j===i?{...x,year:Number(e.target.value)}:x))}/></td>
            <td><button onClick={()=>setComps(cs=>cs.filter((_,j)=>j!==i))} className="text-red-600 text-xs">×</button></td>
          </tr>))}
        </tbody></table>
        <button onClick={()=>setComps(cs=>[...cs,{source:"manual",market:"ES",price_eur:0,km:0,year:new Date().getFullYear()-2}])} className="mt-3 px-3 py-1.5 bg-slate-100 rounded text-sm">+ Añadir</button>
      </div>)}
      {tab==="verdict"&&(<div className="bg-white p-5 rounded-lg shadow-sm">
        {!verdict&&!loading&&<p className="text-slate-500">Pulsa "Analizar" abajo.</p>}
        {loading&&<p>Calculando…</p>}
        {error&&<pre className="text-red-600 text-xs whitespace-pre-wrap">{error}</pre>}
        {verdict&&<V v={verdict}/>}
      </div>)}
      <div className="mt-6 flex items-center gap-3 flex-wrap">
        <button onClick={analyze} disabled={loading} className="px-6 py-2.5 bg-blue-600 text-white rounded font-medium disabled:opacity-50">{loading?"Analizando…":"Analizar rentabilidad"}</button>
        {verdict&&<button onClick={notify} className="px-4 py-2.5 bg-cyan-600 text-white rounded font-medium">📨 Notificar Telegram</button>}
        {verdict&&<span className={"text-2xl font-bold "+vc(verdict.label)}>{verdict.label}</span>}
        {verdict&&<span className="text-sm text-slate-500">Margen {fmtEur(verdict.margin_eur)} ({fmtPct(verdict.margin_pct)})</span>}
      </div>
    </div>
  );
}
function vc(l){if(!l)return"";if(l.startsWith("🟢"))return"text-green-600";if(l.startsWith("🟡"))return"text-amber-600";if(l.startsWith("🔴"))return"text-red-600";return"text-slate-700";}
function V({v}){
  const cb=v.cost_breakdown||{};
  const rot=v.rotation||{};
  const risk=v.risk||{};
  const sc=v.scenarios||[];
  return (<div className="space-y-5">
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
      <St label="Venta recom." value={fmtEur(v.recommended_sale_eur)} accent/>
      <St label="Margen €" value={fmtEur(v.margin_eur)} accent/>
      <St label="Margen %" value={fmtPct(v.margin_pct)}/>
      <St label="ROI an." value={fmtPct(v.annualized_roi_pct)} accent/>
      <St label="Días vender" value={(rot.median_days||0).toFixed(0)+"d"}/>
      <St label="Velocidad" value={rot.velocity_label||"—"}/>
      <St label="Riesgo" value={`${risk.label||"—"} (${risk.score||0}/100)`}/>
      <St label="Puja máx" value={fmtEur(v.max_bid_eur)} accent/>
      <St label="Coste total" value={fmtEur(v.cost_total_eur)}/>
      <St label="Margen post-IRPF" value={fmtEur(v.margin_after_tax_eur)}/>
      <St label="Prob pérdida" value={fmtPct(v.monte_carlo?.prob_loss)}/>
      <St label="VaR 95%" value={fmtEur(v.monte_carlo?.var95_eur)}/>
    </div>
    {sc.length>0&&(<div><h3 className="font-semibold mb-2">Escenarios de venta</h3>
      <div className="grid md:grid-cols-3 gap-3">
        {sc.map((s,i)=>(<div key={i} className={"rounded-lg p-4 border "+(s.name==="recommended"?"border-blue-300 bg-blue-50":"border-slate-200 bg-white")}>
          <div className="text-xs uppercase text-slate-500">{s.name}</div>
          <div className="font-semibold">{s.label}</div>
          <div className="mt-2 num text-2xl font-bold">{fmtEur(s.sale_price_eur)}</div>
          <div className="text-sm mt-2 grid grid-cols-2 gap-x-2">
            <span className="text-slate-500">Días:</span><span className="text-right num">{(s.days_to_sell||0).toFixed(0)}</span>
            <span className="text-slate-500">Margen:</span><span className="text-right num font-medium">{fmtEur(s.margin_eur)}</span>
            <span className="text-slate-500">ROI an.:</span><span className="text-right num font-medium">{fmtPct(s.annualized_roi_pct)}</span>
            <span className="text-slate-500">NPV:</span><span className="text-right num">{fmtEur(s.npv_eur)}</span>
          </div>
        </div>))}
      </div>
    </div>)}
    {risk.factors&&(<details><summary className="font-semibold cursor-pointer">Risk score · {risk.label} ({risk.score}/100)</summary>
      <table className="w-full text-sm mt-2"><tbody>{Object.entries(risk.factors).map(([k,val])=><tr key={k} className="border-t"><td>{k}</td><td className="text-right num">{val}</td></tr>)}</tbody></table>
    </details>)}
    <details open><summary className="font-semibold cursor-pointer">Desglose costes</summary>
      <table className="w-full text-sm mt-2"><tbody>
        <Row k="Adquisición" v={cb.purchase}/>
        <Row k="Comisión subasta" v={cb.auction_fees}/>
        <Row k="Transporte" v={cb.transport}/>
        <Row k="Aduanas" v={cb.customs}/>
        <Row k="IEDMT" v={cb.iedmt}/>
        <Row k="Homologación" v={cb.homologation}/>
        <Row k="Reacondicionado" v={cb.reconditioning}/>
        <Row k="Coste capital" v={cb.capital_cost}/>
        <Row k="Operativos" v={cb.operational}/>
        <Row k="Provisión riesgo extra-UE" v={cb.homologation_risk_provision}/>
        <Row k="TOTAL" v={cb.total} bold/>
      </tbody></table>
    </details>
    <details><summary className="font-semibold cursor-pointer">IEDMT</summary><pre className="text-xs bg-slate-50 p-2 rounded overflow-x-auto">{JSON.stringify(v.iedmt_detail,null,2)}</pre></details>
    {v.customs_detail&&<details><summary className="font-semibold cursor-pointer">Aduanas</summary><pre className="text-xs bg-slate-50 p-2 rounded overflow-x-auto">{JSON.stringify(v.customs_detail,null,2)}</pre></details>}
    <details><summary className="font-semibold cursor-pointer">IVA / régimen</summary><pre className="text-xs bg-slate-50 p-2 rounded overflow-x-auto">{JSON.stringify(v.vat_detail,null,2)}</pre></details>
    <details><summary className="font-semibold cursor-pointer">Mercado ES / DE</summary><div className="grid md:grid-cols-2 gap-4 mt-2 text-xs">
      <div><strong>ES:</strong><pre className="bg-slate-50 p-2 rounded overflow-x-auto">{JSON.stringify(v.market_stats_es,null,2)}</pre></div>
      <div><strong>DE:</strong><pre className="bg-slate-50 p-2 rounded overflow-x-auto">{JSON.stringify(v.market_stats_de,null,2)}</pre></div>
    </div></details>
    <details><summary className="font-semibold cursor-pointer">Monte Carlo</summary><pre className="text-xs bg-slate-50 p-2 rounded">{JSON.stringify(v.monte_carlo,null,2)}</pre></details>
  </div>);
}
function St({label,value,accent}){return <div className={"rounded p-3 "+(accent?"bg-blue-50 border border-blue-200":"bg-slate-50")}><div className="text-xs text-slate-500">{label}</div><div className="text-lg font-semibold num">{value}</div></div>;}
function Row({k,v,bold}){return <tr className={"border-t "+(bold?"font-semibold":"")}><td className="py-1">{k}</td><td className="py-1 text-right num">{fmtEur(v)}</td></tr>;}
ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
</script>
</body></html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(FRONTEND_HTML)


# ════════════════════════════════════════════════════════════════════
# 18. SELF-TESTS (run on startup)
# ════════════════════════════════════════════════════════════════════

def run_self_tests() -> None:
    print("[self-test] Ejecutando…", flush=True)
    # IEDMT
    assert iedmt_rate(100) == 0.0
    assert iedmt_rate(140) == 0.0475
    assert iedmt_rate(180) == 0.0975
    assert iedmt_rate(210) == 0.1475
    assert iedmt_rate(140, canary=True) == 0.0375
    assert depreciation_coef(50) == 0.10

    # REBU
    r = rebu_vat(20000, 15000)
    assert abs(r.vat_charged - 867.768) < 1
    r0 = rebu_vat(10000, 12000)
    assert r0.vat_charged == 0.0

    # Customs Dubai
    cb = compute_customs(30000, 2000, 450)
    assert abs(cb.cif_eur - 32450) < 1
    assert abs(cb.duty_eur - 3245) < 1

    # Smoke flow
    v = Vehicle(make="BMW", model="Serie 3", version="320d", year=2020, km=95000,
                fuel=FuelType.DIESEL, power_cv=190, co2_wltp=145, euro_norm="6d",
                origin_country="DE", has_coc=True, has_service_book=True, previous_owners=2)
    comps = [
        Comparable(source="coches.net", market="ES", price_eur=22500, km=88000, year=2020),
        Comparable(source="coches.net", market="ES", price_eur=21000, km=105000, year=2020),
        Comparable(source="coches.net", market="ES", price_eur=23500, km=75000, year=2021),
        Comparable(source="autoscout24.es", market="ES", price_eur=22000, km=92000, year=2020),
        Comparable(source="autoscout24.es", market="ES", price_eur=24000, km=70000, year=2021),
    ]
    req = AnalysisRequest(vehicle=v, origin=Origin.EU_AUCTION, purchase_price=14500,
                          vat_regime=VATRegime.REBU, comparables=comps)
    verdict = analyze(req)
    assert verdict.label.startswith(("🟢", "🟡", "🔴", "⚫"))
    assert len(verdict.scenarios) == 3
    assert verdict.market_stats_es is not None
    print(f"[self-test] OK · BMW 320d → {verdict.label} margen {verdict.margin_eur:,.0f} €", flush=True)


# ════════════════════════════════════════════════════════════════════
# 19. MAIN
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    run_self_tests()
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    print("\n" + "═" * 60, flush=True)
    print(f"  Car Arbitrage Pro arrancando en http://localhost:{port}", flush=True)
    print(f"  Pulsa Ctrl+C para parar.", flush=True)
    print("═" * 60 + "\n", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
