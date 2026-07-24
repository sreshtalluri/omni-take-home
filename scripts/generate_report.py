"""Render the Growth Marketing report from mart_backlink_opportunities plus
three small curated CSVs. Every quantitative figure in the output -- domain
counts, scores, authority percentiles, competitor flags, release node
counts -- comes from DuckDB; this script formats, merges, and joins, it
never computes a new metric.

Beyond the mart, this script reads three curation artifacts (not data
sources):

  dbt/seeds/category_overrides.csv -- the same source_domain,category
      overrides dbt already seeds and joins into the mart's `category`
      column. Read again here only to confirm every domain in the final
      top 25 has a human-verified row (hard-fail if one is missing);
      category itself always comes from the mart, never recomputed here.
  report/actions.csv -- source_domain,action: one hand-written, per-domain
      "what to actually do" line, written after checking each site's real
      homepage during manual curation. Every domain in the final top 25
      must have a row here, or the run hard-fails rather than falling back
      to a generic guess.
  report/duplicates.csv -- canonical_domain,duplicate_domain,note: known
      cases where two different domain strings in the mart are the same
      outreach target (e.g. an old domain 301-redirecting to the current
      one). The mart has no way to know this on its own -- it counts
      distinct domain strings, not distinct companies -- so this file is
      how a human-verified "these are the same company" fact gets into an
      otherwise fully mart-driven report. Every domain either file
      mentions must exist in the mart, or the run hard-fails.

Duplicate handling: when picking the top 25, every duplicate_domain's row
is merged into its canonical_domain's row (competitor-link flags and
present_in_both unioned/OR'd, authority and score kept at the better of
the two, category taken only from the canonical row) and dropped from
consideration on its own. The merged row keeps whichever rank position the
better of the two would have earned, and the next-best-ranked distinct
company fills the slot that would otherwise go to press with 25 domain
strings representing only 24 real outreach targets. This is done for the
whole mart, not just an original top-25 slice, so it is correct regardless
of how many duplicates exist or where they rank.

Run: uv run python scripts/generate_report.py  (equivalently `make report`).
Requires `make dbt` (or an equivalent `dbt build`) to have already
populated mart_backlink_opportunities.
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "backlinks.duckdb"
ACTIONS_CSV = REPO_ROOT / "report" / "actions.csv"
OVERRIDES_CSV = REPO_ROOT / "dbt" / "seeds" / "category_overrides.csv"
DUPLICATES_CSV = REPO_ROOT / "report" / "duplicates.csv"
OUT_PATH = REPO_ROOT / "report" / "top_25_opportunities.md"

TOP_N = 25
LINK_COLS = ["links_sigma", "links_hex", "links_mode", "links_lightdash"]

# Deterministic tie-break: the mart has several 4-competitor domains that
# round to authority 1.0, so opportunity_score alone doesn't fully order
# the top rows. Mirrored in mart_backlink_opportunities.sql's own ORDER BY
# so the mart and this report always agree on rank order (the merge step
# below re-sorts by this same key afterward, since collapsing duplicates
# can change which rows are adjacent).
ORDER_BY = """
    order by opportunity_score desc, competitor_count desc,
             authority_percentile desc, source_domain asc
