"""Checkpointed orchestrator: download -> extract -> load, one release at a
time. Downloads and extracts are gated by a per-release Manifest at
data/checkpoints/<release>.json, so a crashed/interrupted run resumes at the
first incomplete step on rerun instead of redoing multi-GB downloads or
scans. The load step is not manifest-gated -- it always runs, including on
resume -- but it is safe to repeat: load_release's delete+insert transaction
is idempotent, keyed on release label, so a rerun leaves row counts
unchanged. There is no partial-publish path: any unhandled exception
propagates out of run_release (and out of main's per-release loop), so a
failed release exits the process non-zero, and load_release's delete+insert
transaction -- the only step that writes to the published DuckDB tables --
either never runs or commits atomically. Either way there is nothing
partial to clean up.
"""
import argparse
import shutil
import sys
from pathlib import Path

from etl.config import load_config
from etl.domains import reverse_domain
from etl.download import download
from etl.extract import (
    filter_edges,
    filter_ranks,
    find_target_ids,
    read_stats,
    resolve_source_domains,
)
from etl.load import load_release
from etl.manifest import Manifest

FILES = {"vertices": "domain-vertices.txt.gz", "edges": "domain-edges.txt.gz",
         "ranks": "domain-ranks.txt.gz", "stats": "domain.stats"}

def run_release(cfg, release, files_override=None, workdir=None, db_path=None):
    work = Path(workdir or cfg.data_dir)
    raw, slices_dir = work / "raw" / release.id, work / "slices" / release.id
    slices_dir.mkdir(parents=True, exist_ok=True)
    mf = Manifest(work / "checkpoints" / f"{release.id}.json")

    local = {}
    for key, fname in FILES.items():
        if files_override:
            local[key] = Path(files_override[key])
            continue
        dest = raw / f"{release.id}-{fname}"
        if not mf.is_done(f"download:{key}"):
            url = f"{cfg.base_url}/{release.id}/domain/{release.id}-{fname}"
            download(url, dest, cfg.http)
            mf.mark_done(f"download:{key}", size=dest.stat().st_size)
        local[key] = dest

    # Cheap single pass over the (small) vertices file relative to the
    # multi-GB edges/ranks scans below -- not checkpointed, just re-run on
    # every invocation whether this is a fresh run or a resume.
    targets_rev = {reverse_domain(v): v for v in cfg.targets.values()}
    target_ids = find_target_ids(local["vertices"], targets_rev, cfg.columns)

    edges_tsv, sources_tsv, ranks_tsv = (slices_dir / n for n in
                                         ("edges.tsv", "sources.tsv", "ranks.tsv"))
    if not mf.is_done("extract:edges"):
        n = filter_edges(local["edges"], target_ids, edges_tsv, cfg.columns)
        mf.mark_done("extract:edges", rows=n)
    # A resumed run reads back whatever an earlier extract:edges wrote,
    # without re-touching local["edges"]. splitlines() already turns a
    # zero-match (empty) file into [], but filter out blank lines anyway so
    # a stray trailing newline can never blow up int()/split() here.
    src_ids = {int(l.split("\t")[0]) for l in edges_tsv.read_text().splitlines() if l.strip()}
    if not mf.is_done("extract:sources"):
        mf.mark_done("extract:sources",
                     rows=resolve_source_domains(local["vertices"], src_ids,
                                                 sources_tsv, cfg.columns))
    src_revs = {l.split("\t")[1] for l in sources_tsv.read_text().splitlines() if l.strip()}
    if not mf.is_done("extract:ranks"):
        mf.mark_done("extract:ranks",
                     rows=filter_ranks(local["ranks"], src_revs, ranks_tsv, cfg.columns))

    nodes = read_stats(local["stats"])["nodes"]

    # Mirror the release's stats file into the slices dir as graph.stats,
    # alongside the edges/sources/ranks TSVs above, so a later `make
    # load-slices` (scripts/load_from_slices.py) has what it needs without
    # re-downloading. Skipped when files_override already points the stats
    # source at this exact destination (nothing to copy onto itself).
    stats_dest = slices_dir / "graph.stats"
    if Path(local["stats"]).resolve() != stats_dest.resolve():
        shutil.copy2(local["stats"], stats_dest)

    counts = load_release(db_path or cfg.duckdb_path, release.label,
                          {"edges": edges_tsv, "sources": sources_tsv,
                           "ranks": ranks_tsv}, nodes)
    mf.mark_done("load", **counts)
    print(f"{release.id} ({release.label}): {counts}")
    return counts

def main():
    p = argparse.ArgumentParser(description="CC web graph backlink ETL")
    p.add_argument("--release", help="release id from config")
    p.add_argument("--all", action="store_true", help="run every release in config")
    p.add_argument("--config", default="etl/config.yaml")
    a = p.parse_args()
    if not a.all and not a.release:
        p.error("either --release <id> or --all is required")

    cfg = load_config(a.config)
    todo = cfg.releases if a.all else [r for r in cfg.releases if r.id == a.release]
    if not todo:
        sys.exit(f"unknown release {a.release!r}; known: {[r.id for r in cfg.releases]}")
    for rel in todo:
        run_release(cfg, rel)  # any unhandled error exits non-zero: nothing published

if __name__ == "__main__":
    main()
