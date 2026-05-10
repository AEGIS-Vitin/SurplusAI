"""Notificador Telegram dedicado para Car Arbitrage Pro.

Bot SEPARADO del resto del proyecto: usa variables de entorno con prefijo
CAR_ARBITRAGE_TELEGRAM_* para evitar colisiones con otros bots del repo.

Setup:
1. Crear bot nuevo con @BotFather, copiar token.
2. Iniciar conversación con el bot (enviar /start).
3. Obtener chat_id (https://api.telegram.org/bot<TOKEN>/getUpdates).
4. Exportar:
     CAR_ARBITRAGE_TELEGRAM_BOT_TOKEN=...
     CAR_ARBITRAGE_TELEGRAM_CHAT_ID=...
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Optional

import httpx

DEFAULT_TIMEOUT = 15.0
TELEGRAM_API = "https://api.telegram.org"


@dataclass
class TelegramConfig:
    bot_token: str
    chat_id: str

    @classmethod
    def from_env(cls) -> Optional["TelegramConfig"]:
        token = os.environ.get("CAR_ARBITRAGE_TELEGRAM_BOT_TOKEN")
        chat = os.environ.get("CAR_ARBITRAGE_TELEGRAM_CHAT_ID")
        if not token or not chat:
            return None
        return cls(bot_token=token, chat_id=chat)


def _esc(text: str) -> str:
    """Escape para parse_mode=MarkdownV2 (subset de caracteres reservados)."""
    if text is None:
        return ""
    text = str(text)
    for ch in ("_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"):
        text = text.replace(ch, "\\" + ch)
    return text


def _fmt_eur(n: Optional[float]) -> str:
    if n is None:
        return "—"
    return f"{n:,.0f} €".replace(",", ".")


def format_verdict_message(v: dict, source_url: Optional[str] = None) -> str:
    s = v.get("summary", {}) or {}
    veh = s.get("vehicle", "Vehículo")
    label = s.get("verdict", v.get("label", "—"))

    lines = [
        f"*{_esc(label)}* · {_esc(veh)}",
        "",
        f"💰 Venta recomendada: *{_esc(_fmt_eur(s.get('recommended_sale_eur')))}*",
        f"📈 Margen esperado: *{_esc(_fmt_eur(s.get('expected_margin_eur')))}*",
        f"⏱  Rotación: *{_esc(round(s.get('expected_days_to_sell') or 0))} días* \\({_esc(s.get('velocity', '—'))}\\)",
        f"🎯 Puja máx: *{_esc(_fmt_eur(s.get('max_bid_eur')))}*",
        f"📊 ROI anualizado: *{_esc(round((s.get('annualized_roi_pct') or 0) * 100, 1))}%*",
        f"⚠️ Riesgo: *{_esc(s.get('risk_label', '—'))}* \\({_esc(s.get('risk_score', 0))}/100\\)",
    ]

    mc = v.get("monte_carlo", {}) or {}
    if mc:
        lines += [
            "",
            "_Monte Carlo \\(1000 sims\\)_",
            f"  • Prob\\. pérdida: {_esc(round((mc.get('prob_loss') or 0) * 100, 1))}%",
            f"  • Prob\\. margen ≥ 1\\.500€: {_esc(round((mc.get('prob_margin_above_1500') or 0) * 100, 1))}%",
            f"  • VaR 95%: {_esc(_fmt_eur(mc.get('var95_eur')))}",
        ]

    flags = v.get("flags") or []
    if flags:
        lines += ["", "_Avisos:_"]
        for f in flags[:4]:
            lines.append(f"  • {_esc(f)}")

    scenarios = v.get("scenarios") or []
    if scenarios:
        lines += ["", "_Escenarios de venta:_"]
        for sc in scenarios:
            lines.append(
                f"  • {_esc(sc.get('label'))}: {_esc(_fmt_eur(sc.get('sale_price_eur')))} · "
                f"{_esc(round(sc.get('days_to_sell') or 0))}d · "
                f"margen {_esc(_fmt_eur(sc.get('margin_eur')))} "
                f"\\({_esc(round((sc.get('annualized_roi_pct') or 0) * 100, 1))}% ROI an\\.\\)"
            )

    if source_url:
        lines += ["", f"🔗 {_esc(source_url)}"]

    return "\n".join(lines)


async def send_message(text: str, cfg: Optional[TelegramConfig] = None,
                       parse_mode: str = "MarkdownV2",
                       disable_preview: bool = True) -> dict:
    cfg = cfg or TelegramConfig.from_env()
    if cfg is None:
        return {"ok": False, "error": "CAR_ARBITRAGE_TELEGRAM_BOT_TOKEN/CHAT_ID no configurados."}
    url = f"{TELEGRAM_API}/bot{cfg.bot_token}/sendMessage"
    payload = {
        "chat_id": cfg.chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_preview,
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        try:
            r = await client.post(url, json=payload)
            data = r.json()
            return {"ok": r.status_code == 200 and data.get("ok", False), "response": data}
        except Exception as e:
            return {"ok": False, "error": str(e)}


async def notify_verdict(verdict_dict: dict, source_url: Optional[str] = None,
                         only_if_green: bool = False, min_margin_eur: float = 0.0) -> dict:
    """Envía el veredicto al chat. Permite filtrar por verde y margen mínimo."""
    label = (verdict_dict.get("label") or "")
    margin = (verdict_dict.get("summary", {}) or {}).get("expected_margin_eur") or verdict_dict.get("margin_eur") or 0
    if only_if_green and not label.startswith("🟢"):
        return {"ok": False, "skipped": "no es verde"}
    if margin < min_margin_eur:
        return {"ok": False, "skipped": f"margen {margin:.0f} < umbral {min_margin_eur:.0f}"}
    text = format_verdict_message(verdict_dict, source_url=source_url)
    return await send_message(text)
