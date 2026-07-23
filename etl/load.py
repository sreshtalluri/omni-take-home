import duckdb
from pathlib import Path

class LoadError(Exception):
    pass

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

# edges.tsv and sources.tsv share this shape (id, text). Reused for both the
# real join-based insert below and the anti-join validation, so the
# validation can never read the sources file differently than the insert
# that follows it.
_ID_DOMAIN_CSV = ("read_csv(?, delim='\t', header=false, "
                   "columns={'column0':'bigint','column1':'varchar'})")

_UNRESOLVED_EDGES_SQL = f"""
    select e.column0
    from {_ID_DOMAIN_CSV} e
    where not exists (
        select 1 from {_ID_DOMAIN_CSV} s where s.column0 = e.column0
    )
"""

def load_release(db_path, release_label, slices, nodes_total) -> dict:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(DDL)
        con.execute("begin")
        try:
            # delete-then-insert keyed on release: reruns never double-count
            for t in ("raw_backlink_edges", "raw_domain_ranks", "raw_graph_stats"):
                con.execute(f"delete from {t} where release = ?", [release_label])

            edges_path = str(slices["edges"])
            sources_path = str(slices["sources"])

            # All-or-nothing policy: an edge whose src_id has no row in
            # sources.tsv must fail the whole load, not silently vanish from
            # the inner join below -- partial data silently biases analysis,
            # which is exactly the failure mode this pipeline exists to
            # prevent.
            unresolved = con.execute(
                f"select count(*) from ({_UNRESOLVED_EDGES_SQL}) t",
                [edges_path, sources_path],
            ).fetchone()[0]
            if unresolved > 0:
                examples = con.execute(
                    f"""select distinct column0 from ({_UNRESOLVED_EDGES_SQL}) t
                        order by column0 limit 5""",
                    [edges_path, sources_path],
                ).fetchall()
                example_ids = ", ".join(str(row[0]) for row in examples)
                raise LoadError(
                    f"{unresolved} edge row(s) in release {release_label!r} "
                    f"reference source_id(s) with no matching row in "
                    f"{sources_path}; refusing partial load. Example "
                    f"unresolved source_id(s): {example_ids}")

            con.execute(f"""
                insert into raw_backlink_edges
                select ?, e.column0, s.column1, e.column1
                from {_ID_DOMAIN_CSV} e
                join {_ID_DOMAIN_CSV} s
                  using (column0)""", [release_label, edges_path, sources_path])
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
        counts = {t: con.execute(
                        f"select count(*) from {t} where release = ?",
                        [release_label]).fetchone()[0]
                  for t in ("raw_backlink_edges", "raw_domain_ranks", "raw_graph_stats")}
        return counts
    finally:
        con.close()
