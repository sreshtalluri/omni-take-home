# Omni Backlink Opportunity Pipeline

Take-home for Omni's Growth Engineering role: an ETL + dbt + semantic-layer pipeline over Common Crawl's public web graph, answering:

> Which high-value backlink opportunities should Omni investigate based on competitor backlink patterns?

Output is at most 25 referring domains, grouped by outreach category, that link to at least two of Omni's tracked competitors (Sigma, Hex, Mode, Lightdash) but not to Omni itself -- built to be useful to a Growth Marketing team, not a raw ranking by link count.

## Architecture

```
Common Crawl web graph releases (data.commoncrawl.org, HTTPS)
  cc-main-2026-mar-apr-may  -> release label "2026-05"
  cc-main-2026-apr-may-jun  -> release label "2026-06"
        |
        v  etl/run.py --release <id>  (download -> extract -> load, checkpointed per step)
  data/slices/<release>/*.tsv + graph.stats  (committed, ~500KB)
        |                                         ^
        |                                         | scripts/load_from_slices.py
        v  etl.load.load_release                  | (skips download+extract, same load call)
  DuckDB raw tables (data/backlinks.duckdb) <-----+
    raw_backlink_edges, raw_domain_ranks, raw_graph_stats
        |
        v  dbt build
  staging -> intermediate -> mart (mart_backlink_opportunities)
        |
        +--> report/top_25_opportunities.md  (scripts/generate_report.py,
        |      reads dbt/seeds/category_overrides.csv + report/actions.csv too)
        +--> omni/*.view + *.topic.yaml       (semantic model over the mart)
```

## Reproduction

Run in order.

