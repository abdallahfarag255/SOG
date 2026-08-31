from dataclasses import dataclass
from typing import Optional


@dataclass
class Rider:
    id_rider: str
    driver_name: str = ""
    phone: str = ""
    state: str = ""
    rent_remaining: str = ""
    zone: str = ""
    complete_hours: str = ""
    complete_order: str = ""
    installments: str = ""
    wallet: str = ""
    equation: str = ""
    equation_sign: str = ""


@dataclass
class RiderStats:
    rider_id: str
    complete_hours: str = ""
    complete_order: str = ""
    installments: str = ""
    wallet: str = ""
    driver_name: str = ""
    phone: str = ""
    zone: str = ""
    stat_date: str = ""


@dataclass
class ImageAnalysis:
    filename: str
    filepath: str
    original_name: str
    text_variants: Optional[list] = None
    recognized_installments: str = ""
    error: Optional[Exception] = None
