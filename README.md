# Yahoo Equity Crawler

[![CI](https://github.com/phelukas/yahoo-equity-crawler/actions/workflows/ci.yml/badge.svg)](https://github.com/phelukas/yahoo-equity-crawler/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Crawler em Python que coleta ativos do Yahoo Finance Equity Screener e exporta
os resultados para CSV. O projeto combina navegação com Selenium, descoberta do
endpoint usado pelo screener, paginação via HTTP e fallback para parsing do HTML.

O foco técnico está em resiliência a falhas externas, separação entre domínio e
infraestrutura, execução reproduzível e testes determinísticos com fixtures.

## Principais capacidades

- coleta por região com paginação e deduplicação por símbolo;
- CSV mínimo (`symbol`, `name`, `price`) ou enriquecido;
- fallback para HTML quando o endpoint do screener não pode ser utilizado;
- retries e logs estruturados para diagnóstico;
- artefatos locais para investigar respostas inesperadas;
- execução local, via Docker ou Docker Compose;
- testes unitários e smoke test E2E separado.

## Arquitetura

```text
CLI
 └── serviço de coleta
      ├── navegador Selenium ──> descoberta do estado do screener
      ├── cliente do screener ─> paginação e dados principais
      ├── cliente de cotações ─> enriquecimento opcional
      └── exportador CSV ──────> arquivo de saída
```

O código segue uma estrutura `src/`:

- `domain`: modelos e erros do domínio;
- `service`: orquestração do caso de uso;
- `infrastructure/browser`: configuração e sincronização do Selenium;
- `infrastructure/yahoo`: navegação, clientes HTTP e parsing;
- `infrastructure/export`: serialização para CSV.

O fluxo detalhado e as decisões de fallback estão em
[`docs/FLUXO_TECNICO.md`](docs/FLUXO_TECNICO.md).

## Requisitos

- Python 3.10 ou superior;
- Google Chrome para execução local com Selenium;
- Docker, opcionalmente, para usar Chromium dentro do container.

## Instalação local

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

No Windows, ative o ambiente com `.venv\Scripts\activate`.

## Uso

CSV mínimo:

```bash
yahoo-crawler --region Argentina --output output.csv
```

CSV enriquecido:

```bash
yahoo-crawler --region Brazil --full --output output_full.csv
```

Diagnóstico visual:

```bash
yahoo-crawler --region Mexico --no-headless --log-level DEBUG
```

Regiões suportadas: `United States`, `Argentina`, `Brazil`, `Chile` e `Mexico`.
Use `yahoo-crawler --help` para consultar todas as opções.

## Docker

```bash
docker build -t yahoo-crawler .
docker run --rm -v "$PWD:/app" yahoo-crawler \
  --region Argentina --output /app/output.csv
```

Com Compose:

```bash
docker compose run --rm crawler \
  --region Argentina --output /app/output.csv
```

## Qualidade e testes

A pipeline executa lint, testes unitários com relatório de cobertura e análise
estática em Python 3.10 e 3.12.

```bash
make check
```

Comandos equivalentes:

```bash
ruff check .
pytest -m "not e2e" --cov=yahoo_crawler --cov-report=term-missing
mypy src
```

O teste marcado como `e2e` acessa um serviço externo e fica fora da validação
determinística da CI. Para executá-lo conscientemente:

```bash
pytest -m e2e
```

## Resiliência e limitações

- O Yahoo Finance é um serviço externo sem contrato estável com este projeto.
- Cookies, tokens e estrutura do screener podem mudar sem aviso.
- Respostas `429` e `503` indicam limitação ou indisponibilidade temporária.
- Alguns ativos não possuem `marketCap`; nesses casos o campo permanece vazio.
- O preço usa `regularMarketPrice.raw` e recorre ao fechamento anterior quando
  o valor intraday não está disponível.

Falhas de parsing ou HTTP podem gerar evidências em `artifacts/`, como HTML,
estado JSON e trechos de resposta. Esses arquivos não devem ser versionados.

## Validação dos dados

Depois da execução:

```bash
head -n 2 output.csv
wc -l output.csv
```

Confira também nos logs a fonte usada (`screener_api` ou fallback) e compare uma
amostra de símbolos com a interface do Yahoo. A quantidade total é variável e
não deve ser tratada como uma constante de negócio.

## Licença

Distribuído sob a [licença MIT](LICENSE).

