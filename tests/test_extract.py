import tempfile
from pathlib import Path
from etl.config import load_config
from etl.domains import reverse_domain
from etl.extract import (find_target_ids, filter_edges, resolve_source_domains,
                         filter_ranks, read_stats, ExtractError)
import pytest

FIX = Path("tests/fixtures")
CFG = load_config()
TARGETS_REV = {reverse_domain(v): v for v in CFG.targets.values()}

def test_find_target_ids():
    ids = find_target_ids(FIX / "vertices.txt.gz", TARGETS_REV, CFG.columns)
    assert set(ids.values()) == set(CFG.targets.values())
    assert len(ids) == 5

def test_find_target_ids_missing_target_raises():
    with pytest.raises(ExtractError):
        find_target_ids(FIX / "vertices.txt.gz", {"zz.nope": "nope.zz"}, CFG.columns)

def test_filter_edges_and_resolve(tmp_path):
    ids = find_target_ids(FIX / "vertices.txt.gz", TARGETS_REV, CFG.columns)
    out = tmp_path / "edges.tsv"
    n = filter_edges(FIX / "edges.txt.gz", ids, out, CFG.columns)
    rows = [l.split("\t") for l in out.read_text().splitlines()]
    assert n == len(rows) == 8            # unrelated.org edge excluded
    src_ids = {int(r[0]) for r in rows}
    out2 = tmp_path / "sources.tsv"
    resolve_source_domains(FIX / "vertices.txt.gz", src_ids, out2, CFG.columns)
    assert "com.bi-tools-blog" in out2.read_text()

def test_filter_ranks_and_stats(tmp_path):
    out = tmp_path / "ranks.tsv"
    n = filter_ranks(FIX / "ranks.txt.gz", {"com.bi-tools-blog"}, out, CFG.columns)
    assert n == 1
    assert read_stats(FIX / "graph.stats")["nodes"] == 10

def test_awk_filter_cleans_up_keyfile(tmp_path):
    # Each extractor call shells out to `gzip -dc | awk` with a lookup table
    # written to a NamedTemporaryFile(delete=False) so awk can open it by
    # path; that file must not survive the call, or a long-running pipeline
    # (or a test suite run repeatedly) accumulates cruft in the system temp
    # dir forever. Snapshot-diff isolates leaks from this call specifically,
    # so ambient *.keys files from elsewhere don't make this flaky.
    tmpdir = Path(tempfile.gettempdir())
    before = set(tmpdir.glob("*.keys"))
    filter_ranks(FIX / "ranks.txt.gz", {"com.bi-tools-blog"}, tmp_path / "r.tsv", CFG.columns)
    after = set(tmpdir.glob("*.keys"))
    assert after - before == set()
