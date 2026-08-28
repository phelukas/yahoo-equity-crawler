.PHONY: install lint test typecheck check

install:
	python -m pip install -e ".[dev]"

lint:
	ruff check .

test:
	pytest -m "not e2e" --cov=yahoo_crawler --cov-report=term-missing

typecheck:
	mypy src

check: lint test typecheck

