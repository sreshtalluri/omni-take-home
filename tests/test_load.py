import duckdb
import pytest
from etl.load import load_release, LoadError

def _slices(tmp_path):
    e = tmp_path / "edges.tsv";   e.write_text("7\tomni.co\n8\thex.tech\n")
    s = tmp_path / "sources.tsv"; s.write_text("7\tdev.friendly\n8\tnet.one-link\n")
    r = tmp_path / "ranks.tsv";   r.write_text("dev.friendly\t100\t200\n")
    return {"edges": e, "sources": s, "ranks": r}

def test_load_and_idempotent_rerun(tmp_path):
    db = tmp_path / "t.duckdb"
    counts = load_release(db, "2026-05", _slices(tmp_path), nodes_total=1000)
    counts2 = load_release(db, "2026-05", _slices(tmp_path), nodes_total=1000)  # rerun
    assert counts == counts2
    con = duckdb.connect(str(db))
    assert con.sql("select count(*) from raw_backlink_edges").fetchone()[0] == 2
    row = con.sql("""select source_rev_domain, target_domain from raw_backlink_edges
                     where source_id = 7""").fetchone()
    assert row == ("dev.friendly", "omni.co")
    assert con.sql("select nodes_total from raw_graph_stats").fetchone()[0] == 1000

def test_load_rolls_back_on_failure(tmp_path):
    db = tmp_path / "t.duckdb"
    good_slices = _slices(tmp_path)
    load_release(db, "2026-05", good_slices, nodes_total=1000)

    # Same release, but the ranks slice path doesn't exist -- the ranks
    # insert should blow up mid-transaction, after the delete-then-insert
    # loop has already deleted this release's rows from all three tables.
    bad_slices = dict(good_slices, ranks=tmp_path / "missing-ranks.tsv")
    with pytest.raises(Exception):
        load_release(db, "2026-05", bad_slices, nodes_total=9999)

    con = duckdb.connect(str(db))
    assert con.sql(
        "select count(*) from raw_backlink_edges where release = '2026-05'"
    ).fetchone()[0] == 2
    assert con.sql(
        "select count(*) from raw_domain_ranks where release = '2026-05'"
    ).fetchone()[0] == 1
    # nodes_total is still the original value: the failed rerun's delete
    # and its would-be 9999 never survived the rollback.
    assert con.sql(
        "select nodes_total from raw_graph_stats where release = '2026-05'"
    ).fetchone()[0] == 1000

def test_load_empty_slices(tmp_path):
    db = tmp_path / "t.duckdb"
    e = tmp_path / "edges.tsv";   e.write_text("")
    s = tmp_path / "sources.tsv"; s.write_text("")
    r = tmp_path / "ranks.tsv";   r.write_text("")
    slices = {"edges": e, "sources": s, "ranks": r}
    assert e.stat().st_size == 0
    assert s.stat().st_size == 0
    assert r.stat().st_size == 0

    counts = load_release(db, "2026-07", slices, nodes_total=0)
    assert counts == {
        "raw_backlink_edges": 0,
        "raw_domain_ranks": 0,
        "raw_graph_stats": 1,
    }

    # rerun stays idempotent: same 0-byte slices, same counts, no duplicate
    # stats row.
    counts2 = load_release(db, "2026-07", slices, nodes_total=0)
    assert counts2 == counts

    con = duckdb.connect(str(db))
    assert con.sql(
        "select count(*) from raw_graph_stats where release = '2026-07'"
    ).fetchone()[0] == 1

def test_load_fails_on_unresolved_source_id(tmp_path):
    db = tmp_path / "t.duckdb"
    e = tmp_path / "edges.tsv"
    e.write_text("7\tomni.co\n8\thex.tech\n9\tacme.io\n")
    s = tmp_path / "sources.tsv"
    s.write_text("7\tdev.friendly\n8\tnet.one-link\n")  # source_id 9 missing
    r = tmp_path / "ranks.tsv"
    r.write_text("dev.friendly\t100\t200\n")
    slices = {"edges": e, "sources": s, "ranks": r}

    with pytest.raises(LoadError):
        load_release(db, "2026-06", slices, nodes_total=500)

    con = duckdb.connect(str(db))
    for t in ("raw_backlink_edges", "raw_domain_ranks", "raw_graph_stats"):
        assert con.sql(
            f"select count(*) from {t} where release = '2026-06'"
        ).fetchone()[0] == 0
