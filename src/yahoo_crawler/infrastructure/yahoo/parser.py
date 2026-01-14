from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

@dataclass(frozen=True, slots=True)
class EquityRow:
    symbol: str
    name: str | None
    exchange: str | None
    market_cap: int | float | str | None
    price: int | float | str | None
    currency: str | None


def extract_screener_seed(page_source: str) -> tuple[str | None, dict | None]:
    """
    Encontra a URL do endpoint de screener buscado pelo SvelteKit e seu payload rawCriteria.
    Usa BeautifulSoup para cumprir o requisito do PDF com parsing real.
    """
    soup = BeautifulSoup(page_source, "lxml")
    for script in soup.find_all("script"):
        if "data-sveltekit-fetched" not in script.attrs:
            continue
        data_url = script.get("data-url")
        if not data_url or "predefined/saved" not in data_url:
            continue
        url = data_url.replace("&amp;", "&")
        body = (script.string or script.get_text() or "").strip()
        if not body:
            return url, None
        return url, _parse_seed_body(body)
    return None, None


def extract_screener_data_url(page_source: str) -> str | None:
    url, _criteria = extract_screener_seed(page_source)
    return url


def parse_screener_seed_body(body: str) -> dict | None:
    return _parse_seed_body(body)


def extract_embedded_state(page_source: str) -> dict:
    """Extrai o estado JSON embutido do HTML usando múltiplas estratégias."""
    script_info = _collect_script_info(page_source)

    state = _extract_next_data_state(page_source)
    if state is not None:
        return state

    state = _extract_preloaded_state(page_source)
    if state is not None:
        return state

    state = _extract_root_app_state(page_source)
    if state is not None:
        return state

    sveltekit_state = _extract_sveltekit_state(page_source)
    if sveltekit_state is not None:
        return sveltekit_state

    state = _extract_yahoo_context_state(page_source)
    if state is not None and _score_state(state) > 0:
        return state

    heuristic_state = _extract_script_json_heuristic(page_source)
    if heuristic_state is not None:
        return heuristic_state

    artifact_path = _save_parse_fail_state(script_info, page_source)
    raise RuntimeError(
        "Embedded state not found (no __NEXT_DATA__, __PRELOADED_STATE__, root.App.main, "
        "YAHOO.context, or SvelteKit JSON). "
        f"Saved parse artifacts at {artifact_path}"
    )


def extract_quotes(state: dict) -> list[dict]:
    """Encontra a lista de dicionários de cotações dentro da árvore de estado extraída."""
    candidates = _candidates_from_known_paths(state)
    best = _pick_best_candidate(candidates)
    if best:
        return _coerce_quotes(best[2])

    stores = _get_path(state, ("context", "dispatcher", "stores"))
    if isinstance(stores, dict):
        best = _pick_best_candidate(_find_quote_lists(stores, ["context", "dispatcher", "stores"]))
        if best:
            return _coerce_quotes(best[2])

    for section_path in (("props", "pageProps"), ("pageProps",), ("props",)):
        section = _get_path(state, section_path)
        if isinstance(section, (dict, list)):
            best = _pick_best_candidate(_find_quote_lists(section, list(section_path)))
            if best:
                return _coerce_quotes(best[2])

    best = _pick_best_candidate(_find_quote_lists(state, []))
    if best:
        return _coerce_quotes(best[2])

    top_keys = _safe_keys(state)
    store_keys = _safe_keys(stores) if isinstance(stores, dict) else []
    raise RuntimeError(
        "Quotes list not found. Top-level keys="
        f"{top_keys} | stores={store_keys}. "
        "Run scripts/debug_state_path.py to inspect candidate paths."
    )


