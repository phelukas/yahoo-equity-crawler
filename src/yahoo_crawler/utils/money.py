from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_price(value: str) -> Decimal:
    """
    Converte uma string de preço como "2,089.00" ou "2089.00" para Decimal.
    Lança ValueError se não conseguir interpretar.
    """
    cleaned = (
        value.strip().replace(",", "").replace(" ", "")  # remove separadores de milhar
    )

    if cleaned in {"", "-", "—", "N/A"}:
        raise ValueError(f"Empty/invalid price: {value!r}")

    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid price format: {value!r}") from exc
