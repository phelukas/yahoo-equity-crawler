from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_price(value: str) -> Decimal:
    """
    Converts a price string like "2,089.00" or "2089.00" to Decimal.
    Raises ValueError if cannot parse.
    """
    cleaned = (
        value.strip().replace(",", "").replace(" ", "")  # remove thousand separators
    )

    if cleaned in {"", "-", "—", "N/A"}:
        raise ValueError(f"Empty/invalid price: {value!r}")

    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid price format: {value!r}") from exc
