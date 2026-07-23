import random, time
from pathlib import Path
import requests
from etl.config import HttpCfg

class DownloadError(Exception):
    pass

def download(url: str, dest: Path, http: HttpCfg) -> Path:
    dest = Path(dest)
    if dest.exists():
        return dest  # idempotent: caller's manifest decides re-download
    part = Path(str(dest) + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_err = None
    for attempt in range(http.max_attempts):
        try:
            offset = part.stat().st_size if part.exists() else 0
            if offset:
                # A .part may already be the complete file (crash/interrupt
                # happened after the GET finished writing but before the
                # rename, or before the HEAD used to verify it). Check
                # before issuing another GET so we don't send
                # Range: bytes=<full_size>- to a compliant server, which
                # answers 416 and would otherwise retry forever with the
                # same offset.
                total = _remote_size(url, http)
                if total is not None:
                    if offset == total:
                        part.rename(dest)
                        return dest
                    if offset > total:
                        part.unlink()  # corrupt/stale partial larger than remote
                        offset = 0
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            with requests.get(url, headers=headers, stream=True,
                              timeout=http.timeout_s) as r:
                if r.status_code == 200 and offset:
                    offset = 0  # server ignored Range: restart from scratch
                r.raise_for_status()
                mode = "ab" if offset else "wb"
                with open(part, mode) as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
            total = _remote_size(url, http)
            if total is not None and part.stat().st_size != total:
                raise DownloadError(
                    f"size mismatch: got {part.stat().st_size}, want {total}")
            part.rename(dest)
            return dest
        except Exception as e:  # noqa: BLE001 — every failure funnels into retry
            last_err = e
            if attempt < http.max_attempts - 1:
                time.sleep(http.backoff_base_s * (2 ** attempt) + random.uniform(0, 1))
    raise DownloadError(f"{url} failed after {http.max_attempts} attempts: {last_err}")

def _remote_size(url: str, http: HttpCfg):
    r = requests.head(url, timeout=http.timeout_s, allow_redirects=True)
    cl = r.headers.get("Content-Length")
    return int(cl) if cl else None
