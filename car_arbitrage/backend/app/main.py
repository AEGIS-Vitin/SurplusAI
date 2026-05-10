"""FastAPI app: análisis de rentabilidad y búsqueda de oportunidades."""
from __future__ import annotations

import asyncio
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.core import notifier_telegram, scorer, storage
from app.models.vehicle import AnalysisRequest, Comparable
from app.scrapers.autoscout24 import AutoScout24Scraper
from app.scrapers.coches_net import CochesNetScraper
from app.scrapers.dubizzle import DubizzleScraper
from app.scrapers.mobile_de import MobileDeScraper
from app.scrapers.openlane import OpenLaneScraper

app = FastAPI(title="Car Arbitrage Pro", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _serialize(obj: Any) -> Any:
    if is_dataclass(obj):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(x) for x in obj]
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    return obj


@app.get("/health")
async def health():
    return {"status": "ok", "service": "car_arbitrage"}


@app.post("/analyze")
async def analyze_endpoint(req: AnalysisRequest, save: bool = True):
    try:
        verdict = scorer.analyze(req)
        out = _serialize(verdict)
        if save:
            try:
                aid = storage.save_analysis(req.model_dump(), out)
                out["_analysis_id"] = aid
            except Exception:
                pass
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"analyze failed: {e}")


class NotifyRequest(BaseModel):
    verdict: dict
    source_url: str | None = None
    only_if_green: bool = False
    min_margin_eur: float = 0.0


@app.post("/notify")
async def notify_endpoint(req: NotifyRequest):
    """Envía un veredicto al chat de Telegram configurado."""
    return await notifier_telegram.notify_verdict(
        req.verdict, source_url=req.source_url,
        only_if_green=req.only_if_green, min_margin_eur=req.min_margin_eur,
    )


@app.get("/opportunities")
async def opportunities_endpoint(min_margin: float = 1500, max_risk: int = 35, limit: int = 20):
    """Top oportunidades verdes históricas guardadas en SQLite."""
    return {"results": storage.top_opportunities(min_margin, max_risk, limit)}


@app.get("/recent")
async def recent_endpoint(limit: int = 20, label_prefix: str | None = None):
    return {"results": storage.list_recent(limit, label_prefix)}


class OutcomeRequest(BaseModel):
    analysis_id: int
    actual_sale_eur: float
    actual_days_to_sell: float
    notes: str = ""


@app.post("/outcome")
async def outcome_endpoint(req: OutcomeRequest):
    oid = storage.record_sale_outcome(
        req.analysis_id, req.actual_sale_eur, req.actual_days_to_sell, req.notes,
    )
    return {"outcome_id": oid, "calibration": storage.calibration_stats()}


@app.get("/calibration")
async def calibration_endpoint():
    return storage.calibration_stats()


class SearchRequest(BaseModel):
    make: str
    model: str
    year_from: int | None = None
    year_to: int | None = None
    km_max: int | None = None
    sources: list[Literal["coches.net", "autoscout24.es", "autoscout24.de", "mobile.de", "dubizzle", "openlane"]] = [
        "coches.net", "autoscout24.es", "mobile.de", "autoscout24.de"
    ]


@app.post("/search")
async def search_endpoint(req: SearchRequest):
    """Búsqueda multi-portal. Devuelve listings normalizados."""
    query = req.model_dump()
    tasks = []
    scrapers = []

    if "coches.net" in req.sources:
        s = CochesNetScraper()
        scrapers.append(s)
        tasks.append(s.search(query))
    if "autoscout24.es" in req.sources:
        s = AutoScout24Scraper(country="es")
        scrapers.append(s)
        tasks.append(s.search(query))
    if "autoscout24.de" in req.sources:
        s = AutoScout24Scraper(country="de")
        scrapers.append(s)
        tasks.append(s.search(query))
    if "mobile.de" in req.sources:
        s = MobileDeScraper()
        scrapers.append(s)
        tasks.append(s.search(query))
    if "dubizzle" in req.sources:
        s = DubizzleScraper()
        scrapers.append(s)
        tasks.append(s.search(query))
    if "openlane" in req.sources:
        s = OpenLaneScraper()
        scrapers.append(s)
        tasks.append(s.search(query))

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await asyncio.gather(*(s.close() for s in scrapers), return_exceptions=True)

    out = {"results_by_source": {}, "errors": []}
    for s, r in zip(scrapers, results):
        if isinstance(r, Exception):
            out["errors"].append({"source": s.name, "error": str(r)})
            out["results_by_source"][s.name] = []
        else:
            out["results_by_source"][s.name] = [_serialize(x) for x in r]
    return out


class CombinedRequest(BaseModel):
    analysis: AnalysisRequest
    auto_fetch_comparables: bool = False


@app.post("/analyze-with-fetch")
async def analyze_with_fetch(req: CombinedRequest):
    """Analiza y opcionalmente autocompleta comparables desde scrapers ES/DE."""
    if req.auto_fetch_comparables:
        sr = SearchRequest(
            make=req.analysis.vehicle.make,
            model=req.analysis.vehicle.model,
            year_from=max(1980, req.analysis.vehicle.year - 1),
            year_to=req.analysis.vehicle.year + 1,
            km_max=int(req.analysis.vehicle.km * 1.25),
            sources=["coches.net", "autoscout24.es", "mobile.de", "autoscout24.de"],
        )
        scraped = await search_endpoint(sr)
        comps: list[Comparable] = list(req.analysis.comparables)
        for src, listings in scraped["results_by_source"].items():
            market = "ES" if (".es" in src or "coches" in src) else "DE"
            for li in listings:
                if li.get("price_eur") and li.get("year") and li.get("km") is not None:
                    comps.append(Comparable(
                        source=src, market=market,
                        price_eur=float(li["price_eur"]),
                        km=int(li["km"]),
                        year=int(li["year"]),
                        url=li.get("url"),
                    ))
        req.analysis.comparables = comps
    verdict = scorer.analyze(req.analysis)
    return _serialize(verdict)


# Serve frontend SPA (single origin → no CORS surprises)
_FRONTEND_DIR = Path(os.environ.get(
    "CAR_ARBITRAGE_FRONTEND_DIR",
    str(Path(__file__).resolve().parent.parent.parent / "frontend"),
))
if _FRONTEND_DIR.is_dir():
    @app.get("/")
    async def serve_index() -> FileResponse:
        return FileResponse(_FRONTEND_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR)), name="static")
