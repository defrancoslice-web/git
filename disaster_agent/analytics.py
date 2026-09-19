"""模块二：多维度多层次综合分析。

设计要求：只保留一个分组聚合入口。灾种、时段、区域、损失结构以及自定义维度
全部表达为「维度参数」，新增分析维度不需要新增分析代码。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .cleaning import parse_date, parse_quantity
from .config import Settings
from .models import AnalysisRequest, AnalysisResult


def apply_filters(
    frame: pd.DataFrame, filters: dict[str, Any], settings: Settings
) -> tuple[pd.DataFrame, list[str]]:
    """按等值或集合条件筛选。

    字段名可以是标准字段名，也可以是维度名。
    大模型可能给出「近五年」这类自然语言取值，匹配不到记录时会忽略该条件并记录下来，
    避免整条分析因为一个无效筛选而返回空结果。
    """
    data = frame
    ignored: list[str] = []
    for key, value in filters.items():
        field = key
        spec = settings.dimension(key) if key in settings.dimensions else None
        if key in settings.dimensions:
            field = spec.get("field", key)
        if spec and spec.get("kind") == "virtual":
            continue
        if field not in data.columns:
            ignored.append(f"{key}={value}（无此字段）")
            continue
        if isinstance(value, (list, tuple, set)):
            mask = data[field].isin(list(value))
        else:
            matched = (data[field].astype(str) == str(value)).any()
            if not matched:
                ignored.append(f"{key}={value}（无匹配记录）")
                continue
            mask = data[field] == value
        data = data[mask]
    return data, ignored


def filter_hints(frame: pd.DataFrame, settings: Settings, limit: int = 40) -> dict[str, list[Any]]:
    """列出可筛选维度里真实出现过的取值，供大模型原样选用。"""
    hints: dict[str, list[Any]] = {}
    for name, spec in settings.dimensions.items():
        if spec.get("kind") == "virtual":
            continue
        field = spec.get("field")
        if not field or field not in frame.columns:
            continue
        values = frame[field].dropna().unique().tolist()
        if 0 < len(values) <= limit:
            hints[name] = sorted(values, key=lambda item: str(item))
    return hints


def _dimension_label(name: str, settings: Settings) -> str:
    return settings.dimension(name)["label"]


def _metric_label(name: str, settings: Settings) -> str:
    return settings.metric(name)["label"]


def _metric_unit(name: str, settings: Settings) -> str:
    return settings.metric(name)["unit"]


def loss_structure(frame: pd.DataFrame, settings: Settings, filters: dict[str, Any] | None = None) -> AnalysisResult:
    """损失结构分析：人员伤亡、财产、基础设施、农业、房屋。"""
    request = AnalysisRequest(
        dimensions=["loss_structure"], metrics=[], filters=filters or {}, labels=label_map(settings)
    )
    records: list[dict[str, Any]] = []
    for group in settings.loss_structure_groups:
        available = [name for name in group["metrics"] if name in frame.columns]
        if not available:
            continue
        value = float(frame[available].sum().sum())
        records.append(
            {
                "损失类型": group["name"],
                "数值": round(value, 4),
                "单位": group["unit"],
            }
        )

    amount_records = [item for item in records if item["单位"] == "万元"]
    amount_total = sum(item["数值"] for item in amount_records)
    for item in records:
        base = amount_total if item["单位"] == "万元" else None
        item["占比"] = round(item["数值"] / base, 4) if base else None

    return AnalysisResult(
        request=request,
        records=records,
        totals={
            "损失合计（万元）": round(amount_total, 2),
            "人员伤亡合计（人）": round(
                sum(item["数值"] for item in records if item["单位"] == "人"), 2
            ),
        },
        meta={
            "dimension_label": "损失结构",
            "primary_unit": "万元",
            "rows_after_filter": int(len(frame)),
        },
    )


def _order_key(values: list[Any], spec: dict[str, Any]) -> list[Any]:
    order = spec.get("order")
    if not order:
        return values
    index = {str(item): position for position, item in enumerate(order)}
    return sorted(values, key=lambda item: index.get(str(item), len(order)))


def aggregate(
    frame: pd.DataFrame, request: AnalysisRequest, settings: Settings
) -> AnalysisResult:
    """统一分组聚合入口。"""
    for name in request.dimensions:
        settings.dimension(name)
    for name in request.metrics:
        settings.metric(name)

    data, ignored_filters = apply_filters(frame, request.filters, settings)
    request.labels = label_map(settings)
    meta: dict[str, Any] = {
        "rows_input": int(len(frame)),
        "rows_after_filter": int(len(data)),
        "已忽略筛选": ignored_filters,
    }

    virtual = [name for name in request.dimensions if settings.dimension(name).get("kind") == "virtual"]
    if virtual:
        return loss_structure(data, settings, request.filters)

    if not data.empty and request.metrics:
        dim_fields = [settings.dimension(name)["field"] for name in request.dimensions]
        dimension_labels = [_dimension_label(name, settings) for name in request.dimensions]
        metric_labels = [_metric_label(name, settings) for name in request.metrics]

        if dim_fields:
            grouped = data.groupby(dim_fields, dropna=False)[request.metrics].sum().reset_index()
        else:
            grouped = pd.DataFrame([data[request.metrics].sum().to_dict()])

        grouped = grouped.rename(
            columns=dict(zip(dim_fields, dimension_labels)) | dict(zip(request.metrics, metric_labels))
        )
        records = grouped.to_dict(orient="records")
    else:
        dimension_labels = [_dimension_label(name, settings) for name in request.dimensions]
        metric_labels = [_metric_label(name, settings) for name in request.metrics]
        records = []

    # 排序：优先时间维度升序，其次分类维度的既定顺序，最后按首个指标降序
    if records:
        first_dimension = request.dimensions[0] if request.dimensions else None
        spec = settings.dimension(first_dimension) if first_dimension else {}
        first_label = dimension_labels[0] if dimension_labels else None
        primary_metric = metric_labels[0] if metric_labels else None

        if spec.get("kind") == "temporal" and first_label:
            records.sort(key=lambda item: (item.get(first_label) is None, item.get(first_label)))
        elif spec.get("order") and first_label:
            index = {str(item): position for position, item in enumerate(spec["order"])}
            records.sort(key=lambda item: index.get(str(item.get(first_label)), len(index)))
        elif primary_metric:
            records.sort(key=lambda item: item.get(primary_metric) or 0, reverse=not request.ascending)

        if request.sort_by and request.sort_by in (metric_labels + dimension_labels):
            records.sort(key=lambda item: item.get(request.sort_by) or 0, reverse=not request.ascending)

    meta["columns"] = (
        [{"key": label, "role": "dimension"} for label in dimension_labels]
        + [
            {"key": label, "role": "metric", "unit": _metric_unit(name, settings)}
            for name, label in zip(request.metrics, metric_labels)
        ]
    )

    totals = {_metric_label(name, settings): round(float(data[name].sum()), 4) for name in request.metrics}

    return AnalysisResult(
        request=request,
        records=records[: request.limit],
        totals=totals,
        meta={**meta, "record_count": len(records)},
    )


def sum_metric(frame: pd.DataFrame, name: str, settings: Settings) -> float:
    """指标求和。原始数据里可能带单位文本，这里统一走解析器。"""
    if name not in frame.columns:
        return 0.0
    unit_table = settings.cleaning["unit_conversion"].get(name, {})
    total = 0.0
    for value in frame[name]:
        parsed, unit = parse_quantity(value, unit_table)
        if parsed is None:
            continue
        total += parsed * float(unit_table.get(unit, 1.0)) if unit else parsed
    return total


def _date_series(frame: pd.DataFrame, settings: Settings) -> pd.Series:
    if "occur_date" not in frame.columns:
        return pd.Series(dtype="datetime64[ns]")
    column = frame["occur_date"]
    if pd.api.types.is_datetime64_any_dtype(column):
        return pd.to_datetime(column, errors="coerce")
    formats = settings.cleaning["date_formats"]
    parsed = pd.Series([parse_date(value, formats) for value in column], index=column.index)
    return pd.to_datetime(parsed, errors="coerce")


def overview(frame: pd.DataFrame, settings: Settings) -> dict[str, Any]:
    """灾情总体概况：报告第一节与看板首页共用，原始数据与清洗后数据都能算。"""
    result: dict[str, Any] = {
        "记录条数": int(len(frame)),
        "涉及灾种数": int(frame["disaster_type"].nunique()) if "disaster_type" in frame else 0,
        "覆盖县（区）数": int(frame["county"].nunique()) if "county" in frame else 0,
    }
    moments = _date_series(frame, settings)
    if len(moments) and moments.notna().any():
        result["统计时段"] = f"{moments.min():%Y-%m-%d} 至 {moments.max():%Y-%m-%d}"
    else:
        result["统计时段"] = "未知"

    for name in settings.metric_names:
        spec = settings.metric(name)
        if name in frame.columns and frame[name].notna().any():
            result[f"{spec['label']}（{spec['unit']}）"] = round(sum_metric(frame, name, settings), 2)

    if "direct_economic_loss" in frame.columns and len(frame):
        result["单次事件平均直接经济损失（万元）"] = round(
            sum_metric(frame, "direct_economic_loss", settings) / len(frame), 2
        )
    if "_imputed_metrics" in frame.columns:
        result["含缺失填充的记录数"] = int((frame["_imputed_metrics"] > 0).sum())
    if "_hierarchy_ok" in frame.columns:
        result["行政区划待确认记录数"] = int((~frame["_hierarchy_ok"].astype(bool)).sum())
    return result


def dimension_catalog(settings: Settings) -> list[dict[str, Any]]:
    """给前端和智能体用的维度清单。"""
    return [
        {
            "name": name,
            "label": spec["label"],
            "kind": spec.get("kind", "categorical"),
            "custom": bool(spec.get("custom")),
        }
        for name, spec in settings.dimensions.items()
    ]


def label_map(settings: Settings) -> dict[str, str]:
    """名称 -> 中文标签，用于把分析计划翻译成人话。"""
    mapping = {name: spec["label"] for name, spec in settings.dimensions.items()}
    mapping.update({name: spec["label"] for name, spec in settings.metrics.items()})
    return mapping


def metric_catalog(settings: Settings) -> list[dict[str, Any]]:
    return [
        {"name": name, "label": spec["label"], "unit": spec["unit"], "group": spec.get("loss_group", "")}
        for name, spec in settings.metrics.items()
    ]
