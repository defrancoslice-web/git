"""配置加载：字段规范、清洗规则、图型规则、报告骨架全部外置为 JSON。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"


def load_json(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class Settings:
    """一次性加载全部配置，供各模块共享。"""

    def __init__(self, config_dir: str | Path | None = None) -> None:
        self.config_dir = Path(config_dir) if config_dir else CONFIG_DIR
        self.schema = load_json(self.config_dir / "schema.json")
        self.cleaning = load_json(self.config_dir / "cleaning_rules.json")
        self.chart_rules = load_json(self.config_dir / "chart_rules.json")
        self.outline = load_json(self.config_dir / "report_outline.json")

    @property
    def fields(self) -> list[dict[str, Any]]:
        return self.schema["fields"]

    @property
    def field_names(self) -> list[str]:
        return [item["name"] for item in self.fields]

    @property
    def required_fields(self) -> list[str]:
        return list(self.schema.get("required_fields", []))

    def field(self, name: str) -> dict[str, Any] | None:
        for item in self.fields:
            if item["name"] == name:
                return item
        return None

    @property
    def aliases(self) -> dict[str, str]:
        return dict(self.schema.get("aliases", {}))

    @property
    def metrics(self) -> dict[str, dict[str, Any]]:
        return self.schema["metrics"]

    @property
    def metric_names(self) -> list[str]:
        return list(self.metrics.keys())

    def metric(self, name: str) -> dict[str, Any]:
        if name not in self.metrics:
            raise KeyError(f"未注册的指标：{name}")
        return self.metrics[name]

    @property
    def loss_structure_groups(self) -> list[dict[str, Any]]:
        return self.schema["loss_structure_groups"]

    @property
    def dimensions(self) -> dict[str, dict[str, Any]]:
        return self.schema["dimensions"]

    def dimension(self, name: str) -> dict[str, Any]:
        if name not in self.dimensions:
            raise KeyError(f"未注册的维度：{name}")
        return self.dimensions[name]

    @property
    def custom_dimensions(self) -> list[str]:
        return [name for name, spec in self.dimensions.items() if spec.get("custom")]

    @property
    def region_dimensions(self) -> dict[int, str]:
        """行政区层级 -> 维度名。"""
        result: dict[int, str] = {}
        for name, spec in self.dimensions.items():
            if spec.get("kind") == "region":
                result[int(spec["level"])] = name
        return result

    def region_field(self, level: int) -> str:
        dimension = self.region_dimensions[level]
        return self.dimensions[dimension]["field"]

    def output_path(self, *parts: str) -> Path:
        path = OUTPUT_DIR.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def project_path(self, relative: str) -> Path:
        return PROJECT_ROOT / relative

