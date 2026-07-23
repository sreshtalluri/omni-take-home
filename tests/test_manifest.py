from etl.manifest import Manifest

def test_manifest_roundtrip(tmp_path):
    m = Manifest(tmp_path / "ck.json")
    assert not m.is_done("edges")
    m.mark_done("edges", size=123)
    assert m.is_done("edges")
    assert m.get("edges")["size"] == 123
    # a fresh instance reads the same state back from disk (crash-resume)
    assert Manifest(tmp_path / "ck.json").is_done("edges")
