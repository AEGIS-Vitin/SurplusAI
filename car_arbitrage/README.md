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

- **Calcula coste total puesto en venta** desde subasta UE (OpenLane/BCA),
  retail UE o importación extra-UE (Dubái/EAU, Japón, EE.UU., UK).
- **Aplica IEDMT** según CO2 WLTP, depreciación por antigüedad,
  excepciones (BEV, histórico, Canarias, Ceuta/Melilla, familia numerosa,
  discapacidad).
- **Modela IVA** en los tres regímenes: REBU (margen), general 21%,
  autoliquidación intracomunitaria, e importación extra-UE.
- **Aduanas extra-UE**: CIF + arancel TARIC 10% + IVA importación 21%
  (o IGIC 7% Canarias) + DUA + inspección esperada.
- **Transporte**: tabla por origen UE (camión) y extra-UE (RoRo/contenedor).
- **Homologación**: ficha reducida UE vs homologación individual extra-UE
  con adaptaciones (luces, velocímetro km/h) y provisión de riesgo 15%.
- **Reacondicionado** estimado por km, edad, segmento, combustible.
- **Comparables ES/DE** con regresión robusta Huber para precio justo.
- **Monte Carlo** 1000 simulaciones: probabilidad de pérdida, VaR 95%,
  margen esperado.
- **Puja máxima** que mantiene margen objetivo en escenario P25 venta.
- **Scrapers** (OpenLane con cookie, Dubizzle, mobile.de, autoscout24.es/.de,
  coches.net) para autocompletado de comparables y búsqueda de oportunidades.

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

## Quick start

```bash
cd car_arbitrage/backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest tests/ -v
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Y en otra terminal:

```bash
cd car_arbitrage/frontend
python -m http.server 5500
# abrir http://localhost:5500
```

## Variables de entorno

```bash
# Solo si vas a usar scraping autenticado de OpenLane
export OPENLANE_COOKIE="session=...; auth=...; ..."
```

Para obtener la cookie: inicia sesión en OpenLane en tu navegador, abre
DevTools → Application → Cookies, copia los pares `nombre=valor`
separados por `;`.

## Endpoints

| Método | Path                     | Descripción                          |
|--------|--------------------------|--------------------------------------|
| GET    | `/health`                | Healthcheck                          |
| POST   | `/analyze`               | Análisis con comparables aportados   |
| POST   | `/search`                | Búsqueda multi-portal                |
| POST   | `/analyze-with-fetch`    | Análisis + auto-scrape comparables   |

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
