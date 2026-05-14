from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class FuelType(str, Enum):
    GASOLINE = "gasoline"
    DIESEL = "diesel"
    HEV = "hev"
    MHEV = "mhev"
    PHEV = "phev"
    BEV = "bev"
    LPG = "lpg"
    CNG = "cng"
    H2 = "hydrogen"


class Origin(str, Enum):
    EU_AUCTION = "eu_auction"
    EU_RETAIL_PRO = "eu_retail_pro"
    EU_RETAIL_PRO_REBU = "eu_retail_pro_rebu"
    EU_RETAIL_PRIVATE = "eu_retail_private"
    EXTRA_EU = "extra_eu"


class VATRegime(str, Enum):
    REBU = "rebu"
    GENERAL = "general"
    IMPORT_EXTRA_EU = "import_extra_eu"


class Vehicle(BaseModel):
    make: str
    model: str
    version: Optional[str] = None
    year: int = Field(ge=1950, le=2100)
    km: int = Field(ge=0)
    fuel: FuelType
    power_kw: Optional[float] = None
    power_cv: Optional[float] = None
    displacement_cc: Optional[int] = None
    co2_wltp: Optional[float] = Field(default=None, description="g/km WLTP")
    co2_nedc: Optional[float] = None
    euro_norm: Optional[str] = None
    transmission: Optional[Literal["manual", "automatic"]] = None
    drive: Optional[Literal["fwd", "rwd", "awd"]] = None
    seats: Optional[int] = 5
    vin: Optional[str] = None
    origin_country: str = Field(description="ISO-2 country code, e.g. DE, AE, ES")
    declared_damages: Optional[str] = None
    has_coc: bool = True
    has_service_book: bool = True
    previous_owners: Optional[int] = None

    @property
    def age_years(self) -> int:
        return max(0, date.today().year - self.year)

    @property
    def co2_effective(self) -> Optional[float]:
        if self.co2_wltp is not None:
            return self.co2_wltp
        if self.co2_nedc is not None:
            return self.co2_nedc * 1.21
        return None


class Comparable(BaseModel):
    source: str
    market: Literal["ES", "DE", "FR", "IT", "PT", "NL", "AE", "US", "UK", "JP"]
    price_eur: float
    km: int
    year: int
    url: Optional[str] = None
    days_listed: Optional[int] = None
    accident: bool = False


class AnalysisRequest(BaseModel):
    vehicle: Vehicle
    origin: Origin
    purchase_price: float = Field(description="Precio adjudicación / venta en EUR (o moneda local si fx_rate aportado)")
    purchase_currency: str = "EUR"
    fx_rate_to_eur: float = 1.0
    auction_fee_pct: float = 0.055
    auction_flat_fee: float = 150.0
    transport_eur: Optional[float] = None
    reconditioning_eur: Optional[float] = None
    target_margin_pct: float = 0.12
    sell_market: Literal["ES", "DE"] = "ES"
    vat_regime: VATRegime = VATRegime.REBU
    canary_islands: bool = False
    comparables: list[Comparable] = []
    days_in_stock: int = 35
    capital_cost_annual: float = 0.08
    income_tax_rate: float = 0.25
    extra_options: dict = {}
