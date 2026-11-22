"""经纬度与以地图原点为基准的平面米制坐标（x 向东，y 向北）互相转换。用等距方位投影。"""

from __future__ import annotations

from functools import lru_cache

from pyproj import Transformer


@lru_cache(maxsize=32)
def _transformers(lon0: float, lat0: float) -> tuple[Transformer, Transformer]:
    proj = f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs"
    fwd = Transformer.from_crs("EPSG:4326", proj, always_xy=True)
    inv = Transformer.from_crs(proj, "EPSG:4326", always_xy=True)
    return fwd, inv


def to_meters(lon0: float, lat0: float, lon: float, lat: float) -> tuple[float, float]:
    x, y = _transformers(lon0, lat0)[0].transform(lon, lat)
    return float(x), float(y)


def to_lonlat(lon0: float, lat0: float, x: float, y: float) -> tuple[float, float]:
    lon, lat = _transformers(lon0, lat0)[1].transform(x, y)
    return float(lon), float(lat)