def normalize_equities(quotes: list[dict]) -> list[EquityRow]:
    """Normaliza dicionários de cotações em registros EquityRow."""
    rows: list[EquityRow] = []
    for quote in quotes:
        if not isinstance(quote, dict):
            continue
        symbol = quote.get("symbol") or quote.get("ticker")
        if not symbol:
            continue
        name = _first_non_empty(
            quote.get("shortName"),
            quote.get("longName"),
            quote.get("name"),
            quote.get("displayName"),
        )
        exchange = _first_non_empty(
            quote.get("exchange"),
            quote.get("fullExchangeName"),
            quote.get("exchangeName"),
        )
        market_cap = _normalize_value(quote.get("marketCap"))
        price_value = quote.get("regularMarketPrice")
        if price_value is None:
            price_value = quote.get("regularMarketPreviousClose")
            if price_value is not None:
                logger.info(
                    "Preço alternativo para regularMarketPreviousClose | símbolo=%s", symbol
                )
        if price_value is None:
            price_value = quote.get("price") or quote.get("lastPrice")
        price = _normalize_value(price_value)
        currency = quote.get("currency")
        rows.append(
            EquityRow(
                symbol=str(symbol),
                name=name,
                exchange=exchange,
                market_cap=market_cap,
                price=price,
                currency=currency,
            )
        )
    return rows


_KNOWN_PATHS: tuple[tuple[Any, ...], ...] = (
    ("context", "dispatcher", "stores", "ScreenerResultsStore", "results", "quotes"),
    (
        "context",
        "dispatcher",
        "stores",
        "ScreenerResultsStore",
        "results",
        "finance",
        "result",
        0,
        "quotes",
    ),
    ("context", "dispatcher", "stores", "ScreenerResultsStore", "quotes"),
    ("context", "dispatcher", "stores", "ScreenerResultsStore", "results"),
    ("context", "dispatcher", "stores", "ScreenerStore", "results", "quotes"),
    ("context", "dispatcher", "stores", "ScreenerStore", "quotes"),
    ("context", "dispatcher", "stores", "ScreenerStore", "results"),
)


def _extract_root_app_state(page_source: str) -> dict | None:
    match = re.search(r"root\.App\.main\s*=\s*", page_source)
    if not match:
        return None
    start = page_source.find("{", match.end())
    if start == -1:
        raise RuntimeError("root.App.main found but JSON object not found.")
    json_text = _extract_balanced_json(page_source, start)
    return _loads_json(json_text, "root.App.main")


def _extract_preloaded_state(page_source: str) -> dict | None:
    match = re.search(r"__PRELOADED_STATE__\s*=\s*", page_source)
    if not match:
        return None
    start = page_source.find("{", match.end())
    if start == -1:
        raise RuntimeError("__PRELOADED_STATE__ found but JSON object not found.")
    json_text = _extract_balanced_json(page_source, start)
    return _loads_json(json_text, "__PRELOADED_STATE__")


def _extract_next_data_state(page_source: str) -> dict | None:
    match = re.search(
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(?P<data>.*?)</script>',
        page_source,
        re.DOTALL,
    )
    if not match:
        return None
    json_text = match.group("data").strip()
    if not json_text:
        raise RuntimeError("__NEXT_DATA__ script tag found but empty.")
    return _loads_json(json_text, "__NEXT_DATA__")


def _extract_yahoo_context_state(page_source: str) -> dict | None:
    match = re.search(r"YAHOO\.context\s*=\s*", page_source)
    if not match:
        return None
    start = page_source.find("{", match.end())
    if start == -1:
        raise RuntimeError("YAHOO.context found but JSON object not found.")
    json_text = _extract_balanced_json(page_source, start)
    return _loads_json(json_text, "YAHOO.context")


def _extract_sveltekit_state(page_source: str) -> dict | None:
    entries = _extract_application_json_scripts(page_source)
    if not entries:
        return None

    best = _pick_best_state(entries)
    if best is not None:
        return best

    return {"__sveltekit__": entries}


