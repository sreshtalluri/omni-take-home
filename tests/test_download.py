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
