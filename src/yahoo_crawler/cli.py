import argparse
import sys

from yahoo_crawler.config import Settings
from yahoo_crawler.logging_conf import setup_logging
from yahoo_crawler.service.run_crawl import run_crawl


import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yahoo-crawler",
        description="Coletor de dados de ações do Yahoo Finance. Extrai informações financeiras baseadas em filtros regionais.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--region",
        required=True,
        help="Nome da região/país para filtrar as ações (ex: 'Brazil', 'Argentina').",
    )

    parser.add_argument(
        "--output",
        default="output.csv",
        help="Caminho e nome do arquivo CSV onde os dados serão salvos.",
    )

    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Executa o navegador em modo oculto (use --no-headless para abrir a janela).",
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Define o nível de detalhamento dos logs de execução.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        default=False,
        help="Gera CSV completo (exchange,market_cap,currency,region).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Gera CSV minimal (symbol,name,price) conforme o PDF do desafio.",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.full and args.strict:
        parser.error("--full e --strict são mutuamente exclusivos.")

    strict = args.strict or not args.full

    settings = Settings(
        region=args.region,
        output=args.output,
        headless=args.headless,
        log_level=args.log_level,
        strict=strict,
    )

    setup_logging(settings.log_level)

    try:
        run_crawl(settings)
    except Exception as exc:
        print(f"❌ Error: {exc}", file=sys.stderr)
        sys.exit(1)
