# AEGIS-FOOD: B2B Food Surplus Marketplace

**Cumplimiento de la Ley 1/2025 sobre Prevención y Reducción de la Pérdida y Desperdicio de Alimentos**

Una plataforma marketplace moderna que conecta generadores de excedentes alimentarios con receptores certificados, implementando automáticamente la jerarquía legal de usos establecida por la Ley 1/2025 de España.

## Características Principales

### 🎯 Negocio
- **Marketplace B2B** para compra/venta/donación de excedentes alimentarios
- **Precios dinámicos** que disminuyen automáticamente según proximidad a vencimiento
- **Matching predictivo** que conecta generadores con receptores óptimos
- **Trazabilidad completa** de toda la cadena de suministro
- **Documentación legal automática** para cumplimiento normativo

### 📋 Compliance Legal
- **8 niveles de usos jerárquicos** per Ley 1/2025:
  1. Prevención (Reducción)
  2. Donación para Consumo Humano
  3. Transformación en Productos Alimentarios
  4. Alimentación Animal
  5. Uso Industrial
  6. Compostaje
  7. Biogás/Bioenergía
  8. Eliminación (última opción)
- **Validación automática** de usos permitidos por estado del producto
- **Generación de certificados** de donación y albarandees
- **Trazabilidad de transacciones** para auditorías

### 🌱 Impacto Ambiental
- **Cálculo de CO2 evitado** por producto basado en análisis de ciclo de vida
- **Equivalencias intuitivas** (km de conducción, árbolesplantados, etc.)
- **Dashboard de métricas** de sostenibilidad
- **Contribución a objetivos SDG** y reducción de emisiones

### 📍 Inteligencia Geográfica
- **PostGIS integration** para búsquedas de proximidad
- **Radio configurable** para búsquedas locales/regionales
- **Optimización de logística** basada en distancias

## Arquitectura Técnica

```
marketplace-excedentes/
├── backend/                 # FastAPI + SQLAlchemy
│   ├── main.py             # Endpoints principales
│   ├── models.py           # Modelos Pydantic
│   ├── database.py         # SQLAlchemy ORM + PostGIS
│   ├── pricing.py          # Motor de precios dinámicos
│   ├── compliance.py       # Validación legal Ley 1/2025
│   ├── matching.py         # Matching predictivo
│   ├── carbon.py           # Cálculo de huella carbónica
│   ├── requirements.txt    # Dependencias Python
│   └── Dockerfile
├── frontend/               # HTML5 + CSS3 + JavaScript
│   ├── index.html         # SPA completa (Generador/Receptor/Admin)
│   ├── nginx.conf         # Configuración Nginx
│   └── Dockerfile
├── db/
│   └── init.sql           # Schema PostgreSQL + PostGIS
├── docker-compose.yml     # Orquestación de servicios
├── .env.example           # Variables de entorno
└── README.md
```

## Stack Tecnológico

| Componente | Tecnología | Versión |
|-----------|-----------|---------|
| Backend API | FastAPI | 0.104.1 |
| ORM | SQLAlchemy | 2.0.23 |
| Base de Datos | PostgreSQL | 16 |
| GIS | PostGIS | 3.4 |
| Caché/Queues | Redis | 7 |
| Frontend | HTML5/CSS3/JS Vanilla | - |
| Web Server | Nginx | Alpine |
| Contenedores | Docker | 24+ |

## Quick Start

### 1. Preparar Entorno

```bash
cd /sessions/busy-optimistic-gauss/mnt/empresa-ia/marketplace-excedentes

# Copiar configuración de ejemplo
cp .env.example .env

# Ajustar variables si es necesario (usuario/password DB)
nano .env
```

### 2. Iniciar los Servicios

```bash
docker-compose up --build
```

Esto iniciará:
- **PostgreSQL** en `localhost:5432`
- **Backend** en `http://localhost:8000`
- **Frontend** en `http://localhost:80`
- **Redis** en `localhost:6379`

### 3. Acceder a la Plataforma