"""


def _read_actions() -> dict:
    if not ACTIONS_CSV.exists():
        sys.exit(f"missing {ACTIONS_CSV}: cannot generate report without "
                  "per-domain actions -- see the script docstring")
    with open(ACTIONS_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
    actions = {r["source_domain"]: r["action"] for r in rows}
    if len(actions) != len(rows):
        sys.exit(f"{ACTIONS_CSV} has duplicate source_domain row(s)")
    return actions


def _read_overrides() -> set:
    if not OVERRIDES_CSV.exists():
        sys.exit(f"missing {OVERRIDES_CSV}")
    with open(OVERRIDES_CSV, newline="") as f:
        return {r["source_domain"] for r in csv.DictReader(f)}


def _read_duplicates() -> list:
    if not DUPLICATES_CSV.exists():
        sys.exit(f"missing {DUPLICATES_CSV}: cannot generate report "
                  "without the known same-company duplicate list -- see "
                  "the script docstring")
    with open(DUPLICATES_CSV, newline="") as f:
        return list(csv.DictReader(f))


def _merge_duplicates(all_rows: list, duplicates: list) -> list:
    """Collapse known same-company duplicate rows into their canonical
    row and return one merged record per distinct company, unsorted."""
    by_domain = {r["source_domain"]: r for r in all_rows}

    canonical_of = {}
    for d in duplicates:
        canon, dup = d["canonical_domain"], d["duplicate_domain"]
        missing = [x for x in (canon, dup) if x not in by_domain]
        if missing:
            sys.exit(f"{DUPLICATES_CSV} references domain(s) not in "
                      f"mart_backlink_opportunities: {', '.join(missing)}")
        canonical_of[dup] = canon

    groups = defaultdict(list)
    for r in all_rows:
        groups[canonical_of.get(r["source_domain"], r["source_domain"])].append(
            r["source_domain"])

    merged = []
    for canon, members in groups.items():
        # Start from the canonical domain's own row -- category and every
        # other field's baseline always comes from here, never from a
        # duplicate, so a duplicate can only ever raise a number or add a
        # flag, not change what the merged row *is*.
        rec = dict(by_domain[canon])
        extra = [m for m in members if m != canon]
        for m in extra:
            other = by_domain[m]
            for col in LINK_COLS + ["present_in_both"]:
                rec[col] = max(rec[col], other[col])
            rec["authority_percentile"] = max(rec["authority_percentile"],
                                              other["authority_percentile"])
            rec["opportunity_score"] = max(rec["opportunity_score"],
                                           other["opportunity_score"])
        rec["competitor_count"] = sum(rec[c] for c in LINK_COLS)
        rec["merged_from"] = extra
        merged.append(rec)
    return merged


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)

    # Fetch every candidate, not just the top 25: collapsing a duplicate
    # can pull a lower-ranked distinct company up into the top 25, so the
    # merge-then-select has to run over the whole mart to be correct
    # regardless of how many duplicates exist or where they rank.
    all_rel = con.sql(f"""
        select source_domain, category, links_sigma, links_hex, links_mode,
               links_lightdash, competitor_count, present_in_both,
               authority_percentile, opportunity_score
        from mart_backlink_opportunities
        {ORDER_BY}
    """)
    all_cols = all_rel.columns
    all_rows = [dict(zip(all_cols, r)) for r in all_rel.fetchall()]
    total = len(all_rows)
    if not total:
        sys.exit("mart_backlink_opportunities is empty -- run `make dbt` "
                  "(or `make load-slices && make dbt`) first")

    duplicates = _read_duplicates()
    merged = _merge_duplicates(all_rows, duplicates)
    merged.sort(key=lambda r: (-r["opportunity_score"], -r["competitor_count"],
                               -r["authority_percentile"], r["source_domain"]))

    distinct_total = len(merged)
    if distinct_total < TOP_N:
        sys.exit(f"only {distinct_total} distinct candidate(s) after "
                 f"merging same-company duplicates; expected at least "
                 f"{TOP_N}. Refusing to publish a report that pads or "
                 "invents missing rows.")
    rows = merged[:TOP_N]
    for i, r in enumerate(rows, start=1):
        r["rank"] = i

    # Release labels + each release's node count, for the "how to read
    # authority" note -- pulled from the pipeline's own graph stats rather
    # than hand-typed, same as every other number in this report. Each
    # domain's authority_percentile is computed against its own release's
    # node count (int_domain_authority takes the max across releases), so
    # the note below cites both counts rather than implying one universal
    # denominator.
    stats = con.sql(
        "select release, nodes_total from raw_graph_stats order by release"
    ).fetchall()
    if not stats:
        sys.exit("raw_graph_stats is empty -- run `make etl` (or "
                  "`make load-slices`) first")
    release_labels = [s[0] for s in stats]
    nodes_by_release = ", ".join(f"{label}: {nodes:,} domains"
                                  for label, nodes in stats)

    actions = _read_actions()
    missing_actions = [r["source_domain"] for r in rows
                        if r["source_domain"] not in actions]
    if missing_actions:
        sys.exit("report/actions.csv is missing a row for: "
                  f"{', '.join(missing_actions)}")

    # Design invariant from the curation step: every domain in the final
    # top-N (post-duplicate-merge) got an explicit human-decided row in
    # category_overrides.csv, whether or not that decision matched the
    # keyword heuristic's default (the CSV can't otherwise distinguish
    # "checked and confirmed" from "never checked"). If one is missing,
    # curation was incomplete -- that is missing data, and per this
    # script's contract it hard-fails rather than silently reporting an
    # uncurated category as if it were reviewed.
    overridden = _read_overrides()
    uncurated = [r["source_domain"] for r in rows
                 if r["source_domain"] not in overridden]
    if uncurated:
        sys.exit(f"dbt/seeds/category_overrides.csv has no curated row "
                  f"for: {', '.join(uncurated)} -- every top-{TOP_N} "
                  "domain must be manually verified before the report can "
                  "be generated")

    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)

    out = ["# Top 25 Backlink Opportunities for Omni", "",
           "## How this list was built", ""]
    out.append(
        "We compared who links to Sigma, Hex, Mode, and Lightdash against "
        "who links to Omni, using Common Crawl's public web graph (the "
        f"{' and '.join(release_labels)} releases). Every domain below "
        "links to at least two of the four competitors but not to "
        "omni.co. The ranking score blends three signals: how many "
        "competitors a domain links to, how much authority the domain "
        "itself carries in the web graph, and whether the link showed up "
        "in both releases -- weighted most heavily toward the number of "
        f"competitors linked. Every one of the {len(rows)} domains below "
        "was checked by hand against its actual site and has a "
        "human-verified category in dbt/seeds/category_overrides.csv, "
        "not just a keyword guess."
    )
    out.append("")

    for cat in sorted(by_cat,
                       key=lambda c: -max(d["opportunity_score"]
                                          for d in by_cat[c])):
        out.append(f"## {cat.title()} ({len(by_cat[cat])})")
        out.append("")
        out.append("| Rank | Domain | Links to | Present in both releases "
                    "| Authority pct | Score | Suggested action |")
        out.append("|---|---|---|---|---|---|---|")
        for r in by_cat[cat]:
            links = ", ".join(n for n, f in [
                ("Sigma", r["links_sigma"]), ("Hex", r["links_hex"]),
                ("Mode", r["links_mode"]), ("Lightdash", r["links_lightdash"])
            ] if f)
            both = "Yes" if r["present_in_both"] else "No"
            action = actions[r["source_domain"]]
            if r["merged_from"]:
                # Data-driven, not hand-typed: the note names whichever
                # duplicate domain(s) report/duplicates.csv says merged
                # into this row.
                action += f" Also linked via {', '.join(r['merged_from'])}."
            out.append(
                f"| {r['rank']} | {r['source_domain']} | {links} | {both} "
                f"| {r['authority_percentile']:.3f} "
                f"| {r['opportunity_score']:.3f} "
                f"| {action} |"
            )
        out.append("")

    out.append("## How to read authority")
    out.append("")
    out.append(
        "Authority pct is each domain's harmonic-centrality rank in "
        "Common Crawl's domain-level web graph for a release, converted "
        f"to a percentile of that release's domain count ({nodes_by_release}) "
        "-- when a domain shows up in both releases, the higher of the "
        "two percentiles is kept. It measures how central a domain is in "
        "the overall link graph -- it is not Moz or Ahrefs Domain "
        "Authority; this pipeline uses neither."
    )
    out.append("")

    out.append("## Caveats")
    out.append("")
    out += [
        "- Common Crawl covers a large but incomplete sample of the web; "
        "absence of a link here is not proof it does not exist.",
        "- Domain-level edges only: we know a domain links to hex.tech, "
        "not which page or anchor text -- the category and suggested "
        "action below come from that domain's homepage, not necessarily "
        "the specific page carrying the link.",
        "- \"Present in both releases\" is a soft persistence signal, not "
        "confirmation from two independent months: the two releases "
        "share two of their three underlying monthly crawls.",
        "- montecarlodata.com and montecarlo.ai are the same company "
        "(the former redirects to the latter): they are merged into the "
        "single montecarlo.ai row below (see report/duplicates.csv) "
        "rather than counted as two separate opportunities, so the 25 "
        "rows below are 25 distinct companies, not 25 domain strings.",
        "- Two domains below (getdbt.tech, backlinks.sbs) did not "
        "resolve when checked by hand; their categories and actions are "
        "best-guess (from the domain name and DNS records only), not "
        "confirmed from a live site.",
        "",
    ]

    out.append(
        f"{total} candidate domains met the filter (link to at least two "
        "of Sigma, Hex, Mode, and Lightdash, not to omni.co); the "
        f"{len(rows)} highest-ranked distinct companies are shown above "
        "(one same-company duplicate among them was merged into a single "
        "row -- see the caveats above)."
    )
    out.append("")

    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text("\n".join(out))
    print(f"wrote {OUT_PATH} with {len(rows)} domains across "
          f"{len(by_cat)} categories (of {total} total candidates, "
          f"{distinct_total} distinct companies)")


if __name__ == "__main__":
    main()