def _extract_script_json_heuristic(page_source: str) -> dict | None:
    keywords = ("quotes", "quote", "screener", "equity", "finance", "results")
    for attrs, body in _iter_script_tags(page_source):
        if not body:
            continue
        if not any(keyword in body for keyword in keywords):
            continue
        start = body.find("{")
        if start == -1:
            continue
        try:
            json_text = _extract_balanced_json(body, start)
            data = _loads_json(json_text, "script-heuristic")
            return data
        except RuntimeError:
            continue
    return None


def _extract_application_json_scripts(page_source: str) -> list[dict]:
    entries: list[dict] = []
    for attrs, body in _iter_script_tags(page_source):
        if not body:
            continue
        script_type = attrs.get("type", "")
        is_app_json = script_type == "application/json" or "application/json" in script_type
        if not is_app_json:
            continue
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            continue
        entry: dict[str, Any] = {
            "attrs": attrs,
            "payload": payload,
        }
        body_value = payload.get("body") if isinstance(payload, dict) else None
        if isinstance(body_value, str):
            body_value = body_value.strip()
            if body_value.startswith("{") or body_value.startswith("["):
                try:
                    entry["body"] = json.loads(body_value)
                except json.JSONDecodeError:
                    entry["body"] = body_value
        entries.append(entry)
    return entries


def _extract_raw_criteria(payload: dict) -> dict | None:
    result = payload.get("finance", {}).get("result")
    if not isinstance(result, list) or not result:
        return None
    root = result[0] if isinstance(result[0], dict) else None
    if not isinstance(root, dict):
        return None
    raw = root.get("rawCriteria")
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _parse_seed_body(body: str) -> dict | None:
    try:
        outer = json.loads(body)
    except json.JSONDecodeError:
        return None
    raw_body = outer.get("body")
    if not isinstance(raw_body, str):
        return None
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return None
    return _extract_raw_criteria(payload)


def _pick_best_state(entries: list[dict]) -> dict | None:
    best: tuple[int, dict] | None = None
    for entry in entries:
        candidate = entry.get("body") if isinstance(entry.get("body"), dict) else entry.get("payload")
        if not isinstance(candidate, dict):
            continue
        score = _score_state(candidate)
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, candidate)
    return best[1] if best else None


def _score_state(state: dict) -> int:
    score = 0
    if "quotes" in state:
        score += 5
    if "finance" in state:
        score += 3
    candidates = _find_quote_lists(state, [])
    if candidates:
        score += max(candidate[0] for candidate in candidates)
    return score


def _extract_balanced_json(text: str, start_index: int) -> str:
    depth = 0
    in_string = False
    escape = False
    for index in range(start_index, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start_index : index + 1]
    raise RuntimeError("Unbalanced JSON while parsing root.App.main.")


def _loads_json(payload: str, source: str) -> dict:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to decode {source} JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{source} JSON did not produce a dict.")
    return data


def _get_path(data: Any, path: Iterable[Any]) -> Any:
    current = data
    for part in path:
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                return None
            current = current[part]
        else:
            if not isinstance(current, dict):
                return None
            if part not in current:
                return None
            current = current[part]
    return current


def _find_quote_lists(data: Any, base_path: list[Any], max_depth: int = 16) -> list[tuple[int, list[Any], list[dict]]]:
    candidates: list[tuple[int, list[Any], list[dict]]] = []
    stack: list[tuple[Any, list[Any]]] = [(data, base_path)]
    while stack:
        node, path = stack.pop()
        if len(path) > max_depth:
            continue
        if isinstance(node, dict):
            for key, value in node.items():
                next_path = path + [key]
                if isinstance(value, list):
                    score = _score_quote_list(value, next_path)
                    if score:
                        candidates.append((score, next_path, value))
                elif key == "quotes" and isinstance(value, dict):
                    quote_list = list(value.values())
                    score = _score_quote_list(quote_list, next_path)
                    if score:
                        candidates.append((score, next_path, quote_list))
                if isinstance(value, (dict, list)):
                    stack.append((value, next_path))
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                if isinstance(item, (dict, list)):
                    stack.append((item, path + [idx]))
    return candidates


