"""地图文件的存储：一个目录里的 <id>.geojson。"""

from __future__ import annotations

import re
import threading
from pathlib import Path

from smartkeeper.contracts import MapData, NotFound, ValidationFailed
from smartkeeper.mapdata.fileformat import parse_map

_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class FileMapStore:
    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._cache: dict[str, tuple[float, MapData]] = {}
        self._lock = threading.Lock()

    def _path(self, map_id: str) -> Path:
        if not _ID.match(map_id):
            raise ValidationFailed("map.bad_id", id=map_id)
        return self._dir / f"{map_id}.geojson"

    def load(self, map_id: str) -> MapData:
        path = self._path(map_id)
        if not path.is_file():
            raise NotFound("map.not_found", id=map_id)
        mtime = path.stat().st_mtime
        with self._lock:
            hit = self._cache.get(map_id)
            if hit is not None and hit[0] == mtime:
                return hit[1]
        m = parse_map(path.read_text(encoding="utf-8"))
        m = m.model_copy(update={"id": map_id})
        with self._lock:
            self._cache[map_id] = (mtime, m)
        return m

    def list_ids(self) -> list[str]:
        if not self._dir.is_dir():
            return []
        return sorted(p.stem for p in self._dir.glob("*.geojson"))

    def save(self, map_id: str, text: str) -> MapData:
        m = parse_map(text)
        path = self._path(map_id)
        self._dir.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return m.model_copy(update={"id": map_id})
