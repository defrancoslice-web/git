"""领域模型：模块之间只通过这里的结构传递数据，便于替换实现。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Issue:
    """一次数据质量问题。level 取 info / warning / error。"""

    level: str
    code: str
    message: str
    count: int = 1
    samples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "count": self.count,
            "samples": self.samples,
        }


@dataclass
class IngestReport:
    """数据接入与模板比对报告。"""

    files: list[str] = field(default_factory=list)
    sheets: list[str] = field(default_factory=list)
    rows_read: int = 0
    columns_raw: list[str] = field(default_factory=list)
    matched_columns: dict[str, str] = field(default_factory=dict)
    unmapped_columns: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    rows_out: int = 0

    @property
    def matched_rate(self) -> float:
        total = len(self.matched_columns) + len(self.unmapped_columns)
        return round(len(self.matched_columns) / total, 4) if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": self.files,
            "sheets": self.sheets,
            "rows_read": self.rows_read,
            "rows_out": self.rows_out,
            "columns_raw": self.columns_raw,
            "matched_columns": self.matched_columns,
            "unmapped_columns": self.unmapped_columns,
            "missing_required": self.missing_required,
            "matched_rate": self.matched_rate,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass
class CleanStep:
    """一条可追溯的清洗动作记录。"""

    step: str
    field: str
    action: str
    affected: int
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "field": self.field,
            "action": self.action,
            "affected": self.affected,
            "detail": self.detail,
        }


@dataclass
class CleaningLog:
    """清洗日志：改了什么、依据什么、影响多少行。"""

    rows_in: int = 0
    rows_out: int = 0
    steps: list[CleanStep] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    def add(self, step: str, field_name: str, action: str, affected: int, detail: str = "") -> None:
        if affected <= 0:
            return
        self.steps.append(CleanStep(step, field_name, action, int(affected), detail))

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "steps": [step.to_dict() for step in self.steps],
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass
class AnalysisRequest:
    """一个分析计划：维度 × 指标 × 筛选 × 口径。"""

    dimensions: list[str]
    metrics: list[str]
    filters: dict[str, Any] = field(default_factory=dict)
    limit: int = 50
    sort_by: str | None = None
    ascending: bool = False
    labels: dict[str, str] = field(default_factory=dict)

    def describe(self) -> str:
        def show(name: str) -> str:
            return self.labels.get(name, name)

        dim_text = " × ".join(show(name) for name in self.dimensions) if self.dimensions else "全局"
        metric_text = "、".join(show(name) for name in self.metrics)
        filter_text = (
            "；筛选：" + "，".join(f"{show(key)}={value}" for key, value in self.filters.items())
            if self.filters
            else ""
        )
        return f"按 {dim_text} 统计 {metric_text}{filter_text}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensions": [self.labels.get(name, name) for name in self.dimensions],
            "dimension_keys": self.dimensions,
            "metrics": [self.labels.get(name, name) for name in self.metrics],
            "metric_keys": self.metrics,
            "filters": self.filters,
            "limit": self.limit,
            "sort_by": self.sort_by,
            "ascending": self.ascending,
            "description": self.describe(),
        }


@dataclass
class AnalysisResult:
    """分析结果。records 是可直接序列化的明细记录。"""

    request: AnalysisRequest
    records: list[dict[str, Any]] = field(default_factory=list)
    totals: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "records": self.records,
            "totals": self.totals,
            "meta": self.meta,
        }


@dataclass
class ChartSpec:
    """一张图：图型、数据、渲染结果与前端图表配置。"""

    chart_type: str
    label: str
    why: str
    title: str
    metric: str
    unit: str
    x_label: str = ""
    y_label: str = ""
    categories: list[Any] = field(default_factory=list)
    series: list[dict[str, Any]] = field(default_factory=list)
    png_path: str | None = None
    echarts_option: dict[str, Any] = field(default_factory=dict)
    geo: dict[str, Any] = field(default_factory=dict)
    analysis: AnalysisResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chart_type": self.chart_type,
            "label": self.label,
            "why": self.why,
            "title": self.title,
            "metric": self.metric,
            "unit": self.unit,
            "x_label": self.x_label,
            "y_label": self.y_label,
            "categories": self.categories,
            "series": self.series,
            "png_path": self.png_path,
            "echarts_option": self.echarts_option,
            "geo": self.geo,
            "analysis": self.analysis.to_dict() if self.analysis else None,
        }
