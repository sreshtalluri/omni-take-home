"""Load the already-committed data/slices/<release>/*.tsv + graph.stats
straight into DuckDB, skipping the ~35GB Common Crawl download and the awk
extraction pass over it. Both releases' filtered slices are committed to
the repo (~500KB total), so a reviewer can reproduce dbt + the report
without touching data.commoncrawl.org at all.

Reuses etl.load.load_release exactly as etl/run.py does -- same idempotent
delete+insert per release, same all-or-nothing failure on an unresolved
edge -- so this produces byte-identical raw tables to a full `make etl`
run for the two releases already sliced under data/slices/. Release ids
and labels are read from etl/config.yaml, the same config the full ETL
uses, so the two paths can never drift apart on which releases "count".

Run: uv run python scripts/load_from_slices.py  (equivalently
`make load-slices`), then `make dbt && make report` as usual.
"""
import sys
from pathlib import Path

from etl.config import load_config
from etl.extract import read_stats
from etl.load import LoadError, load_release


def main():
    cfg = load_config("etl/config.yaml")
    data_dir = cfg.data_dir

    for release in cfg.releases:
        slice_dir = f"{data_dir}/slices/{release.id}"
        slices = {name: f"{slice_dir}/{name}.tsv"
                  for name in ("edges", "sources", "ranks")}
        stats_path = f"{slice_dir}/graph.stats"

        missing = [p for p in (*slices.values(), stats_path)
                   if not Path(p).exists()]
        if missing:
            sys.exit(f"missing committed slice file(s) for {release.id}: "
                      f"{', '.join(missing)} -- these ship in the repo "
                      "under data/slices/; if they're absent, use `make "
                      "etl` instead")

        nodes = read_stats(stats_path)["nodes"]
        try:
            counts = load_release(cfg.duckdb_path, release.label, slices,
                                  nodes)
        except LoadError as e:
            sys.exit(f"load failed for {release.id} ({release.label}): {e}")
        print(f"{release.id} ({release.label}): {counts}")


if __name__ == "__main__":
    main()
