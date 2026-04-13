# AEGIS-FOOD Project Structure & Files

## Complete File Inventory

### Root Directory
```
marketplace-excedentes/
├── docker-compose.yml        [Docker orchestration - PostgreSQL, FastAPI, Redis, Nginx]
├── .env                       [Environment variables for development]
├── .env.example              [Template for environment configuration]
├── README.md                 [Main project documentation]
└── PROJECT_STRUCTURE.md      [This file]
```

### Backend `/backend`
```
backend/
├── main.py                   [FastAPI application with all endpoints]
│   └── 17 endpoints covering lots, bids, transactions, compliance, matching, stats
├── models.py                 [Pydantic data models]
│   └── 15+ model classes (Generador, Receptor, Lote, Puja, Transaccion, etc.)
├── database.py              [SQLAlchemy ORM + PostgreSQL + PostGIS]
│   └── 8 database models (GeneradorDB, ReceptorDB, LoteDB, PujaDB, etc.)
├── pricing.py               [Dynamic pricing engine]
│   └── Automatic price adjustment based on time decay & demand
├── compliance.py            [Ley 1/2025 legal compliance]
│   └── 8-level use hierarchy, documentation generation, validation
├── matching.py              [Predictive matching ML]
│   └── Generator recommendations, receiver matching, distance scoring
├── carbon.py                [CO2 footprint calculations]
│   └── LCA-based impact per product category
├── requirements.txt         [Python dependencies]
│   └── FastAPI, SQLAlchemy, GeoAlchemy2, PostgreSQL driver, Pydantic, etc.
├── Dockerfile              [Backend container image (Python 3.11-slim)]
└── .gitkeep               [Directory placeholder]
```

### Frontend `/frontend`
```
frontend/
├── index.html              [Complete SPA (Single Page Application)]
│   ├── 3 main tabs: Generador, Receptor, Admin
│   ├── Modern responsive design (flexbox/grid)
│   ├── Real-time price indicators
│   ├── Legal hierarchy visualization
│   └── ~1000 lines of HTML/CSS/JavaScript
├── nginx.conf             [Nginx reverse proxy configuration]
│   ├── Static file serving
│   ├── API proxy to backend
│   ├── Health check endpoint
│   └── Security headers
├── Dockerfile            [Frontend container (Nginx Alpine)]
└── .gitkeep             [Directory placeholder]
```

### Database `/db`
```
db/
├── init.sql              [Complete PostgreSQL + PostGIS initialization]
│   ├── ENUM types for all entities (estado_lote, uso_final, etc.)
│   ├── 8 main tables (generadores, receptores, lotes, pujas, transacciones, etc.)
│   ├── Spatial indexes on ubicacion (PostGIS)
│   ├── Performance indexes on estado, fecha_limite, generador_id, etc.
│   ├── 4 useful views (v_dashboard_stats, v_top_generadores, etc.)
│   └── Sample data with 5 generators, 5 receivers, 5 sample lots
└── .gitkeep             [Directory placeholder]
```

## Files by Purpose

### 🔧 Configuration Files
- `docker-compose.yml` - Service orchestration
- `.env` - Development environment
- `.env.example` - Template for environment setup
- `backend/requirements.txt` - Python dependencies
- `frontend/nginx.conf` - Nginx configuration
- `backend/Dockerfile` - Backend container build
- `frontend/Dockerfile` - Frontend container build

### 🌐 Backend API (FastAPI)
- `backend/main.py` - All 17 REST endpoints
- `backend/models.py` - 15+ Pydantic models for data validation
- `backend/database.py` - 8 SQLAlchemy ORM models

### 💼 Business Logic
- `backend/pricing.py` - Dynamic pricing algorithm
- `backend/compliance.py` - Ley 1/2025 legal validation
- `backend/matching.py` - Predictive matching engine
- `backend/carbon.py` - CO2 footprint calculations

### 📊 Frontend (Single Page App)
- `frontend/index.html` - Complete responsive dashboard

