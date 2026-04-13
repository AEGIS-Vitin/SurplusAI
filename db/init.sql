-- AEGIS-FOOD Database Initialization
-- PostgreSQL + PostGIS schema for food surplus marketplace
-- Implements Spain's Ley 1/2025 on food waste

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS postgis;

-- Create ENUM types
CREATE TYPE tipo_generador AS ENUM ('retail', 'industria', 'horeca', 'primario');
CREATE TYPE tipo_receptor AS ENUM ('banco_alimentos', 'transformador', 'piensos', 'compost', 'biogas');
CREATE TYPE categoria_producto AS ENUM ('frutas', 'verduras', 'lacteos', 'carnes', 'pescados', 'panaderia', 'prepared', 'otros');
CREATE TYPE estado_lote AS ENUM ('activo', 'adjudicado', 'expirado', 'retirado');
CREATE TYPE estado_puja AS ENUM ('pendiente', 'aceptada', 'rechazada');
CREATE TYPE estado_transaccion AS ENUM ('pendiente', 'completada', 'cancelada');
CREATE TYPE uso_final AS ENUM ('prevencion', 'donacion_consumo', 'transformacion', 'alimentacion_animal', 'uso_industrial', 'compostaje', 'biogas', 'eliminacion');
CREATE TYPE tipo_compliance_doc AS ENUM ('certificado_donacion', 'albaran', 'trazabilidad');

