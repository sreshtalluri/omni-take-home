"""Full pipeline over fixture files: extract -> load -> assert mart inputs.
No network. This is the reproducibility proof for the whole ETL layer.

Also covers the orchestrator CLI (etl/run.py main()) directly: an unknown
--release must fail loudly, and --all must iterate every configured release.
Both CLI tests monkeypatch run_release so nothing here ever touches the
network, per this task's "no network" constraint.
"""
import sys

import duckdb
import pytest
from pathlib import Path

import etl.run as run_mod  # module reference: lets the CLI tests monkeypatch
                            # run_release exactly where main() looks it up
from etl.config import load_config, Release
from etl.run import main, run_release

FIX = Path("tests/fixtures").resolve()

def _fixture_files():
    return {"vertices": FIX / "vertices.txt.gz", "edges": FIX / "edges.txt.gz",
            "ranks": FIX / "ranks.txt.gz", "stats": FIX / "graph.stats"}

def test_pipeline_end_to_end(tmp_path):
    cfg = load_config()
    rel = Release(id="fixture-rel", label="2026-05", crawls=[])
    files = _fixture_files()
    db = tmp_path / "test.duckdb"
    counts = run_release(cfg, rel, files_override=files,
                         workdir=tmp_path, db_path=db)
    assert counts["raw_backlink_edges"] == 8
    con = duckdb.connect(str(db))
    # friendly.dev links to omni -> present in raw, later excluded in mart
    assert con.sql("""select count(*) from raw_backlink_edges
                      where target_domain = 'omni.co'""").fetchone()[0] == 1
    # rerun resumes from manifest and stays idempotent
    counts2 = run_release(cfg, rel, files_override=files,
                          workdir=tmp_path, db_path=db)
    assert counts2 == counts

def test_rerun_skips_extract_edges_when_already_checkpointed(tmp_path):
    """A resumed run must not re-touch the raw edges file once extract:edges
    is checkpointed done -- proves the manifest actually gates the step
    instead of merely recording it. If the gate were missing, the second
    call would try to `gzip -dc` a nonexistent file and raise."""
    cfg = load_config()
    rel = Release(id="fixture-rel-resume", label="2026-05", crawls=[])
    db = tmp_path / "test.duckdb"
    good_files = _fixture_files()
    counts = run_release(cfg, rel, files_override=good_files,
                         workdir=tmp_path, db_path=db)

    broken_files = dict(good_files, edges=tmp_path / "does-not-exist.txt.gz")
    counts2 = run_release(cfg, rel, files_override=broken_files,
                          workdir=tmp_path, db_path=db)
    assert counts2 == counts

def test_main_unknown_release_exits_nonzero_with_helpful_message(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["etl.run", "--release", "nonexistent"])
    with pytest.raises(SystemExit) as exc:
        main()
    message = str(exc.value.code)
    assert exc.value.code  # truthy: not a clean/zero exit
    assert "nonexistent" in message
    cfg = load_config()
    for rel in cfg.releases:
        assert rel.id in message  # helpful: lists the known releases

def test_main_requires_release_or_all(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["etl.run"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code not in (0, None)

def test_main_all_iterates_every_configured_release_with_no_network(monkeypatch):
    calls = []
    monkeypatch.setattr(run_mod, "run_release", lambda cfg, rel: calls.append(rel.id))
    monkeypatch.setattr(sys, "argv", ["etl.run", "--all"])
    main()
    cfg = load_config()
    assert calls == [r.id for r in cfg.releases]

def test_main_release_flag_selects_a_single_release_with_no_network(monkeypatch):
    calls = []
    monkeypatch.setattr(run_mod, "run_release", lambda cfg, rel: calls.append(rel.id))
    cfg = load_config()
    one = cfg.releases[0].id
    monkeypatch.setattr(sys, "argv", ["etl.run", "--release", one])
    main()
    assert calls == [one]