- **Dashboard**: http://localhost/
- **Swagger API**: http://localhost:8000/docs
- **ReDoc API**: http://localhost:8000/redoc

### 4. Detener Servicios

```bash
docker-compose down
```

## API Endpoints

### Lotes (Lots)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/lots` | Publicar nuevo lote |
| GET | `/lots` | Listar lotes activos con filtros |
| GET | `/lots/{lot_id}` | Obtener detalles de un lote |

**Parámetros de búsqueda:**
- `categoria`: frutas, verduras, carnes, pescados, lacteos, panaderia, prepared, otros
- `ubicacion_lat`, `ubicacion_lon`, `radio_km`: Búsqueda geográfica
- `precio_max`: Filtro de precio máximo
- `fecha_limite_min`: Filtro de fecha mínima

### Ofertas (Bids)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/bids` | Realizar oferta en un lote |
| GET | `/bids/{lot_id}` | Listar ofertas de un lote |

### Transacciones

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/transactions` | Cerrar transacción (aceptar oferta) |
| GET | `/transactions/{transaction_id}` | Obtener detalles transacción |

### Compliance & Legal

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/compliance/{transaction_id}` | Obtener documentos legales |
| GET | `/compliance-hierarchy` | Ver jerarquía legal Ley 1/2025 |

### Inteligencia Predictiva

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/matches?generador_id={id}` | Recomendaciones de compradores |
| GET | `/price-suggestion` | Sugerencia de precio base |

### Dashboard & Métricas

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/stats` | Métricas globales del marketplace |
| GET | `/carbon-footprints` | Datos CO2 por categoría |
| GET | `/health` | Health check |

## Modelo de Datos

```sql
-- Generadores (productores de excedentes)
generadores: id, nombre, tipo, cif, ubicacion, contacto, plan_suscripcion

-- Receptores (compradores/aprovechadores)
receptores: id, nombre, tipo, cif, ubicacion, capacidad_kg_dia, categorias_interes

-- Lotes de excedentes
lotes: id, generador_id, producto, categoria, cantidad_kg, ubicacion, 
       fecha_limite, precio_base, precio_actual, estado, temperatura

-- Pujas/Ofertas
pujas: id, lote_id, receptor_id, precio_oferta, uso_previsto, estado

-- Transacciones completadas
transacciones: id, lote_id, puja_id, generador_id, receptor_id, precio_final,
               cantidad_kg, uso_final, co2_evitado_kg, estado

-- Documentación de Compliance
compliance_docs: id, transaccion_id, tipo, contenido_json, pdf_url

-- Créditos de Carbono
carbon_credits: id, transaccion_id, co2_evitado_kg, equivalencias

-- Predicciones de Matching ML
predicciones_matching: id, generador_id, receptor_id, producto_predicho,
                       cantidad_predicha_kg, fecha_predicha, confianza
```

## Motor de Precios Dinámicos

El precio de un lote se ajusta automáticamente según:

```
precio = precio_base × (dias_restantes / dias_totales) × factor_demanda × factor_escasez

Donde:
- dias_restantes/dias_totales: Factor temporal (0.1 a 1.0)
- factor_demanda: 1.0 + (min(num_bids, 5) × 0.06) — incentiva ofertas tempranas
- factor_escasez: Por categoría (carnes 1.15, pan 0.95, etc.)
- Precio mínimo: 10% del precio base
```

**Ejemplo:**
- Lote: 150 kg manzanas a €0.50/kg (€75 total)
- 3 días para vencer, publicado hace 4 días
- 2 ofertas recibidas
- Precio = €0.50 × (3/7) × 1.12 × 1.05 = €0.42/kg

## Cálculo de Huella de Carbono

Basado en análisis de ciclo de vida (LCA) per kg:

| Categoría | CO2e/kg | Factor de Uso |
|-----------|---------|---------------|
| Carnes | 27.0 | 1.0 (donación) → 0.3 (biogas) |
| Pescados | 12.0 | 1.0 → 0.3 |
| Lácteos | 2.5 | 1.0 → 0.3 |
| Panadería | 1.2 | 1.0 → 0.3 |
| Frutas | 0.8 | 1.0 → 0.3 |
| Verduras | 0.6 | 1.0 → 0.3 |