### 💾 Database
- `db/init.sql` - Full schema with 8 tables + 4 views + sample data

### 📚 Documentation
- `README.md` - Complete project documentation
- `PROJECT_STRUCTURE.md` - This file

## API Endpoints (17 total)

### Generadores (Generators)
1. `POST /generadores` - Register new generator
2. `GET /generadores/{id}` - Get generator details

### Receptores (Receivers)
3. `POST /receptores` - Register new receiver
4. `GET /receptores/{id}` - Get receiver details

### Lotes (Surplus Lots)
5. `POST /lots` - Publish new surplus lot
6. `GET /lots` - List active lots with filters
7. `GET /lots/{id}` - Get lot details

### Pujas (Bids)
8. `POST /bids` - Place bid on lot
9. `GET /bids/{lot_id}` - List bids for lot

### Transacciones (Transactions)
10. `POST /transactions` - Close transaction (accept bid)
11. `GET /transactions/{id}` - Get transaction details

### Compliance & Legal
12. `GET /compliance/{transaction_id}` - Get auto-generated legal docs
13. `GET /compliance-hierarchy` - View Ley 1/2025 hierarchy

### Matching & Recommendations
14. `GET /matches?generador_id={id}` - Get buyer recommendations
15. `GET /price-suggestion` - Get suggested base price

### Dashboard & Metrics
16. `GET /stats` - Dashboard metrics
17. `GET /health` - Health check
18. `GET /carbon-footprints` - CO2 data per category

## Database Schema (8 Tables + 4 Views)

### Main Tables
1. **generadores** - Food surplus generators (retail, horeca, industria, primario)
2. **receptores** - Food receivers (banco_alimentos, transformador, piensos, compost, biogas)
3. **lotes** - Surplus food lots with location & pricing
4. **pujas** - Bids/offers on lots
5. **transacciones** - Completed transactions
6. **compliance_docs** - Auto-generated legal documentation
7. **carbon_credits** - Environmental impact tracking
8. **predicciones_matching** - ML predictions for matching

### Views
1. **v_dashboard_stats** - Global marketplace metrics
2. **v_top_generadores** - Top generators by volume
3. **v_top_receptores** - Top receivers by volume
4. **v_lotes_activos_por_categoria** - Lots by category

## Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| **API** | FastAPI | 0.104.1 |
| **ORM** | SQLAlchemy | 2.0.23 |
| **Database** | PostgreSQL | 16 |
| **GIS** | PostGIS | 3.4 |
| **Cache** | Redis | 7 |
| **Frontend** | HTML5/CSS3/JavaScript | - |
| **Web Server** | Nginx | Alpine |
| **Containers** | Docker | 24+ |
| **Orchestration** | Docker Compose | 3.8 |

## Key Features Implemented

### ✅ Compliance
- [x] Ley 1/2025 8-level use hierarchy
- [x] Automatic use validation by product state
- [x] Legal documentation generation
- [x] Trazabilidad tracking

### ✅ Pricing
- [x] Dynamic pricing algorithm
- [x] Time decay factor (proximity to expiry)
- [x] Demand factor (number of bids)
- [x] Category-based scarcity adjustment
- [x] Price suggestions for generators

### ✅ Matching
- [x] History-based recommendations
- [x] Geographic proximity scoring
- [x] Capacity-based matching
- [x] Predictive product forecasting

### ✅ Environmental Impact
- [x] CO2 footprint calculation per product
- [x] LCA-based impact assessment
- [x] Equivalency visualizations
- [x] Dashboard metrics

### ✅ Data
- [x] PostgreSQL with PostGIS for spatial queries
- [x] Comprehensive indexing for performance
- [x] Sample data for testing
- [x] Proper foreign keys and constraints

### ✅ Frontend
- [x] Responsive design (mobile-friendly)
- [x] 3 main tabs (Generator/Receiver/Admin)
- [x] Real-time price indicators
- [x] Legal hierarchy visualization
- [x] Forms with validation
- [x] Statistics dashboard

