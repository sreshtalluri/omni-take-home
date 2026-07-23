import duckdb
from etl.load import load_release

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