**Ejemplo:**
- 60 kg costillas (carnes) → donación para consumo
- CO2 evitado = 60 × 27.0 × 1.0 = 1620 kg CO2e
- Equivalente a: 7000+ km conduciendo un coche

## Jerarquía Legal Ley 1/2025

Cada uso tiene restricciones según **estado del producto**:

### ✅ Antes de Fecha de Consumo Preferente
Todos los usos permitidos (1-7)

### ⚠️ Después de Fecha Consumo, Antes Expiración
- ❌ Donación humana
- ❌ Transformación (excepto carnes/pescados con cadena fría)
- ✅ Alimentación animal
- ✅ Uso industrial
- ✅ Compostaje
- ✅ Biogás

### 🔴 Próximo a Expiración
- ✅ Compostaje
- ✅ Biogás
- ✅ Eliminación

### 💀 Después Expiración
- ✅ Solo Compostaje/Biogás/Eliminación

## Matching Predictivo

El sistema recomienda compradores basándose en:

1. **Historial de categorías**: Qué productos compró antes
2. **Proximidad geográfica**: Radio configurable
3. **Capacidad**: Receptores con suficiente capacidad para el lote
4. **Historial de compras**: Receptores activos y confiables

Bonus: Predice qué productos el generador tendrá en exceso próximamente.

## Seguridad & Validación

✅ Validación de entrada en todos los endpoints  
✅ Checks de autorización (propietario del lote)  
✅ Sanitización de inputs  
✅ SQL injection prevention (SQLAlchemy parameterized)  
✅ CORS configurado  
✅ Health checks en todos los servicios  

## Variables de Entorno

```bash
# .env
DB_USER=user
DB_PASSWORD=password
DB_NAME=marketplace_db
DATABASE_URL=postgresql://user:password@db:5432/marketplace_db
REDIS_URL=redis://redis:6379/0
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=False
CORS_ORIGINS=["*"]
```

## Datos de Prueba

La base de datos se inicializa automáticamente con:
- **5 generadores de ejemplo** (supermarkets, restaurantes, industria)
- **5 receptores de ejemplo** (bancos de alimentos, transformadores, compostaje)
- **5 lotes de ejemplo** con diferentes productos y estados

Acceso para pruebas:
- Generador ID 1: Carrefour Madrid (retail)
- Receptor ID 1: Banco de Alimentos Madrid
- Lote ID 1: Manzanas Golden (150 kg, €0.50/kg)

## Troubleshooting

### "Connection refused" en puerto 5432
```bash
# Verificar que PostgreSQL está corriendo
docker-compose ps

# Reiniciar servicios
docker-compose restart db
```

### "ModuleNotFoundError" en backend
```bash
# Reinstalar dependencias
docker-compose rebuild backend
docker-compose up backend
```

### Frontend no carga
```bash
# Limpiar cache del navegador (Ctrl+Shift+Delete)
# O acceder en incógnito
# Verificar que Nginx está corriendo: docker-compose ps
```

## Roadmap Futuro

- [ ] Integración con sistemas de pago (Stripe, PayPal)
- [ ] Notificaciones en tiempo real (WebSocket)
- [ ] Mobile app (React Native)
- [ ] Sistema de ratings y reputación
- [ ] Machine Learning avanzado para predicciones
- [ ] Integración con APIs de logística
- [ ] Smart contracts para automatizar transacciones
- [ ] Análisis de datos con BI (Power BI, Tableau)

## Contribuciones

Las contribuciones son bienvenidas. Por favor:

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## Licencia

This project is licensed under the MIT License - see the LICENSE file for details.

## Contact & Support

Para reportar bugs, sugerencias, o preguntas:
- Email: info@aegis-food.es
- GitHub Issues: [Link al repositorio]
- Website: https://aegis-food.es

---

**AEGIS-FOOD © 2025** - Making food waste prevention profitable and effortless
