import csv
import json
import logging
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from typing import Any

from yahoo_crawler.config import Settings
from yahoo_crawler.infrastructure.browser.driver_factory import (
    DriverConfig,
    create_chrome_driver,
)
from yahoo_crawler.infrastructure.yahoo.navigator import YahooNavigator
from yahoo_crawler.infrastructure.yahoo.parser import (
    extract_screener_seed,
    parse_screener_seed_body,
    extract_embedded_state,
    extract_quotes,
    normalize_equities,
)
from yahoo_crawler.infrastructure.yahoo.quote_client import YahooQuoteClient
from yahoo_crawler.infrastructure.yahoo.screener_client import SCREENER_URL, YahooScreenerClient

logger = logging.getLogger(__name__)

CSV_HEADERS = [
    "symbol",
    "name",
    "exchange",
    "market_cap",
    "price",
    "currency",
    "region",
]
MINIMAL_HEADERS = ["symbol", "name", "price"]


def run_crawl(settings: Settings) -> None:
    logger.info(
        "Iniciando coletor | região=%s | arquivo_saída=%s",
        settings.region,
        settings.output,
    )

    driver = create_chrome_driver(DriverConfig(headless=settings.headless))
    try:
        nav = YahooNavigator(driver)
        nav.open(region=settings.region)

        logger.info("Após abrir | url=%s", driver.current_url)

        seed_ready = nav.wait_for_screener_seed()
        if not seed_ready:
            logger.warning("Seed do screener não detectada no DOM após a espera")
        result = nav.get_page_source()

        artifacts = Path("artifacts")
        artifacts.mkdir(exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        html_file = artifacts / f"last_page_{ts}.html"
        html_file.write_text(result.page_source, encoding="utf-8")
        logger.info("HTML de depuração salvo | caminho=%s", html_file)

        logger.info("Fonte da página carregada | chars=%s", len(result.page_source))

        rows_data: list[dict] = []
        source = "html"

        screener_url, screener_criteria = extract_screener_seed(result.page_source)
        if not screener_url:
            dom_url, dom_body = nav.get_screener_seed()
            if dom_url:
                screener_url = dom_url
                if dom_body:
                    screener_criteria = parse_screener_seed_body(dom_body)
                logger.info("Seed do screener recuperada do DOM")
        if not screener_url:
            screener_url = SCREENER_URL
            logger.warning("Seed do screener ausente; usando critérios padrão do screener")

        try:
            if screener_criteria:
                logger.info("Critérios do screener encontrados | região=%s", settings.region)
            screener = YahooScreenerClient(
                region=settings.region,
                user_agent=nav.get_user_agent(),
                cookies=nav.get_cookies(),
                base_url=screener_url,
                criteria=screener_criteria,
            )
            rows_data, stats = screener.fetch_all()
            if rows_data:
                source = "screener_api"
                logger.info(
                    "Paginação do screener concluída | páginas=%s | total_itens=%s | únicos=%s | duplicados=%s | total_esperado=%s | tempo=%.2fs",
                    stats.get("pages"),
                    stats.get("total_items"),
                    stats.get("unique_symbols"),
                    stats.get("duplicates"),
                    stats.get("total_expected"),
                    stats.get("elapsed_seconds"),
                )
            else:
                logger.warning("Paginação do screener não retornou linhas; voltando para HTML")
        except Exception:
            logger.exception("Paginação do screener falhou; voltando para HTML")

        if not rows_data:
            state = None
            state_source = "html"
            try:
                state = extract_embedded_state(result.page_source)
            except Exception as exc:
                logger.warning("Estado embutido não encontrado no HTML | erro=%s", exc)
                state = nav.get_runtime_state()
                state_source = "runtime"
                if state is None:
                    raise

            try:
                quotes = extract_quotes(state)
                rows = normalize_equities(quotes)
            except Exception as exc:
                logger.warning(
                    "Falha ao interpretar cotações do estado %s | erro=%s",
                    state_source,
                    exc,
                )
                runtime_state = nav.get_runtime_state()
                if runtime_state and runtime_state is not state:
                    state = runtime_state
                    state_source = "runtime"
                    quotes = extract_quotes(state)
                    rows = normalize_equities(quotes)
                else:
                    artifact_path = _save_parse_state(state, "parse_fail_state")
                    logger.error("Estado de falha de parsing salvo | caminho=%s", artifact_path)
                    logger.error(
                        "Chaves do estado | topo=%s | stores=%s",
                        _safe_keys(state),
                        _safe_keys(_get_stores(state)),
                    )
                    raise
            rows_data = [asdict(row) for row in rows]
            source = state_source
        try:
            client = YahooQuoteClient(
                region=settings.region,
                user_agent=nav.get_user_agent(),
                cookies=nav.get_cookies(),
            )
            rows_data, stats = client.enrich_rows(rows_data)
            logger.info(
                "Enriquecimento concluído | símbolos=%s | lotes=%s | moeda=%s | valor_mercado=%s | falhas=%s | tempo=%.2fs",
                stats.get("total_symbols"),
                stats.get("batches"),
                stats.get("enriched_currency"),
                stats.get("enriched_market_cap"),
                stats.get("failures"),
                stats.get("elapsed_seconds"),
            )
        except Exception:
            logger.exception("Enriquecimento de cotações falhou; continuando com linhas básicas")

        empty_currency = sum(1 for row in rows_data if not row.get("currency"))
        empty_market_cap = sum(1 for row in rows_data if not row.get("market_cap"))
        logger.info(
            "Linhas extraídas | total=%s | fonte=%s | moeda_vazia=%s | valor_mercado_vazio=%s",
            len(rows_data),
            source,
            empty_currency,
            empty_market_cap,
        )

        output_path = Path(settings.output)
        _write_csv(rows_data, output_path, region=settings.region, strict=settings.strict)
        logger.info("CSV gerado | caminho=%s", output_path)

    finally:
        try:
            driver.quit()
        except Exception:
            logger.exception("Falha ao encerrar o driver corretamente")


def _write_csv(rows: list[dict], output_path: Path, region: str, strict: bool) -> None:
    headers = MINIMAL_HEADERS if strict else CSV_HEADERS
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        quoting = csv.QUOTE_ALL if strict else csv.QUOTE_MINIMAL
        writer = csv.DictWriter(handle, fieldnames=headers, quoting=quoting)
        writer.writeheader()
        for row in rows:
            payload = {
                "symbol": row.get("symbol", ""),
                "name": row.get("name") or "",
                "price": row.get("price") or "",
            }
            if not strict:
                payload.update(
                    {
                        "exchange": row.get("exchange") or "",
                        "market_cap": row.get("market_cap") or "",
                        "currency": row.get("currency") or "",
                        "region": region,
                    }
                )
            writer.writerow(payload)


def _save_parse_state(state: dict, tag: str, max_chars: int = 250_000) -> Path:
    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    state_file = artifacts / f"{tag}_{ts}.json"
    payload = _summarize_state(state, max_chars=max_chars)
    state_file.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return state_file


def _summarize_state(state: dict, max_chars: int) -> dict[str, Any]:
    raw = json.dumps(state, ensure_ascii=True)
    return {
        "top_level_keys": _safe_keys(state),
        "stores_keys": _safe_keys(_get_stores(state)),
        "truncated": len(raw) > max_chars,
        "total_chars": len(raw),
        "preview": raw[:max_chars],
    }


def _get_stores(state: dict) -> Any:
    if not isinstance(state, dict):
        return None
    context = state.get("context")
    if not isinstance(context, dict):
        return None
    dispatcher = context.get("dispatcher")
    if not isinstance(dispatcher, dict):
        return None
    return dispatcher.get("stores")


def _safe_keys(data: Any, limit: int = 40) -> list[str]:
    if not isinstance(data, dict):
        return []
    return list(data.keys())[:limit]
