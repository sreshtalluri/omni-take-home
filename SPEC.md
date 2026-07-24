# Tech Spec

See `README.md` for reproduction steps and the deliverables map.

## Problem framing

The assignment, the constraints it imposes, and the source data the pipeline runs against:

- Assignment question: which high-value backlink opportunities should Omni pursue, based on competitor backlink patterns
- Hard constraints: <=25 referring domains; actionable for Growth Marketing, not a raw link-count ranking; recurring scheduled pipeline; retry/recovery semantics; few-hours timebox, MVP
- Competitor set: omni.co, sigmacomputing.com, hex.tech, mode.com, lightdash.com
- Required source data: Common Crawl May 2026 + June 2026 collections (`CC-MAIN-2026-21`, `CC-MAIN-2026-25`)

## Explicit contracts

The schema and guarantees each layer of the pipeline exposes to the next, from raw ingestion through to the report:

### Raw (`etl/load.py` DDL, DuckDB)
- `raw_backlink_edges(release, source_id, source_rev_domain, target_domain)`
- `raw_domain_ranks(release, source_rev_domain, hc_pos, pr_pos)`
- `raw_graph_stats(release, nodes_total)`

### Staging (`dbt/models/staging`)
- `stg_backlink_edges(release, source_domain, target_domain)` -- deduped, un-reversed + lowercased, self-links dropped
- `stg_domain_ranks(release, source_domain, hc_pos, nodes_total, authority_percentile)`

### Intermediate (`dbt/models/intermediate`)
- `int_competitor_coverage(source_domain, links_omni, links_sigma, links_hex, links_mode, links_lightdash, releases_seen, present_in_both)`
- `int_domain_authority(source_domain, authority_percentile)` -- max percentile across releases

### Mart (`dbt/models/marts/mart_backlink_opportunities.sql`)
- Columns: `source_domain, links_sigma, links_hex, links_mode, links_lightdash, links_omni, competitor_count, present_in_both, releases_seen, authority_percentile, opportunity_score, category`
- Filter: `links_omni = 0 AND competitor_count >= min_competitor_count` (2)
- Tests: `source_domain` not_null + unique; `links_omni` accepted_values `[0]`; `opportunity_score` not_null; `competitor_count` in `[2,4]` (singular test, `assert_competitor_count_in_range.sql`)

### Score formula
- `opportunity_score = 0.5*(competitor_count/4) + 0.3*authority_percentile + 0.2*present_in_both`
- Weights live in two places, kept in sync by hand: `etl/config.yaml: score_weights` and `dbt/dbt_project.yml: vars`
- `min_competitor_count = 2`

### Freshness
- One row set per web-graph release, not per calendar month
- Keyed on release label (`2026-05` / `2026-06`); delete+insert per release; rerunning a release is idempotent

### Report contract
- `report/top_25_opportunities.md`, <=25 domains, grouped by category
- Every figure sourced from `mart_backlink_opportunities`; no metric computed in the report script itself

## Implicit contracts & assumptions

Assumptions the pipeline relies on that no schema or test enforces:

- CC web graph file availability and text format assumed stable release-to-release at `data.commoncrawl.org/projects/hyperlinkgraph/<release>/domain/`; not contractually guaranteed by Common Crawl
- Column layouts (`etl/config.yaml: columns`, 1-based indices) pinned from a live peek at the real files, not from documentation -- must be reverified if a future release reorders columns
- Collections -> releases mapping: `cc-main-2026-mar-apr-may` -> `2026-05` (latest input crawl `CC-MAIN-2026-21` = May); `cc-main-2026-apr-may-jun` -> `2026-06` (inputs `CC-MAIN-2026-17`/`-21`/`-25`, latest `CC-MAIN-2026-25` = June; this release alone contains both required crawls)
- Releases overlap on 2 of their 3 input crawls -> `present_in_both` is a soft persistence signal, not two independent time windows
- Domain-level granularity only: registrable domain (reversed-domain un-reversed + lowercased), no subdomain, page, or anchor-text detail anywhere in the graph
- Real graph scale (`cc-main-2026-apr-may-jun` release): 121,091,933 domain nodes, 3,902,808,757 arcs -- `authority_percentile`'s denominator and score magnitudes assume this order of magnitude
- Authority proxy = harmonic-centrality rank position from CC's ranks file -> percentile (`1 - (hc_pos-1)/nodes_total`); explicitly not Moz/Ahrefs Domain Authority
- Domain canonicalization = lowercase + strip trailing dot + strip leading `www.` (`etl/domains.py`); no IDN/punycode handling