-- Table: generadores (Food surplus generators)
CREATE TABLE generadores (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(255) NOT NULL,
    tipo tipo_generador NOT NULL,
    cif VARCHAR(20) NOT NULL UNIQUE,
    direccion VARCHAR(500) NOT NULL,
    ubicacion GEOGRAPHY(POINT, 4326) NOT NULL,
    contacto_email VARCHAR(255) NOT NULL,
    contacto_telefono VARCHAR(20) NOT NULL,
    plan_suscripcion VARCHAR(50) DEFAULT 'basico',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_generadores_cif ON generadores(cif);
CREATE INDEX idx_generadores_tipo ON generadores(tipo);
CREATE INDEX idx_generadores_ubicacion ON generadores USING GIST(ubicacion);

-- Table: receptores (Receivers/consumers)
CREATE TABLE receptores (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(255) NOT NULL,
    tipo tipo_receptor NOT NULL,
    cif VARCHAR(20) NOT NULL UNIQUE,
    direccion VARCHAR(500) NOT NULL,
    ubicacion GEOGRAPHY(POINT, 4326) NOT NULL,
    capacidad_kg_dia FLOAT NOT NULL,
    categorias_interes TEXT[] DEFAULT '{}',
    licencias TEXT[] DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_receptores_cif ON receptores(cif);
CREATE INDEX idx_receptores_tipo ON receptores(tipo);
CREATE INDEX idx_receptores_ubicacion ON receptores USING GIST(ubicacion);
CREATE INDEX idx_receptores_capacidad ON receptores(capacidad_kg_dia);

-- Table: lotes (Surplus lots)
CREATE TABLE lotes (
    id SERIAL PRIMARY KEY,
    generador_id INTEGER NOT NULL REFERENCES generadores(id) ON DELETE CASCADE,
    producto VARCHAR(255) NOT NULL,
    categoria categoria_producto NOT NULL,
    cantidad_kg FLOAT NOT NULL,
    ubicacion GEOGRAPHY(POINT, 4326) NOT NULL,
    fecha_publicacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_limite TIMESTAMP NOT NULL,
    precio_base FLOAT NOT NULL,
    precio_actual FLOAT NOT NULL,
    temperatura_conservacion FLOAT,
    estado estado_lote DEFAULT 'activo',
    lote_origen VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_lotes_generador ON lotes(generador_id);
CREATE INDEX idx_lotes_estado ON lotes(estado);
CREATE INDEX idx_lotes_fecha_limite ON lotes(fecha_limite);
CREATE INDEX idx_lotes_categoria ON lotes(categoria);
CREATE INDEX idx_lotes_ubicacion ON lotes USING GIST(ubicacion);
CREATE INDEX idx_lotes_precio ON lotes(precio_actual);
CREATE INDEX idx_lotes_estado_fecha ON lotes(estado, fecha_limite);

-- Table: pujas (Bids)
CREATE TABLE pujas (
    id SERIAL PRIMARY KEY,
    lote_id INTEGER NOT NULL REFERENCES lotes(id) ON DELETE CASCADE,
    receptor_id INTEGER NOT NULL REFERENCES receptores(id) ON DELETE CASCADE,
    precio_oferta FLOAT NOT NULL,
    uso_previsto INTEGER NOT NULL CHECK (uso_previsto >= 1 AND uso_previsto <= 8),
    mensaje TEXT,
    estado estado_puja DEFAULT 'pendiente',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_pujas_lote ON pujas(lote_id);
CREATE INDEX idx_pujas_receptor ON pujas(receptor_id);
CREATE INDEX idx_pujas_estado ON pujas(estado);
CREATE INDEX idx_pujas_created ON pujas(created_at);

-- Table: transacciones (Completed transactions)
CREATE TABLE transacciones (
    id SERIAL PRIMARY KEY,
    lote_id INTEGER NOT NULL REFERENCES lotes(id),
    puja_id INTEGER NOT NULL REFERENCES pujas(id),
    generador_id INTEGER NOT NULL REFERENCES generadores(id),
    receptor_id INTEGER NOT NULL REFERENCES receptores(id),
    precio_final FLOAT NOT NULL,
    cantidad_kg FLOAT NOT NULL,
    uso_final INTEGER NOT NULL CHECK (uso_final >= 1 AND uso_final <= 8),
    co2_evitado_kg FLOAT,
    estado estado_transaccion DEFAULT 'pendiente',
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_transacciones_generador ON transacciones(generador_id);
CREATE INDEX idx_transacciones_receptor ON transacciones(receptor_id);
CREATE INDEX idx_transacciones_lote ON transacciones(lote_id);
CREATE INDEX idx_transacciones_estado ON transacciones(estado);
CREATE INDEX idx_transacciones_created ON transacciones(created_at);

-- Table: compliance_docs (Legal compliance documentation)
CREATE TABLE compliance_docs (
    id SERIAL PRIMARY KEY,
    transaccion_id INTEGER NOT NULL REFERENCES transacciones(id),
    tipo tipo_compliance_doc NOT NULL,
    contenido_json JSONB NOT NULL,
    pdf_url VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_compliance_docs_transaccion ON compliance_docs(transaccion_id);
CREATE INDEX idx_compliance_docs_tipo ON compliance_docs(tipo);

-- Table: carbon_credits (Carbon impact tracking)
CREATE TABLE carbon_credits (
    id SERIAL PRIMARY KEY,
    transaccion_id INTEGER NOT NULL REFERENCES transacciones(id),
    co2_evitado_kg FLOAT NOT NULL,
    tipo_calculo VARCHAR(100) NOT NULL,
    equivalencias JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_carbon_credits_transaccion ON carbon_credits(transaccion_id);

-- Table: predicciones_matching (ML predictions for matching)
CREATE TABLE predicciones_matching (
    id SERIAL PRIMARY KEY,
    generador_id INTEGER NOT NULL REFERENCES generadores(id),
    receptor_id INTEGER NOT NULL REFERENCES receptores(id),
    producto_predicho VARCHAR(255) NOT NULL,
    cantidad_predicha_kg FLOAT NOT NULL,
    fecha_predicha TIMESTAMP NOT NULL,
    confianza FLOAT NOT NULL CHECK (confianza >= 0 AND confianza <= 1),
    notificado BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_predicciones_generador ON predicciones_matching(generador_id);
CREATE INDEX idx_predicciones_receptor ON predicciones_matching(receptor_id);
CREATE INDEX idx_predicciones_confianza ON predicciones_matching(confianza DESC);

-- ==================== VIEWS ====================

-- Dashboard statistics view
CREATE OR REPLACE VIEW v_dashboard_stats AS
SELECT
    COUNT(DISTINCT t.id) as total_transacciones,
    COALESCE(SUM(t.cantidad_kg), 0) as total_kg_salvados,
    COALESCE(SUM(t.co2_evitado_kg), 0) as total_co2_evitado_kg,
    COALESCE(SUM(t.precio_final), 0) as dinero_total_transaccionado,
    COUNT(DISTINCT t.generador_id) as num_generadores,
    COUNT(DISTINCT t.receptor_id) as num_receptores,
    COALESCE(AVG(t.precio_final), 0) as precio_medio_transaccion
FROM transacciones t
WHERE t.estado = 'completada';

-- Top generators by volume
CREATE OR REPLACE VIEW v_top_generadores AS
SELECT
    g.id,
    g.nombre,
    g.tipo,
    COUNT(DISTINCT t.id) as num_transacciones,
    COALESCE(SUM(t.cantidad_kg), 0) as total_kg,
    COALESCE(SUM(t.co2_evitado_kg), 0) as total_co2_evitado_kg,
    COALESCE(AVG(t.precio_final), 0) as precio_medio
FROM generadores g
LEFT JOIN transacciones t ON g.id = t.generador_id AND t.estado = 'completada'
GROUP BY g.id, g.nombre, g.tipo
ORDER BY total_kg DESC;

-- Top receivers by volume
CREATE OR REPLACE VIEW v_top_receptores AS
SELECT
    r.id,
    r.nombre,
    r.tipo,
    COUNT(DISTINCT t.id) as num_transacciones,
    COALESCE(SUM(t.cantidad_kg), 0) as total_kg_procesados,
    COALESCE(SUM(t.co2_evitado_kg), 0) as total_co2_evitado_kg,
    COALESCE(AVG(t.precio_final), 0) as precio_medio
FROM receptores r
LEFT JOIN transacciones t ON r.id = t.receptor_id AND t.estado = 'completada'
GROUP BY r.id, r.nombre, r.tipo
ORDER BY total_kg_procesados DESC;

-- Active lots by category
CREATE OR REPLACE VIEW v_lotes_activos_por_categoria AS
SELECT
    categoria,
    COUNT(*) as num_lotes,
    COALESCE(SUM(cantidad_kg), 0) as total_kg,
    COALESCE(AVG(precio_actual), 0) as precio_medio,
    MIN(fecha_limite) as proximo_vencimiento
FROM lotes
WHERE estado = 'activo'
GROUP BY categoria;

-- ==================== SAMPLE DATA ====================

-- Sample generators (Spanish food businesses)
INSERT INTO generadores (nombre, tipo, cif, direccion, ubicacion, contacto_email, contacto_telefono, plan_suscripcion)
VALUES
    ('Carrefour Supermercado Madrid', 'retail', 'A12345678A', 'Calle Gran Vía 123, Madrid', ST_GeomFromText('POINT(-3.7038 40.4168)', 4326), 'contacto@carrefour-madrid.es', '+34 91 111 1111', 'premium'),
    ('Mercadona Centro Comercial Barcelona', 'retail', 'B87654321B', 'Avinguda Diagonal 456, Barcelona', ST_GeomFromText('POINT(2.1050 41.3874)', 4326), 'contacto@mercadona-bcn.es', '+34 93 222 2222', 'premium'),
    ('La Boquería Market Valencia', 'primario', 'C11223344C', 'Mercado Central s/n, Valencia', ST_GeomFromText('POINT(-0.3794 39.4699)', 4326), 'info@laboqueria-valencia.es', '+34 96 333 3333', 'basico'),
    ('Restaurante El Patio Sevilla', 'horeca', 'D55667788D', 'Calle Betis 789, Sevilla', ST_GeomFromText('POINT(-5.9988 37.3891)', 4326), 'chef@elpatio-sevilla.es', '+34 95 444 4444', 'estandar'),
    ('Industria Alimentaria Murcia S.L.', 'industria', 'E99887766E', 'Polígono Industrial Oeste, Murcia', ST_GeomFromText('POINT(-1.1289 37.9922)', 4326), 'ventas@indal-murcia.es', '+34 96 555 5555', 'premium');

-- Sample receivers (Food banks, processors, etc)
INSERT INTO receptores (nombre, tipo, cif, direccion, ubicacion, capacidad_kg_dia, categorias_interes, licencias)
VALUES
    ('Banco de Alimentos Madrid', 'banco_alimentos', 'F11111111F', 'Polígono Industrial Vallecas, Madrid', ST_GeomFromText('POINT(-3.6500 40.3800)', 4326), 500, ARRAY['frutas', 'verduras', 'lacteos', 'prepared'], ARRAY['ONG_CERTIFICADA', 'SANIDAD']),
    ('Transformadora de Alimentos Barcelona S.A.', 'transformador', 'G22222222G', 'Calle Industrial 100, Barcelona', ST_GeomFromText('POINT(2.0500 41.4000)', 4326), 1000, ARRAY['frutas', 'verduras', 'prepared'], ARRAY['ISO_22000', 'APPCC']),
    ('Biofeed Piensos Valencia', 'piensos', 'H33333333H', 'Camino Viejo 55, Valencia', ST_GeomFromText('POINT(-0.4200 39.5100)', 4326), 2000, ARRAY['carnes', 'pescados', 'panaderia', 'otros'], ARRAY['REGISTRO_PIENSOS']),
    ('Compost Plus Sevilla', 'compost', 'I44444444I', 'Vertedero Controlado s/n, Sevilla', ST_GeomFromText('POINT(-5.8500 37.3500)', 4326), 5000, ARRAY['frutas', 'verduras', 'otros'], ARRAY['AMBIENTAL']),
    ('Biogás Verde Murcia', 'biogas', 'J55555555J', 'Carretera a Lorca km 15, Murcia', ST_GeomFromText('POINT(-1.2000 38.0200)', 4326), 3000, ARRAY['carnes', 'pescados', 'panaderia', 'prepared'], ARRAY['ENERGIA_RENOVABLE']);

-- Sample lots
INSERT INTO lotes (generador_id, producto, categoria, cantidad_kg, ubicacion, fecha_limite, precio_base, precio_actual, temperatura_conservacion, lote_origen)
VALUES
    (1, 'Manzanas Golden', 'frutas', 150, ST_GeomFromText('POINT(-3.7038 40.4168)', 4326), CURRENT_TIMESTAMP + INTERVAL '3 days', 0.50, 0.42, 4, 'LOTE_001_2025'),
    (1, 'Lechuga Iceberg', 'verduras', 80, ST_GeomFromText('POINT(-3.7038 40.4168)', 4326), CURRENT_TIMESTAMP + INTERVAL '2 days', 0.35, 0.26, 2, 'LOTE_002_2025'),
    (2, 'Queso Fresco Local', 'lacteos', 45, ST_GeomFromText('POINT(2.1050 41.3874)', 4326), CURRENT_TIMESTAMP + INTERVAL '5 days', 4.50, 3.90, 4, 'LOTE_003_2025'),
    (4, 'Costillas de Cerdo', 'carnes', 60, ST_GeomFromText('POINT(-5.9988 37.3891)', 4326), CURRENT_TIMESTAMP + INTERVAL '2 days', 6.00, 4.20, 0, 'LOTE_004_2025'),
    (2, 'Pan Integral Sobrante', 'panaderia', 200, ST_GeomFromText('POINT(2.1050 41.3874)', 4326), CURRENT_TIMESTAMP + INTERVAL '1 day', 0.70, 0.35, 20, 'LOTE_005_2025');

COMMIT;
