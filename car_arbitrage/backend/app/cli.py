"""CLI Typer para Car Arbitrage Pro.

Uso típico:
  python -m app.cli analyze --make BMW --model "Serie 3" --year 2020 \\
        --km 95000 --price 14500 --origin DE --notify

  python -m app.cli opportunities --min-margin 2000

  python -m app.cli outcome --analysis-id 12 --sold-eur 22300 --days 28
"""
from __future__ import annotations
import asyncio
import json
import sys
from dataclasses import asdict, is_dataclass
from typing import Optional

import typer

from app.core import notifier_telegram, scorer, storage
from app.models.vehicle import (
    AnalysisRequest, Comparable, FuelType, Origin, VATRegime, Vehicle,
)

app = typer.Typer(help="Car Arbitrage Pro — calculadora y notificador de oportunidades.")


def _ser(obj):
    if is_dataclass(obj):
        return {k: _ser(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _ser(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_ser(x) for x in obj]
    return obj


@app.command()
def analyze(
    make: str = typer.Option(...),
    model: str = typer.Option(...),
    version: str = typer.Option(""),
    year: int = typer.Option(...),
    km: int = typer.Option(...),
    fuel: str = typer.Option("diesel", help="gasoline/diesel/hev/phev/bev/lpg/cng/hydrogen"),
    co2_wltp: float = typer.Option(None),
    power_cv: float = typer.Option(None),
    price: float = typer.Option(..., help="Precio adjudicación / venta en moneda local"),
    currency: str = typer.Option("EUR"),
    fx: float = typer.Option(1.0, help="Override FX a EUR (0/1 = usar default)"),
    origin: str = typer.Option("DE", help="ISO-2 país origen del coche"),
    channel: str = typer.Option("eu_auction",
        help="eu_auction/eu_retail_pro/eu_retail_pro_rebu/eu_retail_private/extra_eu"),
    vat: str = typer.Option("rebu", help="rebu/general/import_extra_eu"),
    canary: bool = typer.Option(False),
    has_coc: bool = typer.Option(True),
    comparables_json: Optional[str] = typer.Option(None,
        help="Path a JSON con lista de Comparable o '-' para stdin"),
    notify: bool = typer.Option(False, help="Enviar a Telegram"),
    only_if_green: bool = typer.Option(False, help="Solo notificar si veredicto verde"),
    min_margin: float = typer.Option(0.0, help="Umbral margen mínimo para notificar (€)"),
    save: bool = typer.Option(True, help="Guardar análisis en SQLite"),
    output: str = typer.Option("summary", help="summary | json | full"),
):
    """Analiza un vehículo y opcionalmente notifica/guarda."""
    comps: list[Comparable] = []
    if comparables_json:
        raw = sys.stdin.read() if comparables_json == "-" else open(comparables_json).read()
        comps = [Comparable(**c) for c in json.loads(raw)]

    veh = Vehicle(
        make=make, model=model, version=version or None, year=year, km=km,
        fuel=FuelType(fuel),
        co2_wltp=co2_wltp, power_cv=power_cv,
        origin_country=origin.upper(), has_coc=has_coc,
    )
    req = AnalysisRequest(
        vehicle=veh, origin=Origin(channel),
        purchase_price=price, purchase_currency=currency, fx_rate_to_eur=fx,
        vat_regime=VATRegime(vat), canary_islands=canary, comparables=comps,
    )
    verdict = scorer.analyze(req)
    vd = _ser(verdict)

    if save:
        try:
            aid = storage.save_analysis(req.model_dump(), vd)
            vd["_analysis_id"] = aid
        except Exception as e:
            typer.echo(f"[warn] No se pudo guardar análisis: {e}", err=True)

    if output == "json":
        typer.echo(json.dumps(vd, indent=2, default=str, ensure_ascii=False))
    elif output == "full":
        typer.echo(json.dumps(vd, indent=2, default=str, ensure_ascii=False))
    else:
        s = vd["summary"]
        typer.echo(f"\n{s['verdict']}  {s['vehicle']}")
        typer.echo(f"  Venta recomendada: {s['recommended_sale_eur']:,.0f} €")
        typer.echo(f"  Margen esperado:   {s['expected_margin_eur']:,.0f} €")
        typer.echo(f"  Días a vender:     {s['expected_days_to_sell']:,.0f} ({s['velocity']})")
        typer.echo(f"  ROI anualizado:    {s['annualized_roi_pct']*100:,.1f}%")
        typer.echo(f"  Puja máxima:       {s['max_bid_eur']:,.0f} €")
        typer.echo(f"  Riesgo:            {s['risk_label']} ({s['risk_score']}/100)")
        if vd.get("flags"):
            typer.echo("  Avisos: " + " · ".join(vd["flags"][:3]))

    if notify:
        result = asyncio.run(notifier_telegram.notify_verdict(
            vd, only_if_green=only_if_green, min_margin_eur=min_margin,
        ))
        if result.get("ok"):
            typer.echo("✓ Telegram enviado.")
        elif result.get("skipped"):
            typer.echo(f"⊘ Telegram omitido: {result['skipped']}")
        else:
            typer.echo(f"✗ Telegram error: {result.get('error') or result.get('response')}", err=True)


@app.command()
def opportunities(
    min_margin: float = typer.Option(1500),
    max_risk: int = typer.Option(35),
    limit: int = typer.Option(20),
):
    """Lista oportunidades verdes guardadas en SQLite ordenadas por margen."""
    rows = storage.top_opportunities(min_margin_eur=min_margin, max_risk=max_risk, limit=limit)
    if not rows:
        typer.echo("Sin oportunidades guardadas que cumplan los criterios.")
        return
    typer.echo(f"\nTop {len(rows)} oportunidades:")
    for r in rows:
        typer.echo(
            f"  #{r['id']:>4}  {r['label']}  {r['make']} {r['model']} {r['year']} "
            f"({r['km']:,}km) · margen {r['margin_eur']:,.0f}€ "
            f"· ROI {(r['roi_annualized'] or 0)*100:,.0f}% · riesgo {r['risk_score']}"
        )


@app.command()
def outcome(
    analysis_id: int = typer.Option(..., "--analysis-id"),
    sold_eur: float = typer.Option(...),
    days: float = typer.Option(...),
    notes: str = typer.Option(""),
):
    """Registra el resultado real de una venta para calibración."""
    oid = storage.record_sale_outcome(analysis_id, sold_eur, days, notes=notes)
    typer.echo(f"Outcome #{oid} registrado para análisis #{analysis_id}.")
    stats = storage.calibration_stats()
    typer.echo(f"Calibración acumulada (n={stats['n']}): {stats}")


@app.command()
def telegram_test():
    """Envía un mensaje de prueba al chat configurado."""
    cfg = notifier_telegram.TelegramConfig.from_env()
    if cfg is None:
        typer.echo("✗ Variables de entorno no configuradas:", err=True)
        typer.echo("  CAR_ARBITRAGE_TELEGRAM_BOT_TOKEN", err=True)
        typer.echo("  CAR_ARBITRAGE_TELEGRAM_CHAT_ID", err=True)
        raise typer.Exit(1)
    result = asyncio.run(notifier_telegram.send_message(
        "✅ *Car Arbitrage Pro* test OK\\.", parse_mode="MarkdownV2",
    ))
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    app()
