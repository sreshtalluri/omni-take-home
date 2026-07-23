from etl.config import load_config

def test_load_config():
    cfg = load_config("etl/config.yaml")
    assert cfg.targets["omni"] == "omni.co"
    assert len(cfg.targets) == 5
    assert [r.label for r in cfg.releases] == ["2026-05", "2026-06"]
    assert cfg.http.max_attempts == 5
    assert abs(sum(cfg.score_weights.values()) - 1.0) < 1e-9