### Prerequisites
- [uv](https://docs.astral.sh/uv/). Dependencies are pinned in `pyproject.toml`/`uv.lock` (Python 3.12, see `.python-version`); `uv run <cmd>` resolves the environment on first use, no separate install step.
- macOS or Linux -- `etl/extract.py` shells out to `bash -c "gzip -dc ... | awk ..."`.
- ~40GB free disk for a full two-release `make etl` run. `make test` needs none.

### 1. `make test`
No external network. Runs the pytest suite (23 tests) against committed fixtures in `tests/fixtures/` -- including a full download-skipped/extract/load pipeline run and a checkpoint-resume case. This is the reproducibility proof for the ETL layer without touching Common Crawl or `data/`.

### 2. Get data into DuckDB -- quick or full

**Quick, no download (recommended for review):**
```
make load-slices && make dbt && make report
```
`make load-slices` (`scripts/load_from_slices.py`) loads the already-filtered slices committed under `data/slices/<release>/` (edges/sources/ranks TSVs + `graph.stats`, ~500KB total for both releases) straight into `data/backlinks.duckdb`, via the exact same `etl.load.load_release` call -- same idempotent delete+insert, same all-or-nothing failure semantics -- that `make etl` uses at the end of its download+extract run. Release ids and labels are read from `etl/config.yaml`, the same config `make etl` reads, so the two paths can't silently diverge on which releases "count". This reproduces `dbt build` and the report without a multi-GB download.

**Full, from raw Common Crawl:**
```
make etl
```
Runs `uv run python -m etl.run --all` -- downloads and processes **both** configured releases from scratch.

**Warning: ~35GB total download** (vertices ~850MB + edges ~14-16GB + ranks ~2.2GB per release), 30-60+ minutes depending on bandwidth. Each release is checkpointed independently at `data/checkpoints/<release-id>.json`; a killed run resumes from the last completed step (download / extract / load) instead of restarting from scratch.

Single-release alternative (~18GB, bypasses the Makefile's `--all`):
```
uv run python -m etl.run --release cc-main-2026-apr-may-jun
```
`cc-main-2026-apr-may-jun` alone already contains both crawls the assignment requires (see "Collections mapping" below). Running it alone drops the `present_in_both` persistence signal, which needs two releases -- `weight_persistence` would need to be zeroed and the remaining weights renormalized in `dbt/dbt_project.yml`. See `SPEC.md`.

### 3. `make dbt`
`cd dbt && uv run dbt build --profiles-dir .` -- builds staging -> intermediate -> mart and runs schema + singular tests against whatever step 2 loaded.

### 4. `make report`
`uv run python scripts/generate_report.py` -- renders `report/top_25_opportunities.md` from `mart_backlink_opportunities`, plus two small curated CSVs (`dbt/seeds/category_overrides.csv`, `report/actions.csv`) for the human-verified category and suggested action on each of the top 25. Every count, score, and percentile in the report comes from DuckDB; the script formats and joins, computing nothing of its own except re-scoring merged same-company duplicate rows with the weights read from `dbt/dbt_project.yml` (see the script docstring).

## Deliverables map

| Assignment deliverable | Location |
|---|---|
| 1. ETL framework + code | `etl/` (`config.yaml`, `config.py`, `domains.py`, `download.py`, `extract.py`, `load.py`, `run.py`), tested by `tests/` |
| 2. dbt project | `dbt/` (`dbt_project.yml`, `profiles.yml`, `models/staging`, `models/intermediate`, `models/marts`, `seeds/category_overrides.csv` -- 25 site-verified category overrides) |
| 3. Omni semantic model | `omni/backlink_opportunities.view`, `omni/backlink_opportunities.topic.yaml` |
| 4. Top-25 recommended domains report | `report/top_25_opportunities.md`, produced by `make report` (step 4 above) from the mart plus `report/actions.csv` (per-domain suggested actions) |
| 5. Tech spec | `SPEC.md` |
| 6. Git repo | this repository |

## What was implemented

- ETL framework: config-driven targets/releases/retry params, resumable HTTP Range downloads with bounded exponential-backoff+jitter retries, `awk` stream filtering of the raw web graph (no full decompressed file ever materialized), atomic JSON checkpoint manifests per release, idempotent all-or-nothing DuckDB loads keyed on release.
- dbt project: staging -> intermediate -> mart, schema + singular tests, seed-based category override table.
- Mock Omni semantic model (view + topic) over `mart_backlink_opportunities`, syntax verified against fetched docs.omni.co pages rather than written from memory.
- Both required Common Crawl collections -- May 2026 (`CC-MAIN-2026-21`) and June 2026 (`CC-MAIN-2026-25`) -- covered via the two web graph releases in `etl/config.yaml`.
- All 25 domains in the final report were manually re-categorized against their actual homepage (fetched, not assumed) and given a per-domain suggested action -- not the raw keyword-heuristic category or a generic per-category action.
- `scripts/load_from_slices.py` (`make load-slices`) loads the committed `data/slices/` straight into DuckDB via the same `etl.load.load_release` the full pipeline uses, so `dbt build` and the report are reproducible without the ~35GB download.

## Out of scope

- Full WARC parsing / HTML fetch at scale
- Anchor-text extraction
- JS-rendered link discovery
- Paid SEO API enrichment (Ahrefs/Moz Domain Authority)
- Link velocity trends beyond the two tracked releases

See `SPEC.md`, "What I'd do with a week", for what closes these gaps.

## Collections mapping

The assignment names the "May 2026" and "June 2026" Common Crawl collections, which per `index.commoncrawl.org/collinfo.json` are `CC-MAIN-2026-21` and `CC-MAIN-2026-25`. Common Crawl's domain-level web graph isn't published per monthly crawl, though -- each release merges three consecutive monthly crawls. We use `cc-main-2026-mar-apr-may` (label `2026-05`; latest input crawl is `CC-MAIN-2026-21`) and `cc-main-2026-apr-may-jun` (label `2026-06`; inputs are `CC-MAIN-2026-17`/`-21`/`-25`, so this release alone already contains both required crawls). The two releases share two of their three input crawls, so a domain flagged `present_in_both` is a soft persistence signal across overlapping windows, not confirmation from two independent months -- a tradeoff documented here and in `SPEC.md`, not hidden.
