.PHONY: etl dbt report test all
etl:
	uv run python -m etl.run --all
dbt:
	cd dbt && uv run dbt build --profiles-dir .
report:
	uv run python scripts/generate_report.py
test:
	uv run pytest -v
all: etl dbt report
