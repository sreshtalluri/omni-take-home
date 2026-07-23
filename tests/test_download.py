import threading, functools
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import pytest
from etl.config import HttpCfg
from etl.download import download, DownloadError

HTTP = HttpCfg(max_attempts=3, timeout_s=5, backoff_base_s=0.01)

@pytest.fixture
def served_file(tmp_path):
    src = tmp_path / "srv" / "file.bin"
    src.parent.mkdir()
    src.write_bytes(b"x" * 10_000)
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(src.parent))
    srv = HTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}/file.bin", src
    srv.shutdown()

def test_download_full(served_file, tmp_path):
    url, src = served_file
    dest = tmp_path / "out.bin"
    download(url, dest, HTTP)
    assert dest.read_bytes() == src.read_bytes()

def test_download_resumes_partial(served_file, tmp_path):
    url, src = served_file
    dest = tmp_path / "out.bin"
    part = Path(str(dest) + ".part")
    part.write_bytes(b"x" * 4_000)          # simulate a crashed partial download
    download(url, dest, HTTP)
    assert dest.read_bytes() == src.read_bytes()

def test_download_fails_after_max_attempts(tmp_path):
    with pytest.raises(DownloadError):
        download("http://127.0.0.1:1/nope", tmp_path / "x", HTTP)

class _CountingGetHandler(SimpleHTTPRequestHandler):
    """Counts GET requests so tests can assert a GET was (or wasn't) made.

    do_HEAD is untouched/uncounted: a spec-compliant HEAD-only check must
    not register as a download attempt.
    """
    get_count = 0

    def do_GET(self):
        type(self).get_count += 1
        super().do_GET()

@pytest.fixture
def counting_served_file(tmp_path):
    src = tmp_path / "srv_counting" / "file.bin"
    src.parent.mkdir()
    src.write_bytes(b"x" * 10_000)
    _CountingGetHandler.get_count = 0
    handler = functools.partial(_CountingGetHandler, directory=str(src.parent))
    srv = HTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}/file.bin", src
    srv.shutdown()

def test_download_resume_already_complete_skips_get(counting_served_file, tmp_path):
    # Simulates a crash after the GET finished writing every byte but
    # before `part.rename(dest)` (e.g. the post-download HEAD raised, or
    # the process died right there). The .part on disk is already the
    # complete, correct file.
    url, src = counting_served_file
    dest = tmp_path / "out.bin"
    part = Path(str(dest) + ".part")
    part.write_bytes(src.read_bytes())
    download(url, dest, HTTP)
    assert dest.read_bytes() == src.read_bytes()
    assert not part.exists()
    assert _CountingGetHandler.get_count == 0  # no GET issued; HEAD-only recheck
