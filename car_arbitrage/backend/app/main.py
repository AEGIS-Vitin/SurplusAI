"""FastAPI app: análisis de rentabilidad y búsqueda de oportunidades."""
from __future__ import annotations
import asyncio
from dataclasses import asdict, is_dataclass
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.core import scorer
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
async def analyze_endpoint(req: AnalysisRequest):
    try:
        verdict = scorer.analyze(req)
        return _serialize(verdict)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"analyze failed: {e}")


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
        scrapers.append(s); tasks.append(s.search(query))
    if "autoscout24.es" in req.sources:
        s = AutoScout24Scraper(country="es")
        scrapers.append(s); tasks.append(s.search(query))
    if "autoscout24.de" in req.sources:
        s = AutoScout24Scraper(country="de")
        scrapers.append(s); tasks.append(s.search(query))
    if "mobile.de" in req.sources:
        s = MobileDeScraper()
        scrapers.append(s); tasks.append(s.search(query))
    if "dubizzle" in req.sources:
        s = DubizzleScraper()
        scrapers.append(s); tasks.append(s.search(query))
    if "openlane" in req.sources:
        s = OpenLaneScraper()
        scrapers.append(s); tasks.append(s.search(query))

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