## Design decisions & tradeoffs

Key tradeoffs made to fit the scope and timebox, and why:

- Web graph vs WARC parsing: domain-level edge list over full WARC HTML parsing -- turns a petabyte-scale crawl into a filter over an edge list; costs anchor text and page-level detail
- `awk` streaming vs materializing: `gzip -dc | awk` keeps peak memory flat over multi-GB decompressed files instead of loading them whole into Python/DuckDB; awk carries the inner-loop filter, Python only orchestrates
- All-or-nothing per release: any edge whose `source_id` has no matching vertex row aborts the whole release's load rather than publishing a partial edge set that would silently bias gap analysis
- Competitor selection: Mode + Lightdash chosen over Tableau/Power BI -- giant incumbents' backlink profiles would drown the gap analysis, working against the "actionable, not a big-number ranking" requirement
- Categorization: keyword/TLD heuristic + seed-table override (`dbt/seeds/category_overrides.csv`) rather than automated NLP/LLM classification -- target set is small (<=25), and each of the <=25 candidates needs its category checked against its actual site regardless
- Omni semantic model carries `ai_context` + `synonyms` on the topic/dimensions so Omni's AI/NL features route marketer questions through the governed topic (its `default_filters`, `sample_queries`) instead of an ungoverned ad hoc query

## Recovery semantics

How the pipeline retries, resumes, and stays idempotent across partial or repeated runs:

- Retries: HTTP downloads retry up to `http.max_attempts` (5) with exponential backoff (`backoff_base_s * 2^attempt`) + random jitter, bounded per-request timeout (60s)
- Resumable downloads: HTTP Range requests resume a `.part` file from its current byte offset; a HEAD request checks remote size first so a complete-but-unrenamed `.part` is finalized without an extra GET (avoids a 416 loop against a compliant server)
- Checkpoint manifests: one JSON manifest per release (`data/checkpoints/<release-id>.json`), one entry per step (`download:<file>`, `extract:edges`, `extract:sources`, `extract:ranks`, `load`); writes are atomic (temp file + `os.replace`)
- Idempotent load: delete-where-release then insert, in one transaction, keyed on release label; rerunning a completed release leaves row counts unchanged
- All-or-nothing publish: any unresolved `source_id` raises `LoadError` before commit; transaction rolls back; nothing published for that release
- Empty slices are valid: a tracked target with zero backlinks in a release loads as zero rows, distinct from the corrupt/partial data the all-or-nothing policy exists to catch
- Run evidence (2026-07-23 real run): 2026-05 loaded 2,924 edges / 2,413 ranked domains; 2026-06 loaded 3,145 edges / 2,560 ranked domains; rerunning the completed 2026-06 release end-to-end took 66s wall clock (vs ~40min cold) with byte-identical counts -- manifest skipped all downloads and extracts, load re-ran idempotently; `dbt build` on the combined releases: 14/14 PASS; mart produced 277 candidate domains (20 linking to all 4 competitors, 60 to 3, 197 to 2; 227 present in both releases)

## What I'd do with a week

Follow-on work that's out of scope for this timebox but would extend the pipeline further:

- WARC anchor-text extraction for the top candidate domains (byte-range fetch just the linking pages, not full WARC parsing at scale)
- Per-crawl link velocity: track opportunity domains across more than two releases to distinguish growing vs. one-off links
- Moz/Ahrefs enrichment to replace the harmonic-centrality proxy with an actual Domain Authority metric
- LLM-assisted categorization with live site fetches, replacing/augmenting the keyword heuristic + manual override table
- MotherDuck + scheduled deployment (GitHub Actions cron) running `etl/run.py --all` monthly, plus alerting on release failure
- Weight calibration: tune `score_weights` against actual outreach outcomes (response rate, links won) instead of the fixed 0.5/0.3/0.2 starting point
