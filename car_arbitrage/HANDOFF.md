# HANDOFF — Car Arbitrage Pro

> Contexto para Code y Cowork. Lee este archivo antes de tocar nada.

## Qué es esto

Calculadora de rentabilidad para comprar coches en subastas B2B (OpenLane,
BCA, Autorola) o importarlos de fuera de la UE (Dubái/EAU, Japón, EE.UU.,
UK), con todo el stack fiscal español (IEDMT, IVA general, REBU,
autoliquidación intracomunitaria, importación extra-UE), aduanas TARIC,
transporte, homologación individual, y análisis de margen + ROI + riesgo
+ rotación + Monte Carlo. PR #1 (draft) en
`https://github.com/AEGIS-Vitin/SurplusAI/pull/1`.

## ⚡ Ejecutar en una sola línea

```bash
python3 car_arbitrage/car_arbitrage_solo.py
# → http://localhost:8000
```

Ese único archivo (`car_arbitrage_solo.py`, ~1466 líneas) contiene
**TODO**: motor fiscal, FastAPI, frontend SPA embebido, SQLite,
Telegram notifier, self-tests al arranque. Auto-instala dependencias
Python si faltan (fastapi, uvicorn, pydantic, httpx, numpy).

Variables de entorno opcionales:
```bash
export CAR_ARBITRAGE_TELEGRAM_BOT_TOKEN="<de @BotFather>"
export CAR_ARBITRAGE_TELEGRAM_CHAT_ID="<tu chat>"
export CAR_ARBITRAGE_DB="/ruta/db.sqlite3"   # default ./car_arbitrage.sqlite3
export PORT=8000
```

## Estructura del repo (módulo aislado)

```
car_arbitrage/
├── car_arbitrage_solo.py        # ⭐ SINGLE-FILE: ejecuta esto y ya está
├── run-local.sh                 # Alternativa: monta venv y arranca multi-archivo
├── README.md
├── HANDOFF.md                   # ← este archivo
├── docker-compose.yml           # `docker compose up`
├── fly.toml                     # Deploy a Fly.io
├── backend/                     # Versión multi-archivo (mismo motor)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py              # FastAPI
│   │   ├── cli.py               # Typer CLI
│   │   ├── core/                # iedmt, vat_regimes, customs, transport,
│   │   │                        # homologation, reconditioning, fx, pricer,
│   │   │                        # scorer, rotation, risk, notifier_telegram,
│   │   │                        # storage
│   │   ├── scrapers/            # openlane, dubizzle, mobile_de,
│   │   │                        # autoscout24, coches_net (rate-limited)
│   │   └── models/vehicle.py
│   └── tests/                   # 30 tests pytest, todos pasan
├── frontend/index.html          # SPA React via CDN (mismo motor)
└── mobile/                      # Expo / React Native skeleton
    ├── App.tsx
    ├── app.json (extra.API_BASE)
    └── src/{api.ts, format.ts, screens/}
```

## Estado

| | Estado |
|---|---|
| Tests | 30/30 ✅ |
| CI (GitHub Actions) | ✅ pasa lint + tests + docker build |
| Docker build | ✅ |
| Single-file app | ✅ probado |
| Frontend web | ✅ |
| Mobile (Expo) | ⚠️ skeleton sin compilar |
| Deploy Fly.io | ⏸️ pendiente acción humana |
| Auth | ❌ no implementado |
| Push notifications nativas | ❌ no implementado |

## Lo que YA funciona

- **IEDMT** con todos los tramos CO2 WLTP, depreciación, BEV exento,
  Canarias (IGIC), Ceuta/Melilla, histórico >30 años, familia numerosa,
  discapacidad.
- **IVA en 3 regímenes**: REBU (margen), general 21%, autoliquidación
  intracomunitaria, e importación extra-UE.
- **Aduanas extra-UE**: CIF + arancel TARIC 10% (8703) + IVA importación
  21% (o IGIC 7% Canarias) + DUA + inspección esperada.
- **Transporte** con tablas por origen UE (camión) y extra-UE
  (RoRo/contenedor) con tasas portuarias.
- **Homologación**: ficha reducida UE vs homologación individual extra-UE
  con adaptaciones (luces, velocímetro km/h) y provisión de riesgo 15%.
- **Reacondicionado** estimado por km, edad, segmento, combustible.
- **Pricer**: regresión OLS sobre comparables (km, año) + percentiles.
- **Rotación teórica** por 16 segmentos con LogNormal, velocity score,
  probabilidades de venta a 30/60/90 días.
- **Risk score 0-100** con desglose por factor; auto-VETO si crítico.
- **Monte Carlo 1000 sims**: prob. pérdida, prob. margen ≥ 1.500/3.000€,
  VaR 95%, días esperados.
- **3 escenarios de venta** (rápida P25×1.05, recomendada P50, paciente P75)
  cada uno con días, margen, ROI anualizado y NPV.
