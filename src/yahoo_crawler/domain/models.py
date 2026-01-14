from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class EquityRow:
    symbol: str
    name: str
    price: Decimal
