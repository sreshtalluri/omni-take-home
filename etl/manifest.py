import json, os
from pathlib import Path

class Manifest:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def get(self, key):
        return self._data.get(key)

    def is_done(self, key):
        return self._data.get(key, {}).get("done", False)

    def mark_done(self, key, **meta):
        self._data[key] = {"done": True, **meta}
        tmp = self.path.with_suffix(".tmp")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(self._data, indent=2))
        os.replace(tmp, self.path)  # atomic: crash never corrupts the manifest