- **Puja máxima** que mantiene margen objetivo en escenario P25 venta.
- **Bot Telegram** dedicado (`CAR_ARBITRAGE_TELEGRAM_*`).
- **SQLite** persistencia + outcomes + calibración.
- **Scrapers** rate-limited (NO usar en CI; ToS riesgo).

## Lo que falta — pickup tasks para Cowork/Code

### 🟢 Bajo riesgo, alto valor

1. **Deploy a Fly.io** (requiere `fly auth login` humano):
   ```bash
   cd car_arbitrage
   fly launch --no-deploy --copy-config --name car-arbitrage-<sufijo>
   fly volumes create car_arbitrage_data --size 1 --region mad
   fly secrets set CAR_ARBITRAGE_TELEGRAM_BOT_TOKEN=...
   fly secrets set CAR_ARBITRAGE_TELEGRAM_CHAT_ID=...
   fly deploy
   ```
   Luego actualizar `mobile/app.json` → `expo.extra.API_BASE` con la URL final.

2. **Compilar app móvil con Expo** (`mobile/`):
   ```bash
   cd car_arbitrage/mobile
   npm install
   npx expo start          # QR para Expo Go
   # o builds nativos:
   eas build --platform ios && eas submit --platform ios
   eas build --platform android && eas submit --platform android
   ```

3. **Fixtures HTML para tests offline** de scrapers en
   `backend/tests/fixtures/{coches_net,mobile_de,dubizzle,openlane}_*.html`
   con tests que NO toquen la red. Esto desbloquea CI con cobertura de
   parsers.

### 🟡 Mediano

4. **Auth con Supabase** (multi-tenant):
   - `pip install supabase fastapi-users`
   - Tablas `users`, `tenants`, `analyses(tenant_id, user_id)` en SQLite
     o migrar a Postgres.
   - Middleware JWT en endpoints `/analyze /opportunities /outcome`.
   - Pantalla login en frontend + móvil (AsyncStorage del JWT).
   - Quitar el `/notify` global; Telegram por usuario (config en perfil).

5. **Push notifications nativas** (FCM + APNs vía Expo Notifications):
   - `npm install expo-notifications` en `mobile/`.
   - Endpoint backend `/devices` que registra tokens push por usuario.
   - Cron cada 15 min que llama scrapers, evalúa con `/analyze`, y empuja
     notificación push al móvil + Telegram al usuario si VERDE y margen
     supera umbral configurado.

6. **Cron de oportunidades**:
   - APScheduler (in-process) o GitHub Actions schedule (hourly).
   - Lee modelos vigilados de tabla `watchlist(make, model, year_range,
     km_max, min_margin)` por usuario.
   - Para cada uno: busca en OpenLane (con cookie del usuario), Dubizzle,
     etc., evalúa y notifica los 🟢 nuevos no notificados ya
     (deduplicación por hash url).

### 🔴 Riesgo alto / decisión humana

7. **Scraping autenticado de OpenLane**: violar ToS → riesgo legal.
   Considerar API B2B oficial de OpenLane si existe (contactar comercial).
   Mientras tanto, dejar como uso bajo cookie del usuario, **no usar en
   CI ni a escala**.

8. **Valor fiscal Hacienda exacto**: aproximamos por escalado del precio
   esperado y depreciación. Para producción: descargar Orden HFP anual
   del BOE y construir tabla make/model/year → valor fiscal "a nuevo".

9. **Calibración del modelo de rotación**: comparar `days_to_sell`
   estimado vs `actual_days_to_sell` registrado en `sale_outcomes` y
   re-calibrar `SEGMENT_DAYS` cada N transacciones reales.

## Problemas conocidos

- **Click 8.3 vs Typer 0.12**: incompatibilidad. Pinneamos `click<8.2` y
  `typer==0.15.1` en `requirements.txt`. No tocar sin probar CLI primero.
- **Frontend en `file://`**: no funciona porque hace `fetch("/analyze")`
  → necesita backend corriendo. Si abres `index.html` con doble clic,
  configura `window.API_BASE = "http://localhost:8000"` o sirve por
  HTTP. La versión single-file resuelve esto: el backend sirve también
  el HTML.
- **Selectores HTML de scrapers**: best-effort, se rompen cuando los
  portales cambian. Hay que mantener fixtures.

## Mensaje a Cowork

Si lees esto y quieres tomar el siguiente bloque: empieza por **#1
(Deploy Fly.io)** o **#3 (Fixtures HTML)** — son los que más desbloquean
sin diseño nuevo. Para 4-6 háblalo con humano antes (auth scheme,
proveedor de push, política de scraping a escala).

Cualquier cambio: PR contra `claude/car-profitability-scraper-KeJxu` o
crear nueva rama desde ahí. Mantén los 30 tests verdes y el lint
ruff (config en `.github/workflows/car-arbitrage-ci.yml`).