def _score_quote_list(items: list[Any], path: list[Any]) -> int:
    if not items:
        return 0
    symbol_hits = 0
    score = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("symbol") or item.get("ticker"):
            symbol_hits += 1
            score += 2
            if _normalize_value(item.get("regularMarketPrice")) is not None:
                score += 1
            if _normalize_value(item.get("marketCap")) is not None:
                score += 1
    if symbol_hits == 0:
        return 0
    path_str = ".".join(str(part) for part in path if isinstance(part, str))
    if "Screener" in path_str:
        score += 10
    if "quotes" in path_str:
        score += 5
    if "results" in path_str:
        score += 2
    return score


def _pick_best_candidate(
    candidates: list[tuple[int, list[Any], list[dict]]]
) -> tuple[int, list[Any], list[dict]] | None:
    best: tuple[int, list[Any], list[dict]] | None = None
    for candidate in candidates:
        if best is None:
            best = candidate
            continue
        if candidate[0] > best[0]:
            best = candidate
            continue
        if candidate[0] == best[0] and len(candidate[2]) > len(best[2]):
            best = candidate
    return best


def _candidates_from_known_paths(state: dict) -> list[tuple[int, list[Any], list[dict]]]:
    candidates: list[tuple[int, list[Any], list[dict]]] = []
    for path in _KNOWN_PATHS:
        value = _get_path(state, path)
        if isinstance(value, dict) and "quotes" in value:
            value = value.get("quotes")
            path = (*path, "quotes")
        if isinstance(value, dict):
            value = list(value.values())
        if isinstance(value, list):
            score = _score_quote_list(value, list(path))
            if score:
                candidates.append((score, list(path), value))
    return candidates


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "raw" in value:
            return value.get("raw")
        if "fmt" in value:
            return value.get("fmt")
    return value


def _coerce_quotes(quotes: Any) -> list[dict]:
    if isinstance(quotes, list):
        return quotes
    if isinstance(quotes, dict):
        return list(quotes.values())
    return []


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if value:
            return str(value)
    return None


def _safe_keys(data: Any, limit: int = 40) -> list[str]:
    if not isinstance(data, dict):
        return []
    return list(data.keys())[:limit]


def _iter_script_tags(page_source: str) -> Iterable[tuple[dict[str, str], str]]:
    for match in re.finditer(
        r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>",
        page_source,
        re.DOTALL | re.IGNORECASE,
    ):
        attrs = _parse_attrs(match.group("attrs") or "")
        body = match.group("body") or ""
        yield attrs, body.strip()


def _parse_attrs(attrs_text: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r"([a-zA-Z0-9_-]+)\s*=\s*\"([^\"]*)\"", attrs_text):
        attrs[match.group(1)] = match.group(2)
    for match in re.finditer(r"([a-zA-Z0-9_-]+)\s*=\s*'([^']*)'", attrs_text):
        attrs[match.group(1)] = match.group(2)
    return attrs


def _collect_script_info(page_source: str) -> dict[str, Any]:
    scripts = []
    for attrs, body in _iter_script_tags(page_source):
        scripts.append(
            {
                "id": attrs.get("id"),
                "type": attrs.get("type"),
                "data_url": attrs.get("data-url"),
                "data_sveltekit": "data-sveltekit-fetched" in attrs,
                "length": len(body),
            }
        )
    return {
        "total_scripts": len(scripts),
        "scripts": scripts[:40],
    }


def _save_parse_fail_state(info: dict[str, Any], page_source: str) -> Path:
    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = artifacts / f"parse_fail_state_{ts}.json"
    snippets = []
    for attrs, body in list(_iter_script_tags(page_source))[:5]:
        snippets.append(
            {
                "id": attrs.get("id"),
                "type": attrs.get("type"),
                "data_url": attrs.get("data-url"),
                "snippet": body[:800],
            }
        )
    payload = {
        "info": info,
        "snippets": snippets,
    }
    out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return out