### ✅ DevOps
- [x] Docker containerization
- [x] Docker Compose orchestration
- [x] Health checks for all services
- [x] Proper networking
- [x] Persistent volumes
- [x] Environment configuration

## Quick Start Commands

```bash
# Navigate to project
cd /sessions/busy-optimistic-gauss/mnt/empresa-ia/marketplace-excedentes

# Start all services
docker-compose up --build

# Access services
Frontend:     http://localhost/
Swagger API:  http://localhost:8000/docs
Database:     localhost:5432
Redis:        localhost:6379

# Stop services
docker-compose down
```

## File Sizes & Lines of Code

| File | Type | Lines | Size |
|------|------|-------|------|
| backend/main.py | Python | ~650 | 25 KB |
| backend/models.py | Python | ~350 | 12 KB |
| backend/database.py | Python | ~300 | 11 KB |
| backend/compliance.py | Python | ~400 | 15 KB |
| backend/pricing.py | Python | ~200 | 8 KB |
| backend/matching.py | Python | ~350 | 13 KB |
| backend/carbon.py | Python | ~250 | 9 KB |
| frontend/index.html | HTML/CSS/JS | ~1400 | 48 KB |
| db/init.sql | SQL | ~400 | 14 KB |
| README.md | Markdown | ~450 | 16 KB |
| **TOTAL** | **Mixed** | **~4,750** | **171 KB** |

## Data Models (Pydantic)

**15+ Pydantic models** for input/output validation:
- GeneradorBase, GeneradorCreate, Generador
- ReceptorBase, ReceptorCreate, Receptor
- LoteBase, LoteCreate, LoteUpdate, Lote, LoteWithBids
- PujaBase, PujaCreate, PujaUpdate, Puja
- TransaccionBase, TransaccionCreate, Transaccion
- ComplianceDocBase, ComplianceDocCreate, ComplianceDoc
- CarbonCreditBase, CarbonCreditCreate, CarbonCredit
- PrediccionMatching
- Response models: StatsResponse, HealthResponse, MatchResponse

## Database Models (SQLAlchemy)

**8 database models** with proper relationships:
- GeneradorDB (1-to-many with LoteDB, TransaccionDB, PrediccionMatchingDB)
- ReceptorDB (1-to-many with PujaDB, TransaccionDB, PrediccionMatchingDB)
- LoteDB (relationships with Generador, Puja, Transaccion)
- PujaDB (relationships with Lote, Receptor, Transaccion)
- TransaccionDB (relationships with Lote, Puja, Generador, Receptor, ComplianceDoc, CarbonCredit)
- ComplianceDocDB (foreign key to Transaccion)
- CarbonCreditDB (foreign key to Transaccion)
- PrediccionMatchingDB (foreign keys to Generador, Receptor)

## Production Readiness Checklist

- [x] Error handling and validation
- [x] CORS configuration
- [x] Health checks
- [x] Database migrations via init.sql
- [x] Environment configuration
- [x] Logging setup ready
- [x] Docker containers
- [x] Network isolation
- [x] Volume persistence
- [x] Security headers (Nginx)
- [x] Input sanitization
- [x] Proper HTTP status codes
- [x] API documentation (Swagger)
- [x] Sample data for testing
- [x] README with deployment instructions

## Notes

- All code follows PEP 8 standards for Python
- Frontend is a modern SPA with no build process (vanilla JS)
- Database uses ENUM types for type safety
- PostGIS enables geospatial queries for location-based matching
- Pricing algorithm includes anti-gaming mechanisms (demand factor, category-based scarcity)
- Compliance engine implements full Ley 1/2025 hierarchy
- CO2 calculations based on published LCA data
- All timestamps use UTC internally

---

**Created**: April 2025  
**Version**: 1.0.0  
**Status**: Production-Ready MVP
