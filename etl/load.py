import duckdb
from pathlib import Path

DDL = """
create table if not exists raw_backlink_edges (
  release varchar not null, source_id bigint not null,
  source_rev_domain varchar not null, target_domain varchar not null);
create table if not exists raw_domain_ranks (
  release varchar not null, source_rev_domain varchar not null,
  hc_pos bigint, pr_pos bigint);
create table if not exists raw_graph_stats (
  release varchar not null, nodes_total bigint not null);
"""

def load_release(db_path, release_label, slices, nodes_total) -> dict:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(DDL)
    con.execute("begin")
    try:
        # delete-then-insert keyed on release: reruns never double-count
        for t in ("raw_backlink_edges", "raw_domain_ranks", "raw_graph_stats"):
            con.execute(f"delete from {t} where release = ?", [release_label])
        con.execute("""
            insert into raw_backlink_edges
            select ?, e.column0, s.column1, e.column1
            from read_csv(?, delim='\t', header=false,
                          columns={'column0':'bigint','column1':'varchar'}) e
            join read_csv(?, delim='\t', header=false,
                          columns={'column0':'bigint','column1':'varchar'}) s
              using (column0)""", [release_label, str(slices["edges"]), str(slices["sources"])])
        con.execute("""
            insert into raw_domain_ranks
            select ?, column0, column1, column2
            from read_csv(?, delim='\t', header=false,
                columns={'column0':'varchar','column1':'bigint','column2':'bigint'})""",
            [release_label, str(slices["ranks"])])
        con.execute("insert into raw_graph_stats values (?, ?)",
                    [release_label, nodes_total])
        con.execute("commit")
    except Exception:
        con.execute("rollback")
        raise
    counts = {t: con.sql(f"select count(*) from {t} where release = '{release_label}'").fetchone()[0]
              for t in ("raw_backlink_edges", "raw_domain_ranks", "raw_graph_stats")}
    con.close()
    return counts
