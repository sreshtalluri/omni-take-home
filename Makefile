.PHONY: etl load-slices dbt report test all
etl:
	uv run python -m etl.run --all
load-slices:
	uv run python scripts/load_from_slices.py
dbt:
	cd dbt && uv run dbt build --profiles-dir .
report:
	uv run python scripts/generate_report.py
test:
	uv run pytest -v
all: etl dbt report
