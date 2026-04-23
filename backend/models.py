"""
Pydantic models for the AEGIS-FOOD marketplace.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field, EmailStr


class TipoGenerador(str, Enum):
    retail = "retail"
    industria = "industria"
    horeca = "horeca"
    primario = "primario"


class TipoReceptor(str, Enum):
    banco_alimentos = "banco_alimentos"
    transformador = "transformador"
    piensos = "piensos"
    compost = "compost"
    biogas = "biogas"


class Categoria(str, Enum):
    frutas = "frutas"
    verduras = "verduras"
    lacteos = "lacteos"
    carnes = "carnes"
    pescados = "pescados"
    panaderia = "panaderia"
    prepared = "prepared"
    otros = "otros"


class EstadoLote(str, Enum):
    activo = "activo"
    adjudicado = "adjudicado"
    expirado = "expirado"
    retirado = "retirado"


class EstadoPuja(str, Enum):
    pendiente = "pendiente"
    aceptada = "aceptada"
    rechazada = "rechazada"


class EstadoTransaccion(str, Enum):
    pendiente = "pendiente"
    completada = "completada"
    cancelada = "cancelada"


class OutcomeTransaccion(str, Enum):
    """Where the surplus actually ended up.

    This is the piece of data that matters for SurplusAI's disposal-guarantee
    brand — it turns an unknown audit trail into a clean story for Ley 1/2025
    inspectors and for ESG reports sold to customers.
    """
    donated_ong = "donated_ong"           # ONG / Cruz Roja / Cáritas (human consumption)
    food_bank = "food_bank"               # Banco de alimentos (human consumption)
    cattle_feed = "cattle_feed"           # Pienso — SANDACH / REGISTRO_PIENSOS
    biomass_biogas = "biomass_biogas"     # Valorización biogás (lot → materia prima)
    compost = "compost"                   # Compostaje aeróbico
    energy_biogas = "energy_biogas"       # Digestor energético (vs materia-prima biogás)


class UsoFinal(int, Enum):
    """Legal hierarchy per Ley 1/2025"""
    prevencion = 1
    donacion_consumo = 2
    transformacion = 3
    alimentacion_animal = 4
    uso_industrial = 5
    compostaje = 6
    biogas = 7
    eliminacion = 8


class TipoComplianceDoc(str, Enum):
    certificado_donacion = "certificado_donacion"
    albaran = "albaran"
    trazabilidad = "trazabilidad"


# Generador models
class GeneradorBase(BaseModel):
    nombre: str
    tipo: TipoGenerador
    cif: str
    direccion: str
    ubicacion_lat: float
    ubicacion_lon: float
    contacto_email: EmailStr
    contacto_telefono: str
    plan_suscripcion: str = "basico"


class GeneradorCreate(GeneradorBase):
    pass


class GeneradorUpdate(BaseModel):
    nombre: Optional[str] = None
    direccion: Optional[str] = None
    contacto_email: Optional[EmailStr] = None
    contacto_telefono: Optional[str] = None
    plan_suscripcion: Optional[str] = None


class Generador(GeneradorBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# Receptor models
class ReceptorBase(BaseModel):
    nombre: str
    tipo: TipoReceptor
    cif: str
    direccion: str
    ubicacion_lat: float
    ubicacion_lon: float
    capacidad_kg_dia: float
    categorias_interes: List[Categoria] = []
    licencias: List[str] = []


class ReceptorCreate(ReceptorBase):
    pass


class ReceptorUpdate(BaseModel):
    nombre: Optional[str] = None
    direccion: Optional[str] = None
    capacidad_kg_dia: Optional[float] = None
    categorias_interes: Optional[List[Categoria]] = None
    licencias: Optional[List[str]] = None


class Receptor(ReceptorBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# Lote models
class LoteBase(BaseModel):
    producto: str
    cantidad_kg: float
    categoria: Categoria
    fecha_limite: datetime
    precio_base: float
    temperatura_conservacion: Optional[float] = None
    lote_origen: Optional[str] = None


class LoteCreate(LoteBase):
    generador_id: int
    ubicacion_lat: float
    ubicacion_lon: float


class LoteUpdate(BaseModel):
    producto: Optional[str] = None
    cantidad_kg: Optional[float] = None
    categoria: Optional[Categoria] = None
    fecha_limite: Optional[datetime] = None
    precio_base: Optional[float] = None
    estado: Optional[EstadoLote] = None
    temperatura_conservacion: Optional[float] = None


class Lote(LoteBase):
    id: int
    generador_id: int
    ubicacion_lat: float
    ubicacion_lon: float
    fecha_publicacion: datetime
    precio_actual: float
    estado: EstadoLote
    created_at: datetime

    class Config:
        from_attributes = True


class LoteWithBids(Lote):
    num_bids: int = 0
    precio_oferta_mas_alta: Optional[float] = None


# Puja models
class PujaBase(BaseModel):
    lote_id: int
    receptor_id: int
    precio_oferta: float
    uso_previsto: UsoFinal
    mensaje: Optional[str] = None


class PujaCreate(PujaBase):
    pass


class PujaUpdate(BaseModel):
    precio_oferta: Optional[float] = None
    mensaje: Optional[str] = None
    estado: Optional[EstadoPuja] = None


class Puja(PujaBase):
    id: int
    estado: EstadoPuja
    created_at: datetime

    class Config:
        from_attributes = True


# Transaccion models
class TransaccionBase(BaseModel):
    lote_id: int
    puja_id: int
    cantidad_kg: float
    precio_final: float
    uso_final: UsoFinal
    # New (v2 business model): split revenue streams explicitly so the
    # dashboard can distinguish "GMV SurplusAI" (what we invoice) from
    # "valor comida rescatada" (the price of the food itself, which is
    # often €0 or symbolic).
    service_fee_eur: Optional[float] = None    # tarifa gestión lote (€20–80)
    logistics_fee_eur: Optional[float] = None  # €0.25/km, MIN €25 (P0.2)
    biomass_revenue_eur: Optional[float] = None  # € cobrados a la planta biogás/compost
    outcome: Optional[OutcomeTransaccion] = None


class TransaccionCreate(TransaccionBase):
    distance_km: Optional[float] = None  # distance between generador and receptor,
                                         # used to compute logistics_fee when the
                                         # client doesn't pass one explicitly


class Transaccion(TransaccionBase):
    id: int
    generador_id: int
    receptor_id: int
    estado: EstadoTransaccion
    co2_evitado_kg: Optional[float] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# Compliance models
class ComplianceDocBase(BaseModel):
    transaccion_id: int
    tipo: TipoComplianceDoc
    contenido_json: Dict[str, Any]
    pdf_url: Optional[str] = None


class ComplianceDocCreate(ComplianceDocBase):
    pass


class ComplianceDoc(ComplianceDocBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# Carbon credits models
class CarbonCreditBase(BaseModel):
    transaccion_id: int
    co2_evitado_kg: float
    tipo_calculo: str
    equivalencias: Dict[str, Any]


class CarbonCreditCreate(CarbonCreditBase):
    pass


class CarbonCredit(CarbonCreditBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# Matching predictions models
class PrediccionMatching(BaseModel):
    id: int
    generador_id: int
    receptor_id: int
    producto_predicho: str
    cantidad_predicha_kg: float
    fecha_predicha: datetime
    confianza: float
    notificado: bool
    created_at: datetime

    class Config:
        from_attributes = True


# API Response models
class LoteFiltros(BaseModel):
    categoria: Optional[Categoria] = None
    ubicacion_lat: Optional[float] = None
    ubicacion_lon: Optional[float] = None
    radio_km: Optional[float] = 50.0
    precio_max: Optional[float] = None
    fecha_limite_min: Optional[datetime] = None


class StatsResponse(BaseModel):
    total_kg_saved: float
    total_transactions: int
    co2_avoided_kg: float
    money_saved: float
    num_generadores: int
    num_receptores: int
    avg_transaction_value: float


class HealthResponse(BaseModel):
    status: str
    database: str
    timestamp: datetime


class MatchResponse(BaseModel):
    receptor_id: int
    receptor_nombre: str
    producto_predicho: str
    cantidad_predicha_kg: float
    fecha_predicha: datetime
    confianza: float
    score_match: float


# ---- Automatic matching (P0.1) ----
class AutoMatchCandidate(BaseModel):
    receptor_id: int
    receptor_nombre: str
    receptor_tipo: str
    distance_km: float
    score: float
    priority_factor: float
    urgency_factor: float
    weight_factor: float


class AutoMatchResult(BaseModel):
    lote_id: int
    categoria: str
    matches: List[AutoMatchCandidate]
    notified_top_n: int
    fallback_available: bool


# ---- Subscription plans (P0.5) ----
class SubscriptionPlan(BaseModel):
    id: int
    name: str
    price_monthly_eur: float
    max_lots_month: Optional[int] = None
    includes: Dict[str, Any]

    class Config:
        from_attributes = True
