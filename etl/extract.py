"""Stream filters over gzipped CC graph files.

gzip -dc | awk keeps peak memory flat and never materializes the ~50GB
decompressed edge list. awk (not Python) does the inner loop: ~10x faster
on a billion-line scan, and available on any macOS/Linux box.
"""
import shlex, subprocess, tempfile
from pathlib import Path

class ExtractError(Exception):
    pass

def _awk_filter(gz: Path, awk_prog: str, keyfile_lines=None, out=None) -> int:
    """Run gzip -dc <gz> | awk <prog>, optionally passing a lookup file as
    -v keyfile=..., writing stdout to `out`. Returns line count written.

    The keyfile is written with NamedTemporaryFile(delete=False) because awk
    opens it by path in a separate process -- it can't be handed an
    already-open, delete-on-close file descriptor the way an in-process
    reader could use one. It is always removed in `finally` (success or
    ExtractError) so repeated calls -- one per extractor call in a real
    pipeline run, or dozens across a test session -- don't accumulate
    orphaned *.keys files in the system temp dir.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".keys", delete=False) as kf:
        if keyfile_lines is not None:
            kf.write("\n".join(str(k) for k in keyfile_lines) + "\n")
        keypath = kf.name
    try:
        cmd = (f"gzip -dc {shlex.quote(str(gz))} | "
               f"awk -F'\\t' -v keyfile={shlex.quote(keypath)} {shlex.quote(awk_prog)}")
        with open(out, "w") if out else tempfile.TemporaryFile("w+") as fh:
            proc = subprocess.run(["bash", "-o", "pipefail", "-c", cmd],
                                  stdout=fh, stderr=subprocess.PIPE, text=True)
            if proc.returncode != 0:
                raise ExtractError(f"stream filter failed on {gz}: {proc.stderr[-2000:]}")
            fh.seek(0)
            return sum(1 for _ in fh) if out is None else _count_lines(out)
    finally:
        Path(keypath).unlink(missing_ok=True)

def _count_lines(path) -> int:
    with open(path) as f:
        return sum(1 for _ in f)

_LOAD_KEYS = 'BEGIN { while ((getline k < keyfile) > 0) keys[k] = 1 } '

def find_target_ids(vertices_gz, targets_rev, cols) -> dict:
    """Map vertex id -> target domain (normal order) for the configured
    target domains. Raises ExtractError if any target is missing."""
    ci, cd = cols["vertices"]["id"], cols["vertices"]["rev_domain"]
    prog = _LOAD_KEYS + f'($({cd}) in keys) {{ print $({ci}) "\\t" $({cd}) }}'
    found = {}
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "target_ids.tsv"
        _awk_filter(vertices_gz, prog, keyfile_lines=targets_rev.keys(), out=out)
        for line in out.read_text().splitlines():
            vid, rev = line.split("\t")
            found[int(vid)] = targets_rev[rev]
    missing = set(targets_rev.values()) - set(found.values())
    if missing:
        raise ExtractError(f"targets not found in vertices file: {missing}")
    return found

def filter_edges(edges_gz, target_ids, out_tsv, cols) -> int:
    """Write src_id<TAB>target_domain rows for edges whose destination is a
    target vertex. Returns row count."""
    cs, cd = cols["edges"]["src"], cols["edges"]["dst"]
    prog = _LOAD_KEYS + f'($({cd}) in keys) {{ print $({cs}) "\\t" $({cd}) }}'
    n = _awk_filter(edges_gz, prog, keyfile_lines=target_ids.keys(), out=Path(out_tsv))
    # rewrite dst ids as domain names so downstream never needs the id space
    lines = Path(out_tsv).read_text().splitlines()
    with open(out_tsv, "w") as f:
        for line in lines:
            s, d = line.split("\t")
            f.write(f"{s}\t{target_ids[int(d)]}\n")
    return n

def resolve_source_domains(vertices_gz, src_ids, out_tsv, cols) -> int:
    """Write src_id<TAB>rev_domain rows for the given vertex ids."""
    ci, cd = cols["vertices"]["id"], cols["vertices"]["rev_domain"]
    prog = _LOAD_KEYS + f'($({ci}) in keys) {{ print $({ci}) "\\t" $({cd}) }}'
    return _awk_filter(vertices_gz, prog, keyfile_lines=src_ids, out=Path(out_tsv))

def filter_ranks(ranks_gz, rev_domains, out_tsv, cols) -> int:
    """Write rev_domain<TAB>hc_pos<TAB>pr_pos rows for the given domains."""
    ch, cp, cd = cols["ranks"]["hc_pos"], cols["ranks"]["pr_pos"], cols["ranks"]["rev_domain"]
    prog = _LOAD_KEYS + f'($({cd}) in keys) {{ print $({cd}) "\\t" $({ch}) "\\t" $({cp}) }}'
    return _awk_filter(ranks_gz, prog, keyfile_lines=rev_domains, out=Path(out_tsv))

def read_stats(path) -> dict:
    """Parse a CC .stats/.properties file into a dict of int values. At
    minimum returns {"nodes": int} for percentile math; raises ExtractError
    if the node count can't be found."""
    stats = {}
    for line in Path(path).read_text().splitlines():
        parts = line.replace("=", "\t").split("\t")
        if len(parts) >= 2 and parts[1].strip().isdigit():
            stats[parts[0].strip()] = int(parts[1])
    if "nodes" not in stats:
        raise ExtractError(f"could not read node count from {path}")
    return stats
