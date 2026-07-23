"""Handcrafted toy web graph in Common Crawl file formats.

Referrers (normal order):
  bi-tools-blog.com  -> sigma, hex, mode   (winner: 3 competitors, no omni)
  data-weekly.io     -> sigma, hex         (2 competitors, no omni)
  friendly.dev       -> omni, sigma        (links to omni: excluded)
  one-link.net       -> hex                (below min_competitor_count)
  unrelated.org      -> one-link.net       (edge not touching targets: ignored)
"""
import gzip
from pathlib import Path
from etl.domains import reverse_domain

HERE = Path(__file__).parent
DOMAINS = sorted(reverse_domain(d) for d in [
    "omni.co", "sigmacomputing.com", "hex.tech", "mode.com", "lightdash.com",
    "bi-tools-blog.com", "data-weekly.io", "friendly.dev", "one-link.net",
    "unrelated.org",
])  # vertices sorted by reversed name, ids assigned in that order (CC convention)
IDS = {d: i for i, d in enumerate(DOMAINS)}
LINKS = [
    ("bi-tools-blog.com", "sigmacomputing.com"), ("bi-tools-blog.com", "hex.tech"),
    ("bi-tools-blog.com", "mode.com"), ("data-weekly.io", "sigmacomputing.com"),
    ("data-weekly.io", "hex.tech"), ("friendly.dev", "omni.co"),
    ("friendly.dev", "sigmacomputing.com"), ("one-link.net", "hex.tech"),
    ("unrelated.org", "one-link.net"),
]

def main():
    with gzip.open(HERE / "vertices.txt.gz", "wt") as f:
        for d, i in sorted(IDS.items(), key=lambda kv: kv[1]):
            f.write(f"{i}\t{d}\n")
    with gzip.open(HERE / "edges.txt.gz", "wt") as f:
        pairs = sorted((IDS[reverse_domain(s)], IDS[reverse_domain(t)]) for s, t in LINKS)
        for s, t in pairs:
            f.write(f"{s}\t{t}\n")
    with gzip.open(HERE / "ranks.txt.gz", "wt") as f:
        f.write("#hc_pos\t#hc_val\t#pr_pos\t#pr_val\t#rev_domain\n")
        for pos, (d, _) in enumerate(sorted(IDS.items()), start=1):
            f.write(f"{pos}\t0.5\t{pos}\t0.001\t{d}\n")
    (HERE / "graph.stats").write_text(f"nodes\t{len(DOMAINS)}\narcs\t{len(LINKS)}\n")

if __name__ == "__main__":
    main()
