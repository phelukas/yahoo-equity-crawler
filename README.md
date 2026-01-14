# Yahoo Equity Crawler

Crawler em Python para o Yahoo Finance Equity Screener.  
Atende aos requisitos do teste: Selenium, BeautifulSoup e orientacao a objetos.

## Requisitos
- Python 3.10+
- Google Chrome instalado (execucao local com Selenium)
- Selenium Manager baixa o driver automaticamente a partir do Chrome instalado
- Docker (opcional, para rodar sem setup local)

## Instalacao local (passo a passo)
1) `python -m venv .venv`
2) `source .venv/bin/activate`
3) `pip install -e .`

## Uso rapido
- CSV minimal (padrao do PDF):
  - `yahoo-crawler --region Argentina --log-level INFO --output output.csv`
- CSV completo:
  - `yahoo-crawler --region Argentina --full --output output_full.csv`
- Debug visual (abre o navegador):
  - `yahoo-crawler --region Argentina --no-headless --log-level DEBUG`

## Referencia de comandos (todas as flags)
- `--region` (obrigatorio): nome da regiao. Suportadas: `United States`, `Argentina`, `Brazil`, `Chile`, `Mexico`.
- `--output` (opcional): caminho do CSV. Default: `output.csv`.
- `--strict` (opcional): gera CSV minimal no formato do PDF (`symbol,name,price`).
- `--full` (opcional): gera CSV completo com `exchange,market_cap,currency,region`.
- `--log-level` (opcional): `DEBUG|INFO|WARNING|ERROR`. Default: `INFO`.
- `--headless/--no-headless` (opcional): ativa/desativa o modo headless. Default: headless.

Observacao: `--strict` e `--full` sao mutuamente exclusivos.  
Se nenhuma flag for informada, o default e o CSV minimal.

## Formato de saida
CSV minimal (padrao):
```
"symbol","name","price"
"AMX.BA","America Movil, S.A.B. de C.V.","2089.00"
```

CSV completo (com `--full`):
```
symbol,name,exchange,market_cap,price,currency,region
```

## Como funciona (fluxo)
1) Selenium abre o screener com `?region=XX`.
2) O crawler extrai o endpoint SvelteKit e o `rawCriteria`.
3) Pagina via endpoint do screener com `offset/size` (TODOS os itens da regiao).
4) Se o endpoint falhar, cai para parsing do HTML.
5) Enrichment opcional completa `currency` e `market_cap`.
6) Gera CSV minimal ou completo.

## Intraday price
O campo `price` usa `regularMarketPrice.raw` (intraday).  
Se ausente, faz fallback para `regularMarketPreviousClose.raw` e registra log.

## Paginacao e dedupe
- Pagina com `start/count` (ou `offset/size` no payload do screener).
- Para quando a pagina vem vazia ou com menos itens que o `count`.
- Deduplica por `symbol`.

## Artifacts e debug
Falhas geram arquivos em `artifacts/`:
- `last_page_<ts>.html`
- `parse_fail_state_<ts>.json`
- `quote_http_<status>_<ts>.txt`
- `screener_http_<status>_<ts>.txt`
- `screener_json_<ts>.txt`

## Edge cases (market_cap)
Alguns ativos (ETFs, microcaps, OTC) nao tem `marketCap` no Yahoo.  
O CSV mantem o campo vazio nesses casos (sem quebrar o pipeline).

## Docker
Build:
- `docker build -t yahoo-crawler .`

Executar (CSV minimal):
- `docker run --rm -v "$PWD:/app" yahoo-crawler --region Argentina --output /app/output.csv`

Executar (CSV completo):
- `docker run --rm -v "$PWD:/app" yahoo-crawler --region Argentina --full --output /app/output_full.csv`

## Docker Compose
- `docker compose run --rm crawler --region Argentina --output /app/output.csv`

Observacao: o Docker usa Chromium dentro do container.

## Validado
- Docker: `docker run --rm -v "$PWD:/app" yahoo-crawler --region Argentina --output /app/output.csv`
- Exemplo de contagem (Argentina): `wc -l output.csv` ~= 1049 (header + 1048 itens)

## Testes
- `pytest -q`

## Validacao rapida
- `yahoo-crawler --region Argentina --log-level INFO --output output.csv`
- `wc -l output.csv`
- `head -n 2 output.csv`
- `pytest -q`

## Troubleshooting
- 401 Invalid Crumb: rode novamente (cookies/crumb expiram) ou tente `--no-headless` para validar consent.
- 429/503: o Yahoo rate-limitou; aguarde alguns segundos e tente de novo.
- CSV com poucos itens: confirme `source=screener_api` no log e a regiao suportada.

## Como validar se os dados estao corretos
1) Rode o crawler:
   - `yahoo-crawler --region Argentina --log-level INFO --output output.csv`
2) Verifique o formato do CSV:
   - `head -n 2 output.csv`
   - Deve aparecer exatamente:
     - `"symbol","name","price"`
3) Verifique se veio tudo:
   - `wc -l output.csv`
   - O total deve ser maior que o subset do HTML (>= 1000 para Argentina no momento).
4) Verifique se o log mostra fonte correta:
   - Procure por `source=screener_api` e `Screener pagination done`.
5) (Opcional) Compare com a pagina web:
   - Abra o screener com `?region=AR` e valide alguns tickers do CSV.
