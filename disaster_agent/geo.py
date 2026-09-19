"""空间数据支持：加载行政区划 GeoJSON，并把分析结果匹配到地图要素。

地图文件放在 data/geo/ 下，来源为公开的行政区划边界数据。
没有地图文件时全部相关功能自动降级，不影响其它图表。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .config import DATA_DIR

GEO_DIR = DATA_DIR / "geo"

# 行政区层级 -> 地图文件（不含扩展名）
LEVEL_MAP = {
    2: "sichuan_city",
    3: "sichuan_county",
}

_CACHE: dict[str, "GeoAssets"] = {}


@dataclass
class GeoAssets:
    """一份地图资源。"""

    name: str
    path: Path
    features: list[dict[str, Any]]
    names: list[str] = field(default_factory=list)
    centroids: dict[str, list[float]] = field(default_factory=dict)
    duplicates: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        counter: dict[str, int] = {}
        for feature in self.features:
            properties = feature.get("properties") or {}
            name = str(properties.get("name") or "").strip()
            if not name:
                continue
            counter[name] = counter.get(name, 0) + 1
            if name not in self.centroids:
                point = properties.get("centroid") or properties.get("center")
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    self.centroids[name] = [float(point[0]), float(point[1])]
        self.names = list(counter.keys())
        self.duplicates = [name for name, count in counter.items() if count > 1]


def map_name_for_level(level: int) -> str | None:
    return LEVEL_MAP.get(int(level))


def geo_path(name: str) -> Path:
    return GEO_DIR / f"{name}.json"


def geo_available(level: int) -> bool:
    name = map_name_for_level(level)
    return bool(name) and geo_path(name).exists()


def load_geo(name: str) -> GeoAssets | None:
    """加载地图文件，带进程内缓存。文件不存在时返回 None。"""
    if name in _CACHE:
        return _CACHE[name]
    path = geo_path(name)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assets = GeoAssets(name=name, path=path, features=list(payload.get("features", [])))
    _CACHE[name] = assets
    return assets


def iter_polygons(geometry: dict[str, Any] | None) -> Iterator[list[list[float]]]:
    """遍历几何体的外环坐标。支持 Polygon 与 MultiPolygon。"""
    if not geometry:
        return
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "Polygon":
        for ring in coordinates[:1]:
            if ring:
                yield ring
    elif kind == "MultiPolygon":
        for polygon in coordinates:
            for ring in polygon[:1]:
                if ring:
                    yield ring


def match_values(
    assets: GeoAssets,
    records: list[dict[str, Any]],
    name_field: str,
    value_field: str,
) -> dict[str, Any]:
    """把分析记录匹配到地图要素名称。

    只返回有数据的区域，没有数据的区域不参与着色，避免把「无数据」误读成「零损失」。
    同时给出未匹配到的记录、以及命中重名的区域。
    """
    lookup: dict[str, float] = {}
    matched: list[str] = []
    for row in records:
        name = str(row.get(name_field) or "").strip()
        if name not in assets.names:
            continue
        try:
            value = float(row.get(value_field) or 0)
        except (TypeError, ValueError):
            continue
        lookup[name] = lookup.get(name, 0.0) + value
        matched.append(name)

    data = [{"name": name, "value": round(value, 4)} for name, value in lookup.items()]
    values = [item["value"] for item in data]
    return {
        "data": data,
        "min": min(values) if values else 0.0,
        "max": max(values) if values else 0.0,
        "matched_count": len(set(matched)),
        "missing_count": max(len(assets.names) - len(lookup), 0),
        "duplicate_names": assets.duplicates,
        "unmatched_records": [
            str(row.get(name_field))
            for row in records
            if str(row.get(name_field) or "").strip() not in lookup
        ][:10],
    }


def list_maps() -> list[dict[str, Any]]:
    """已安装的地图清单，供界面和命令行查看。"""
    result: list[dict[str, Any]] = []
    for level, name in sorted(LEVEL_MAP.items()):
        path = geo_path(name)
        result.append(
            {
                "name": name,
                "level": level,
                "installed": path.exists(),
                "path": str(path),
                "size_kb": round(path.stat().st_size / 1024, 1) if path.exists() else 0,
            }
        )
    return result
