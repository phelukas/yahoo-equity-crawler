# Documentação técnica do Yahoo Equity Crawler

Este documento explica o fluxo técnico, componentes e pontos de debug do crawler.
Use como referência rápida quando tiver dúvidas.

## Objetivo
- Abrir o Yahoo Finance Equity Screener filtrado por região.
- Extrair todos os ativos (equities) disponíveis para a região.
- Gerar um CSV minimal (padrão) ou completo.
- Opcionalmente enriquecer dados com a API de quotes.

## Componentes principais
- `src/yahoo_crawler/service/run_crawl.py`: orquestração do fluxo.
- `src/yahoo_crawler/infrastructure/yahoo/navigator.py`: Selenium e navegação.
- `src/yahoo_crawler/infrastructure/yahoo/parser.py`: parsing do HTML/estado JSON.
- `src/yahoo_crawler/infrastructure/yahoo/screener_client.py`: API do screener (paginação).
- `src/yahoo_crawler/infrastructure/yahoo/quote_client.py`: API de quotes (enriquecimento).
- `src/yahoo_crawler/utils/money.py`: parsing de preço.
- `scripts/debug_state_path.py`: utilitário de debug do estado.

## Diagrama simples do fluxo
```
[CLI yahoo-crawler]
        |
        v
[run_crawl.py]
        |
        v
[Selenium abre screener por região]
        |
        v
[Extrai seed (SvelteKit)]
   |            |
   |            v
   |      [Falha?] ----> [Fallback HTML]
   |                       |
   |                       v
   |                [Extrai estado JSON]
   |                       |
   |                       v
   |                [Encontra quotes]
   v
[API Screener (paginação)]
        |
        v
[Normaliza rows]
        |
        v
[Enriquecimento (API quotes)]
        |
        v
[Escreve CSV]
```

## Fluxo técnico detalhado
1) Selenium abre a página do screener com `?region=XX`.
2) O crawler tenta detectar um `script` com `data-sveltekit-fetched`.
3) Se encontrar, extrai a URL e o `rawCriteria` (seed do screener).
4) Com a seed, chama a API do screener, paginando (`start/count` ou `offset/size`).
5) Deduplica resultados por `symbol`.
6) Se a API falhar (ex.: 429), cai para parsing do HTML:
   - Extrai um estado JSON embutido (ex.: `__NEXT_DATA__`, `__PRELOADED_STATE__`,
     `root.App.main`, `YAHOO.context`).
   - Busca a lista de `quotes` dentro desse estado.
7) Normaliza os dados para o formato de linhas (rows).
8) (Opcional) Enriquecimento via API de quotes para `currency` e `market_cap`.
9) Escreve o CSV final.

## Saída do CSV
### Minimal (padrão)
- `symbol`, `name`, `price`

### Completo (`--full`)
- `symbol`, `name`, `exchange`, `market_cap`, `price`, `currency`, `region`

## Diferenças por região
- O conjunto de ativos muda conforme a região do Yahoo.
- A quantidade total de linhas varia bastante por país.
- Moeda e bolsa (exchange) mudam com a região.
- Alguns ativos não têm `market_cap` no Yahoo e o campo fica vazio.

## Logs importantes (o que observar)
- `fonte=screener_api` indica uso da API do screener (melhor caminho).
- `Paginação do screener concluída` mostra páginas e total.
- `fallback para HTML` indica falha no screener e queda para parsing do HTML.
- `Falha ao interpretar cotações` indica que o estado não trouxe `quotes`.

## Artefatos e debug
Quando há falhas, arquivos são salvos em `artifacts/`:
- `last_page_<ts>.html`: HTML da página aberta.
- `parse_fail_state_<ts>.json`: resumo do estado que falhou no parser.
- `screener_http_*` e `quote_http_*`: detalhes das chamadas HTTP.

## Como validar se está tudo certo
- `head -n 2 output.csv` confirma cabeçalho correto.
- `wc -l output.csv` confirma quantidade razoável de linhas.
- Procure logs com `fonte=screener_api` e `Paginação do screener concluída`.

## Troubleshooting rápido
- 429/503: rate limit do Yahoo. Aguarde alguns minutos e tente novamente.
- Seed ausente: tente novamente ou rode com `--no-headless` e aceite consentimento.
- Fallback HTML falhou: abra `artifacts/last_page_*.html` e verifique bloqueio/consent.

## Debug do estado (quando quotes não aparecem)
- Use `scripts/debug_state_path.py` para inspecionar caminhos candidatos.
- O objetivo é identificar onde está a lista de `quotes` no estado.

## Testes
- `pytest -q` roda toda a suíte.
- `pytest -q -m "not e2e"` roda sem Selenium.
