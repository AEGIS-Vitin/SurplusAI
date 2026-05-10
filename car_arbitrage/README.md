# Car Arbitrage Pro

Calculadora de rentabilidad para compraventa de coches con arbitraje
multi-mercado. Cubre fiscalidad española completa (IEDMT, IVA general,
REBU, autoliquidación intracomunitaria, importación extra-UE) y costes
reales de transporte, aduanas, homologación y reacondicionado.

> ⚠️ **Aviso legal.** Esta herramienta es una ayuda de cálculo, NO sustituye
> a un asesor fiscal. Verifica siempre con tu gestor antes de operar. El
> scraping de portales como OpenLane, Dubizzle, mobile.de, etc. puede
> violar sus Términos de Servicio: el usuario es el único responsable.
> Importar coches de fuera de la UE requiere homologación individual y
> cumplimiento Euro 6d, con riesgo real de pérdida si no se acepta.

## Qué hace

### Fiscalidad y costes
- **Coste total puesto en venta** desde subasta UE (OpenLane/BCA),
  retail UE o importación extra-UE (Dubái/EAU, Japón, EE.UU., UK).
- **IEDMT** según CO2 WLTP, depreciación por antigüedad, excepciones
  (BEV, histórico, Canarias, Ceuta/Melilla, familia numerosa, discapacidad).
- **IVA** en los tres regímenes: REBU (margen), general 21%, autoliquidación
  intracomunitaria, e importación extra-UE.
- **Aduanas extra-UE**: CIF + arancel TARIC 10% + IVA importación 21%
  (o IGIC 7% Canarias) + DUA + inspección esperada.
- **Transporte**: tabla por origen UE (camión) y extra-UE (RoRo/contenedor).
- **Homologación**: ficha reducida UE vs homologación individual extra-UE
  con adaptaciones (luces, velocímetro km/h) y provisión de riesgo 15%.
- **Reacondicionado** estimado por km, edad, segmento, combustible.

### Análisis y decisión
- **Comparables ES/DE** con regresión robusta Huber para precio justo.
- **3 escenarios de venta** (rápida P25×1.05, recomendada P50, paciente P75)
  con margen, días, ROI anualizado y NPV de cada uno.
- **Rotación teórica** por segmento (premium alemán, exotic, SUV, city,
  EV, PHEV, youngtimer, classic…) con LogNormal y velocity score 1-5.
- **Risk score combinado** (0-100): homologación, rollback, daño estructural,
  propietarios, libro mantenimiento, liquidez, datos de mercado.
- **Monte Carlo** 1000 simulaciones: prob. pérdida, prob. margen ≥ 1.500/3.000€,
  VaR 95%, días esperados a vender.
- **Puja máxima** que mantiene margen objetivo en escenario P25 venta.

### Ingesta y operación
- **Scrapers** (OpenLane con cookie, Dubizzle, mobile.de, autoscout24.es/.de,
  coches.net) para autocompletado de comparables y búsqueda de oportunidades.
- **Bot Telegram dedicado** con env vars `CAR_ARBITRAGE_TELEGRAM_*`
  (separado de cualquier otro bot del repo). Notifica veredictos con
  escenarios, ROI, riesgo y enlace al lote. Filtros opcionales: solo verdes,
  margen mínimo.
- **Persistencia SQLite** del histórico de análisis y resultados reales de
  venta (`outcomes`) para calibrar el modelo (`/calibration`).
- **CLI Typer** (`python -m app.cli`) con comandos `analyze`, `opportunities`,
  `outcome` y `telegram-test`.

## Arquitectura

```
car_arbitrage/
├── backend/
│   ├── app/
│   │   ├── core/          # iedmt, vat_regimes, customs, transport,
│   │   │                  # homologation, reconditioning, fx, pricer, scorer
│   │   ├── scrapers/      # base, openlane, dubizzle, mobile_de,
│   │   │                  # autoscout24, coches_net
│   │   ├── models/        # vehicle (Pydantic)
│   │   └── main.py        # FastAPI: /health /analyze /search /analyze-with-fetch
│   ├── tests/             # pytest unitario módulos fiscales + smoke E2E
│   └── requirements.txt
└── frontend/
    └── index.html         # SPA React (CDN) — pestañas Vehículo/Compra/Mercado/Veredicto
```

## Quick start (1 comando)

```bash
cd car_arbitrage
./run-local.sh
# → abre http://localhost:8000
```

El script crea venv, instala deps, corre tests, y arranca el backend con
el frontend servido en el mismo origen (sin CORS) en el puerto 8000.

## Aún más rápido — single-file Python

```bash
python3 car_arbitrage_solo.py
# → http://localhost:8000
```

UN solo archivo (`car_arbitrage_solo.py`) con TODO embebido: motor fiscal,
FastAPI, frontend, SQLite, Telegram. Auto-instala dependencias.

## Para móvil — artefacto HTML puro (sin servidor)

