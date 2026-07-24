from dataclasses import dataclass
from pathlib import Path
import yaml

@dataclass(frozen=True)
class HttpCfg:
    max_attempts: int
    timeout_s: int
    backoff_base_s: float

@dataclass(frozen=True)
class Release:
    id: str
    label: str
    crawls: list

@dataclass(frozen=True)
class Config:
    targets: dict
    releases: list
    base_url: str
    http: HttpCfg
    data_dir: str
    duckdb_path: str
    columns: dict

def load_config(path="etl/config.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text())
    return Config(
        targets=raw["targets"],
        releases=[Release(**r) for r in raw["releases"]],
        base_url=raw["base_url"].rstrip("/"),
        http=HttpCfg(**raw["http"]),
        data_dir=raw["data_dir"],
        duckdb_path=raw["duckdb_path"],
        columns=raw["columns"],
    )
