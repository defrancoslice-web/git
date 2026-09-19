"""智能体的六个工具。工具是智能体唯一能做的事情集合，边界清晰、可单独测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from ..analytics import aggregate, overview
from ..cleaning import parse_quantity
from ..models import AnalysisRequest, AnalysisResult, ChartSpec
from ..pipeline import Pipeline

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "load_template",
            "description": "读取并解析灾情数据模板与字段规范，返回字段映射比对报告。",
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "Excel/CSV 文件路径列表"}
                },
                "required": ["paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "profile_data",
            "description": "对导入的原始数据做体检：字段完整率、取值分布、疑似异常值。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clean_data",
            "description": "执行缺失值填充、异常值处理、格式统一与行政层级校验，输出清洗日志。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate_analysis",
            "description": "按维度与指标执行分组聚合分析，返回明细记录与合计值。",
            "parameters": {
                "type": "object",
                "properties": {
                    "dimensions": {"type": "array", "items": {"type": "string"}},
                    "metrics": {"type": "array", "items": {"type": "string"}},
                    "filters": {"type": "object"},
                    "limit": {"type": "integer"},
                },
                "required": ["dimensions", "metrics"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_chart",
            "description": "根据分析结果自动选择图型并渲染，返回静态图路径与前端图表配置。",
            "parameters": {
                "type": "object",
                "properties": {
                    "dimensions": {"type": "array", "items": {"type": "string"}},
                    "metrics": {"type": "array", "items": {"type": "string"}},
                    "filters": {"type": "object"},
                    "title": {"type": "string"},
                },
                "required": ["dimensions", "metrics", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_heatmap",
            "description": "生成灾情空间分布图：热力图（按县级中心点渲染热力强度）或分级着色图（按行政区划边界分级上色）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "dimension": {"type": "string", "description": "区域维度，如 region_county、region_city"},
                    "metric": {"type": "string", "description": "指标，如 direct_economic_loss"},
                    "title": {"type": "string"},
                    "chart_type": {
                        "type": "string",
                        "enum": ["spatial_heatmap", "choropleth"],
                        "description": "默认 spatial_heatmap",
                    },
                    "filters": {"type": "object"},
                },
                "required": ["dimension", "metric", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_report",
            "description": "生成标准化分析报告，并按需导出 Markdown / Word / PDF。",
            "parameters": {
                "type": "object",
                "properties": {
                    "formats": {"type": "array", "items": {"type": "string", "enum": ["md", "docx", "pdf"]}}
                },
            },
        },
    },
]


class ToolBox:
    """工具实现。所有工具共享同一个 Pipeline 实例。"""

    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline

    @property
    def settings(self):
        return self.pipeline.settings

    # ---- 工具 1 ----
    def load_template(self, paths: Iterable[str | Path]) -> dict[str, Any]:
        report = self.pipeline.run_ingest(paths)
        return {
            "files": [Path(name).name for name in report.files],
            "sheets": report.sheets,
            "rows_read": report.rows_read,
            "matched_columns": report.matched_columns,
            "unmapped_columns": report.unmapped_columns,
            "missing_required": report.missing_required,
            "matched_rate": report.matched_rate,
            "issues": [issue.to_dict() for issue in report.issues],
        }

    # ---- 工具 2 ----
    def profile_data(self) -> dict[str, Any]:
        frame = self.pipeline._require("raw", "ingest")
        profile: dict[str, Any] = {
            "rows": int(len(frame)),
            "columns": int(frame.shape[1]),
            "fields": [],
        }
        for column in frame.columns:
            series = frame[column]
            missing = int(series.isna().sum())
            entry: dict[str, Any] = {
                "field": column,
                "label": (self.settings.field(column) or {}).get("label", column),
                "missing": missing,
                "missing_rate": round(missing / max(len(frame), 1), 4),
                "distinct": int(series.nunique(dropna=True)),
            }
            if column in self.settings.metric_names:
                unit_table = self.settings.cleaning["unit_conversion"].get(column, {})
                numeric = pd.Series(
                    [parse_quantity(value, unit_table)[0] for value in series],
                    index=series.index,
                    dtype="float64",
                )
                entry["numeric_parse_rate"] = round(float(numeric.notna().mean()), 4)
                entry["max"] = float(numeric.max()) if numeric.notna().any() else None
            profile["fields"].append(entry)
        profile["overview"] = overview(frame, self.settings) if not frame.empty else {}
        return profile

    # ---- 工具 3 ----
    def clean_data(self) -> dict[str, Any]:
        log = self.pipeline.run_clean()
        frame = self.pipeline._require("frame", "clean")
        return {
            "rows_in": log.rows_in,
            "rows_out": log.rows_out,
            "steps": [step.to_dict() for step in log.steps],
            "issues": [issue.to_dict() for issue in log.issues],
            "hierarchy_pending": int((~frame["_hierarchy_ok"].astype(bool)).sum())
            if "_hierarchy_ok" in frame
            else 0,
            "imputed_records": int((frame["_imputed_metrics"] > 0).sum())
            if "_imputed_metrics" in frame
            else 0,
        }

    # ---- 工具 4 ----
    def aggregate_analysis(
        self,
        dimensions: list[str],
        metrics: list[str],
        filters: dict[str, Any] | None = None,
        limit: int = 40,
    ) -> AnalysisResult:
        request = AnalysisRequest(
            dimensions=list(dimensions), metrics=list(metrics), filters=dict(filters or {}), limit=int(limit)
        )
        return self.pipeline.analyze(request)

    # ---- 工具 5 ----
    def render_chart(
        self,
        dimensions: list[str],
        metrics: list[str],
        title: str,
        filters: dict[str, Any] | None = None,
        filename: str | None = None,
    ) -> ChartSpec:
        analysis = self.aggregate_analysis(dimensions, metrics, filters or {})
        safe_name = filename or ("adhoc_" + "_".join(dimensions + metrics))[:60]
        return self.pipeline.render_chart(analysis, title, safe_name)

    # ---- 工具 6 ----
    def render_heatmap(
        self,
        dimension: str,
        metric: str,
        title: str,
        chart_type: str = "spatial_heatmap",
        filters: dict[str, Any] | None = None,
    ) -> ChartSpec:
        if chart_type not in {"spatial_heatmap", "choropleth"}:
            raise ValueError("chart_type 只支持 spatial_heatmap 或 choropleth")
        analysis = self.aggregate_analysis([dimension], [metric], filters or {}, limit=500)
        return self.pipeline.render_geo_chart(
            analysis, title, chart_type=chart_type, filename=f"adhoc_{chart_type}"
        )

    # ---- 工具 7 ----
    def write_report(self, formats: list[str] | None = None) -> dict[str, Any]:
        bundle = self.pipeline.run_report(tuple(formats or ["md", "docx", "pdf"]))
        return {
            "title": bundle.title,
            "sections": [section.title for section in bundle.sections],
            "outputs": self.pipeline.outputs,
        }

    # ---- 统一调用入口 ----
    def call(self, name: str, **kwargs: Any) -> Any:
        handler = getattr(self, name, None)
        if handler is None:
            raise ValueError(f"未注册的工具：{name}")
        if name in {"aggregate_analysis", "render_chart", "render_heatmap"}:
            result = handler(**kwargs)
            return result.to_dict() if hasattr(result, "to_dict") else result
        return handler(**kwargs)

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": item["function"]["name"],
                "description": item["function"]["description"],
                "parameters": list(item["function"]["parameters"].get("properties", {}).keys()),
            }
            for item in TOOL_SPECS
        ]