`car_arbitrage_artifact.html` es un único archivo HTML que abres con
doble clic o subes a tu móvil. Toda la fiscalidad (IEDMT, IVA REBU,
aduanas extra-UE, escenarios, ROI, riesgo, Monte Carlo) corre en el
navegador. Funciona offline. NO incluye scrapers ni Telegram (necesitan
servidor).

## Quick start con Docker

```bash
cd car_arbitrage
docker compose up --build
# → http://localhost:8000
```

## Manual (dev)

```bash
cd car_arbitrage/backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest tests/ -v
.venv/bin/uvicorn app.main:app --reload --port 8000
```

## Deploy a Fly.io

```bash
cd car_arbitrage
fly launch --no-deploy --copy-config --name car-arbitrage-<sufijo>
fly volumes create car_arbitrage_data --size 1 --region mad
fly secrets set CAR_ARBITRAGE_TELEGRAM_BOT_TOKEN=...
fly secrets set CAR_ARBITRAGE_TELEGRAM_CHAT_ID=...
fly deploy
```

## App móvil (Expo / React Native)

Ver [`mobile/README.md`](./mobile/README.md). Resumen:

```bash
cd car_arbitrage/mobile
npm install
npx expo start
# escanea QR con Expo Go (iOS / Android) o pulsa i/a para emulador
```

Editar `mobile/app.json` → `expo.extra.API_BASE` para apuntar al backend
desplegado.

## Variables de entorno

```bash
# Scraping autenticado de OpenLane
export OPENLANE_COOKIE="session=...; auth=...; ..."

# Bot Telegram dedicado (separado de otros bots del repo)
export CAR_ARBITRAGE_TELEGRAM_BOT_TOKEN="<token de @BotFather>"
export CAR_ARBITRAGE_TELEGRAM_CHAT_ID="<tu chat_id>"

# Opcional: ruta DB SQLite (default: ./car_arbitrage.sqlite3)
export CAR_ARBITRAGE_DB="/var/data/car_arbitrage.sqlite3"
```

**Setup del bot Telegram:**
1. Habla con `@BotFather` en Telegram → `/newbot` → nombre + username → guarda token.
2. Inicia conversación con tu bot (envía `/start`).
3. `curl https://api.telegram.org/bot<TOKEN>/getUpdates` → encuentra `chat.id`.
4. Exporta las dos variables de entorno arriba.
5. Test: `python -m app.cli telegram-test`.

**Cookie OpenLane:** inicia sesión en OpenLane en tu navegador, DevTools →
Application → Cookies, copia los pares `nombre=valor` separados por `;`.

## Endpoints

| Método | Path                     | Descripción                          |
|--------|--------------------------|--------------------------------------|
| GET    | `/health`                | Healthcheck                          |
| POST   | `/analyze`               | Análisis con comparables aportados (guarda en SQLite por defecto) |
| POST   | `/search`                | Búsqueda multi-portal                |
| POST   | `/analyze-with-fetch`    | Análisis + auto-scrape comparables   |
| POST   | `/notify`                | Envía un veredicto a Telegram        |
| GET    | `/opportunities`         | Top oportunidades verdes históricas  |
| GET    | `/recent`                | Análisis recientes                   |
| POST   | `/outcome`               | Registra resultado real de venta     |
| GET    | `/calibration`           | Métricas de calibración              |

## CLI

```bash
# Análisis con comparables vía stdin (JSON list)
echo '[{"source":"coches.net","market":"ES","price_eur":22500,"km":88000,"year":2020}, ...]' \
  | python -m app.cli analyze \
      --make BMW --model "Serie 3" --version 320d --year 2020 --km 95000 \
      --fuel diesel --co2-wltp 145 --price 14500 --origin DE \
      --channel eu_auction --vat rebu --comparables-json - --notify

# Top oportunidades
python -m app.cli opportunities --min-margin 2000 --max-risk 30

# Registrar venta real (calibración)
python -m app.cli outcome --analysis-id 12 --sold-eur 22300 --days 28

# Test bot Telegram
python -m app.cli telegram-test
```

## Limitaciones conocidas

- **Valor fiscal Hacienda**: aproximado por escalado del precio de venta
  esperado y el coeficiente de depreciación. Para producción usa la
  Orden HFP anual (BOE) o la base oficial de Hacienda por marca/modelo.
- **Selectores HTML** de scrapers son best-effort y se rompen cuando los
  portales cambian. Cachea fixtures HTML para tests, no scrapees en CI.
- **OpenLane y Dubizzle**: ToS pueden prohibir scraping. Uso bajo tu
  responsabilidad. Considera APIs B2B oficiales si están disponibles.
- **Comparables auto-fetcheados**: dependen de que los scrapers funcionen
  hoy. Verifica siempre la calidad antes de tomar decisiones.
- **Tipos de cambio**: por defecto cacheados; aporta override real de BCE
  para producción.

## Tests

```bash
cd backend
.venv/bin/pytest tests/ -v
```

Cubren: tramos IEDMT, BEV exento, histórico, Canarias, REBU vs general,
aduanas Dubái, smoke end-to-end BMW (subasta DE) y Land Cruiser (Dubái).
