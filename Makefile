.PHONY: test lint format check run sync

test:
	uv run pytest tests

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

check: lint test

run:
	uv run uvicorn veltrix.api.main:app --host 0.0.0.0 --port 8000

ui:
	uv run streamlit run src/veltrix/ui/app.py --server.port 8501

sync:
	uv sync
