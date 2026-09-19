"""模块三：可视化图表生成。

图型由规则表决定，智能体只能在候选图型里选择，不能自由造图；
每次输出同时给出静态 PNG（离线可看）与 ECharts 配置（前端可交互）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager, rcParams  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, Normalize  # noqa: E402

from . import geo as geo_module  # noqa: E402
from .config import Settings  # noqa: E402
from .models import AnalysisResult, ChartSpec  # noqa: E402

GEO_CHART_TYPES = {"choropleth", "spatial_heatmap"}

_TYPE_LABELS = {
    "trend_line": "趋势类-多系列折线图",
    "trend_area": "趋势类-面积图",
    "compare_bar": "对比类-柱状图",
    "region_rank_bar": "空间分布类-分级排序条形图",
    "structure_donut": "占比类-环形图",
    "matrix_heatmap": "自定义图表-矩阵热力图",
    "choropleth": "空间分布类-分级着色图",
    "spatial_heatmap": "空间分布类-热力图",
}

_TYPE_WHY = {
    "choropleth": "按行政区划边界对指标值分级着色，直观呈现灾情空间聚集特征；灰色为无灾害记录区域",
    "spatial_heatmap": "以县级行政中心为点位、按指标值渲染热力强度，突出高值聚集区；无数据区域不显示热力点",
    "region_rank_bar": "按指标值排序的横向条形图，用于区域之间的对比",
    "compare_bar": "单一分类维度的横向对比",
}

_FONT_CANDIDATES = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "SimSun",
    "Arial Unicode MS",
]
_FONT_READY = False


def configure_fonts() -> str | None:
    """选择可用的中文字体，避免图表出现方块字。"""
    global _FONT_READY
    available = {font.name for font in font_manager.fontManager.ttflist}
    chosen = next((name for name in _FONT_CANDIDATES if name in available), None)
    if chosen:
        rcParams["font.sans-serif"] = [chosen]
    rcParams["axes.unicode_minus"] = False
    _FONT_READY = True
    return chosen


def match_rule(
    request_dimensions: list[str], settings: Settings, geo_available: bool = False
) -> dict[str, Any]:
    """按规则表匹配图型，未命中则用兜底图型。"""
    specs = [settings.dimension(name) for name in request_dimensions]
    facts = {
        "dimension_count": len(request_dimensions),
        "has_temporal_dimension": any(spec.get("kind") == "temporal" for spec in specs),
        "has_region_dimension": any(spec.get("kind") == "region" for spec in specs),
        "has_virtual_dimension": any(spec.get("kind") == "virtual" for spec in specs),
        "region_level": [spec.get("level") for spec in specs if spec.get("kind") == "region"],
    }

    matched: list[dict[str, Any]] = []
    for rule in settings.chart_rules["rules"]:
        if rule.get("requires_geo") and not geo_available:
            continue
        conditions = rule.get("when", {})
        ok = True
        for key, expected in conditions.items():
            actual = facts.get(key)
            if key == "region_level":
                if not set(expected) & set(actual or []):
                    ok = False
                    break
            elif actual != expected:
                ok = False
                break
        if ok:
            matched.append(rule)

    if not matched:
        return dict(settings.chart_rules["default"])
    return max(matched, key=lambda rule: rule.get("priority", 0))


def _geo_palette(settings: Settings) -> list[str]:
    return settings.chart_rules.get("geo_palette") or ["#f2f7fd", "#9dc0e4", "#2f6fb5", "#1c4b80"]


def _choropleth_option(spec: ChartSpec, settings: Settings) -> dict[str, Any]:
    geo = spec.geo
    unit = f" {spec.unit}" if spec.unit else ""
    return {
        "title": {"text": spec.title, "left": "center"},
        "tooltip": {"trigger": "item", "formatter": "{b}<br/>" + spec.y_label + "：{c}" + unit},
        "visualMap": {
            "min": geo.get("min", 0),
            "max": geo.get("max", 1) or 1,
            "left": "left",
            "bottom": 10,
            "calculable": True,
            "text": ["高", "低"],
            "inRange": {"color": _geo_palette(settings)},
        },
        "series": [
            {
                "type": "map",
                "map": geo.get("map"),
                "roam": True,
                "zoom": 1.02,
                "label": {"show": False},
                "emphasis": {
                    "label": {"show": True, "fontSize": 11},
                    "itemStyle": {"areaColor": "#ffd166"},
                },
                "itemStyle": {"borderColor": "#ffffff", "borderWidth": 0.6, "areaColor": "#f3f4f6"},
                "data": geo.get("data", []),
            }
        ],
    }


def _spatial_heatmap_option(spec: ChartSpec, settings: Settings) -> dict[str, Any]:
    geo = spec.geo
    unit = f" {spec.unit}" if spec.unit else ""
    return {
        "title": {"text": spec.title, "left": "center"},
        "tooltip": {"trigger": "item", "formatter": "{b}<br/>" + spec.y_label + "：{c}" + unit},
        "visualMap": {
            "min": geo.get("min", 0),
            "max": geo.get("max", 1) or 1,
            "left": "left",
            "bottom": 10,
            "calculable": True,
            "text": ["高", "低"],
            "inRange": {"color": _geo_palette(settings)},
        },
        "geo": {
            "map": geo.get("map"),
            "roam": True,
            "zoom": 1.02,
            "itemStyle": {"areaColor": "#f1f3f6", "borderColor": "#d5dbe3", "borderWidth": 0.5},
            "emphasis": {"itemStyle": {"areaColor": "#e6ebf2"}, "label": {"show": False}},
        },
        "series": [
            {
                "type": "heatmap",
                "coordinateSystem": "geo",
                "pointSize": 26,
                "blurSize": 36,
                "minOpacity": 0.25,
                "data": geo.get("points", []),
            }
        ],
    }


def _numeric(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if result != result else result


def _extract(
    analysis: AnalysisResult, settings: Settings
) -> tuple[list[Any], list[dict[str, Any]], str, str]:
    """从分析结果里抽出 categories / series / 指标名 / 单位。"""
    request = analysis.request
    dimension_labels = [settings.dimension(name)["label"] for name in request.dimensions]

    if request.dimensions and settings.dimension(request.dimensions[0]).get("kind") == "virtual":
        primary_unit = analysis.meta.get("primary_unit", "万元")
        rows = [item for item in analysis.records if item.get("单位") == primary_unit]
        categories = [item["损失类型"] for item in rows]
        series = [{"name": f"损失额（{primary_unit}）", "values": [_numeric(item["数值"]) for item in rows]}]
        return categories, series, "损失额", primary_unit

    metric_names = request.metrics
    metric_label = settings.metric(metric_names[0])["label"] if metric_names else "数值"
    unit = settings.metric(metric_names[0])["unit"] if metric_names else ""

    if not dimension_labels:
        return [], [{"name": metric_label, "values": []}], metric_label, unit

    if len(dimension_labels) == 1:
        label = dimension_labels[0]
        categories = [item.get(label) for item in analysis.records]
        values = [_numeric(item.get(metric_label)) for item in analysis.records]
        return categories, [{"name": metric_label, "values": values}], metric_label, unit

    first, second = dimension_labels[0], dimension_labels[1]
    categories: list[Any] = []
    for item in analysis.records:
        value = item.get(first)
        if value not in categories:
            categories.append(value)
    series_names: list[Any] = []
    for item in analysis.records:
        value = item.get(second)
        if value not in series_names:
            series_names.append(value)

    series: list[dict[str, Any]] = []
    for name in series_names:
        lookup = {
            item.get(first): _numeric(item.get(metric_label))
            for item in analysis.records
            if item.get(second) == name
        }
        series.append({"name": str(name), "values": [lookup.get(category, 0.0) for category in categories]})
    return categories, series, metric_label, unit


def build_echarts_option(spec: ChartSpec, settings: Settings) -> dict[str, Any]:
    """生成前端可直接渲染的 ECharts 配置。"""
    if spec.chart_type == "choropleth":
        return _choropleth_option(spec, settings)
    if spec.chart_type == "spatial_heatmap":
        return _spatial_heatmap_option(spec, settings)

    palette = settings.chart_rules.get("palette", [])
    base: dict[str, Any] = {
        "title": {"text": spec.title, "left": "center"},
        "color": palette,
        "tooltip": {"trigger": "axis" if spec.chart_type != "structure_donut" else "item"},
        "legend": {"bottom": 0},
        "grid": {"left": 68, "right": 24, "top": 56, "bottom": 48},
    }

    if spec.chart_type == "structure_donut":
        values = spec.series[0]["values"] if spec.series else []
        base["tooltip"] = {"trigger": "item"}
        base["legend"] = {"bottom": 0}
        base["series"] = [
            {
                "type": "pie",
                "radius": ["42%", "68%"],
                "center": ["50%", "48%"],
                "data": [
                    {"name": str(name), "value": value}
                    for name, value in zip(spec.categories, values)
                ],
                "label": {"formatter": "{b}: {d}%"},
            }
        ]
        return base

    x_axis: dict[str, Any] = {
        "type": "category",
        "data": [str(item) for item in spec.categories],
        "name": spec.x_label,
        "axisLabel": {"rotate": 30 if len(spec.categories) > 8 else 0},
    }
    y_axis: dict[str, Any] = {
        "type": "value",
        "name": f"{spec.y_label}（{spec.unit}）" if spec.unit else spec.y_label,
    }

    if spec.chart_type == "region_rank_bar":
        base["xAxis"] = y_axis
        base["yAxis"] = {**x_axis, "name": spec.y_label, "inverse": False}
        base["series"] = [
            {"type": "bar", "name": item["name"], "data": item["values"], "barMaxWidth": 24}
            for item in spec.series
        ]
        return base

    base["xAxis"] = x_axis
    base["yAxis"] = y_axis
    if spec.chart_type in {"trend_line", "trend_area"}:
        base["series"] = [
            {
                "type": "line",
                "name": item["name"],
                "data": item["values"],
                "smooth": True,
                "areaStyle": {} if spec.chart_type == "trend_area" else None,
                "symbolSize": 7,
            }
            for item in spec.series
        ]
    else:
        base["series"] = [
            {"type": "bar", "name": item["name"], "data": item["values"], "barMaxWidth": 32}
            for item in spec.series
        ]
    return base


def _render(spec: ChartSpec, settings: Settings, destination: Path) -> None:
    if not _FONT_READY:
        configure_fonts()
    if spec.chart_type in GEO_CHART_TYPES:
        _render_geo(spec, settings, destination)
        return
    palette = settings.chart_rules.get("palette", ["#2f6fb5"])
    chart_type = spec.chart_type
    categories = [str(item) for item in spec.categories]

    if chart_type == "structure_donut":
        values = spec.series[0]["values"] if spec.series else []
        figure, axes = plt.subplots(figsize=(7.2, 4.6), dpi=160)
        axes.pie(
            values,
            labels=categories,
            autopct="%1.1f%%",
            colors=palette[: len(values)],
            wedgeprops={"width": 0.42, "edgecolor": "white"},
            textprops={"fontsize": 9},
        )
        axes.set_title(spec.title)
        axes.axis("equal")
    elif chart_type == "matrix_heatmap":
        values = spec.series
        matrix = [item["values"] for item in values]
        figure, axes = plt.subplots(figsize=(max(7.0, 1.1 * len(categories) + 3), 4.6), dpi=160)
        image = axes.imshow(matrix, aspect="auto", cmap="YlOrBr")
        axes.set_xticks(range(len(categories)))
        axes.set_xticklabels(categories, rotation=30, ha="right", fontsize=9)
        axes.set_yticks(range(len(values)))
        axes.set_yticklabels([item["name"] for item in values], fontsize=9)
        for row in range(len(matrix)):
            for column in range(len(matrix[row])):
                axes.text(column, row, f"{matrix[row][column]:,.0f}", ha="center", va="center", fontsize=8)
        axes.set_xlabel(spec.x_label)
        axes.set_ylabel(spec.y_label)
        axes.set_title(spec.title)
        figure.colorbar(image, ax=axes, shrink=0.85)
    elif chart_type == "region_rank_bar":
        values = spec.series[0]["values"] if spec.series else []
        order = sorted(range(len(categories)), key=lambda index: values[index])
        height = max(3.2, 0.36 * len(categories) + 1.6)
        figure, axes = plt.subplots(figsize=(8.6, height), dpi=160)
        axes.barh([categories[index] for index in order], [values[index] for index in order], color=palette[0])
        axes.set_xlabel(f"{spec.y_label}（{spec.unit}）")
        axes.set_ylabel(spec.x_label)
        axes.set_title(spec.title)
        for position, index in enumerate(order):
            axes.text(values[index], position, f" {values[index]:,.0f}", va="center", fontsize=8)
        axes.grid(axis="x", alpha=0.25, linewidth=0.6)
        axes.set_axisbelow(True)
    elif chart_type in {"trend_line", "trend_area"}:
        figure, axes = plt.subplots(figsize=(8.6, 4.0), dpi=160)
        for position, item in enumerate(spec.series):
            color = palette[position % len(palette)]
            axes.plot(categories, item["values"], marker="o", markersize=4, linewidth=1.8, label=item["name"], color=color)
            if chart_type == "trend_area" and len(spec.series) == 1:
                axes.fill_between(categories, item["values"], alpha=0.18, color=color)
        axes.set_xlabel(spec.x_label)
        axes.set_ylabel(f"{spec.y_label}（{spec.unit}）")
        axes.set_title(spec.title)
        axes.grid(alpha=0.25, linewidth=0.6)
        axes.set_axisbelow(True)
        if len(spec.series) > 1:
            axes.legend(fontsize=9)
        if len(categories) > 8:
            for label in axes.get_xticklabels():
                label.set_rotation(30)
                label.set_ha("right")
    else:
        values = spec.series[0]["values"] if spec.series else []
        height = max(3.2, 0.38 * len(categories) + 1.6)
        figure, axes = plt.subplots(figsize=(8.6, height), dpi=160)
        axes.bar(categories, values, color=palette[0])
        axes.set_xlabel(spec.x_label)
        axes.set_ylabel(f"{spec.y_label}（{spec.unit}）")
        axes.set_title(spec.title)
        axes.grid(axis="y", alpha=0.25, linewidth=0.6)
        axes.set_axisbelow(True)
        if len(categories) > 8:
            for label in axes.get_xticklabels():
                label.set_rotation(30)
                label.set_ha("right")

    figure.tight_layout()
    figure.savefig(destination)
    plt.close(figure)


def build_chart(
    analysis: AnalysisResult,
    settings: Settings,
    title: str,
    filename: str,
    output_dir: Path | None = None,
    force_type: str | None = None,
) -> ChartSpec:
    """把分析结果渲染成一张图（静态 PNG + ECharts 配置）。"""
    rule = match_rule(analysis.request.dimensions, settings, _has_geo(analysis, settings))
    chart_type = force_type or rule["result"]

    # 规则或调用方选中空间图型时，转交给地图渲染器
    if chart_type in GEO_CHART_TYPES:
        try:
            return build_geo_chart(
                analysis, settings, title, chart_type, filename, output_dir=output_dir
            )
        except (FileNotFoundError, ValueError):
            # 边界文件缺失或维度不匹配时降级，不影响整条流水线
            chart_type = "region_rank_bar"
            rule = {
                "result": chart_type,
                "label": _TYPE_LABELS[chart_type],
                "why": _TYPE_WHY[chart_type],
            }

    if chart_type == rule["result"]:
        label, why = rule.get("label", chart_type), rule.get("why", "")
    else:
        label = _TYPE_LABELS.get(chart_type, rule.get("label", chart_type))
        why = _TYPE_WHY.get(chart_type, rule.get("why", ""))
    categories, series, metric_label, unit = _extract(analysis, settings)

    dimension_labels = [settings.dimension(name)["label"] for name in analysis.request.dimensions]
    spec = ChartSpec(
        chart_type=chart_type,
        label=label,
        why=why,
        title=title,
        metric=metric_label,
        unit=unit,
        x_label=dimension_labels[0] if dimension_labels else "",
        y_label=metric_label,
        categories=categories,
        series=series,
        analysis=analysis,
    )
    spec.echarts_option = build_echarts_option(spec, settings)

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / f"{filename}.png"
        _render(spec, settings, destination)
        spec.png_path = str(destination)
    return spec


def _has_geo(analysis: AnalysisResult, settings: Settings) -> bool:
    """分析维度里是否有可用的行政区划边界文件。"""
    for name in analysis.request.dimensions:
        spec = settings.dimension(name)
        if spec.get("kind") != "region":
            continue
        if geo_module.geo_available(int(spec.get("level", 0))):
            return True
    return False


def build_geo_chart(
    analysis: AnalysisResult,
    settings: Settings,
    title: str,
    chart_type: str,
    filename: str,
    output_dir: Path | None = None,
) -> ChartSpec:
    """生成空间分布图（分级着色图 / 热力图）。"""
    region_dimensions = [
        name for name in analysis.request.dimensions if settings.dimension(name).get("kind") == "region"
    ]
    if not region_dimensions:
        raise ValueError("空间分布图需要至少一个区域维度，例如「县（区）」或「市（州）」")
    if not analysis.request.metrics:
        raise ValueError("空间分布图需要一个指标，例如「直接经济损失」")

    dimension = settings.dimension(region_dimensions[0])
    level = int(dimension.get("level", 0))
    map_name = geo_module.map_name_for_level(level)
    assets = geo_module.load_geo(map_name) if map_name else None
    if assets is None:
        raise FileNotFoundError(f"缺少 {level} 级行政区划边界文件（data/geo/{map_name}.json）")

    metric_key = analysis.request.metrics[0]
    metric_label = settings.metric(metric_key)["label"]
    unit = settings.metric(metric_key)["unit"]
    name_field = dimension["label"]

    matched = geo_module.match_values(assets, analysis.records, name_field, metric_label)

    if chart_type == "choropleth":
        label = "空间分布类-分级着色图"
        why = "按行政区划边界对指标值分级着色，直观呈现灾情空间聚集特征；灰色为无灾害记录区域"
    else:
        label = "空间分布类-热力图"
        why = "以县级行政中心为点位、按指标值渲染热力强度，突出高值聚集区；无数据区域不显示热力点"

    spec = ChartSpec(
        chart_type=chart_type,
        label=label,
        why=why,
        title=title,
        metric=metric_label,
        unit=unit,
        x_label="经度",
        y_label=metric_label,
        categories=[item["name"] for item in matched["data"]],
        series=[{"name": metric_label, "values": [item["value"] for item in matched["data"]]}],
        analysis=analysis,
    )
    spec.geo = {
        "map": map_name,
        "level": level,
        "min": matched["min"],
        "max": matched["max"],
        "data": matched["data"],
        "matched_count": matched["matched_count"],
        "region_count": len(assets.names),
        "duplicate_names": matched["duplicate_names"],
        "unmatched_records": matched["unmatched_records"],
    }
    if chart_type == "spatial_heatmap":
        points: list[list[float]] = []
        for item in matched["data"]:
            point = assets.centroids.get(item["name"])
            if point:
                points.append([point[0], point[1], item["value"]])
        spec.geo["points"] = points

    spec.echarts_option = build_echarts_option(spec, settings)

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / f"{filename}.png"
        _render(spec, settings, destination)
        spec.png_path = str(destination)
    return spec


def _render_geo(spec: ChartSpec, settings: Settings, destination: Path) -> None:
    """用 matplotlib 直接绘制行政区划多边形，生成离线的静态空间图。"""
    geo = spec.geo
    assets = geo_module.load_geo(geo.get("map", ""))
    if assets is None:
        raise FileNotFoundError("缺少行政区划边界文件")

    palette = _geo_palette(settings)
    cmap = LinearSegmentedColormap.from_list("disaster_geo", palette)
    norm = Normalize(vmin=geo.get("min", 0), vmax=geo.get("max", 1) or 1)
    values = {item["name"]: item["value"] for item in geo.get("data", [])}

    polygons: list[list[tuple[float, float]]] = []
    facecolors: list[Any] = []
    neutral = spec.chart_type == "spatial_heatmap"
    no_data = (0.94, 0.95, 0.96, 1.0)  # 无数据区域的中性底色
    for feature in assets.features:
        name = str((feature.get("properties") or {}).get("name") or "")
        # 热力图只用点位承载数值，底图保持中性，避免重复编码
        if neutral:
            color = (1.0, 1.0, 1.0, 1.0)
        elif name in values:
            color = cmap(norm(values[name]))
        else:
            color = no_data
        for ring in geo_module.iter_polygons(feature.get("geometry")):
            points = [(float(point[0]), float(point[1])) for point in ring if len(point) >= 2]
            if len(points) >= 3:
                polygons.append(points)
                facecolors.append(color)
    if not polygons:
        raise ValueError("行政区划边界文件里没有可绘制的多边形")

    figure, axes = plt.subplots(figsize=(9.2, 7.4), dpi=160)
    if neutral:
        axes.add_collection(
            PolyCollection(polygons, facecolors="#f4f6f9", edgecolors="#c2cad4", linewidths=0.35)
        )
    else:
        axes.add_collection(
            PolyCollection(polygons, facecolors=facecolors, edgecolors="#8c98a6", linewidths=0.35)
        )

    if spec.chart_type == "spatial_heatmap":
        points = geo.get("points") or []
        if points:
            xs = [item[0] for item in points]
            ys = [item[1] for item in points]
            vs = [item[2] for item in points]
            span = (geo.get("max", 1) or 1) - geo.get("min", 0)
            sizes = [
                70 + 900 * ((value - geo.get("min", 0)) / span if span else 0.5) for value in vs
            ]
            axes.scatter(
                xs, ys, s=sizes, c=vs, cmap=cmap, norm=norm, alpha=0.5,
                edgecolors="white", linewidths=0.6, zorder=3,
            )

    # 标注数值最高的前三个区域，便于读数
    top = sorted(geo.get("data", []), key=lambda item: item.get("value") or 0, reverse=True)[:3]
    for item in top:
        point = assets.centroids.get(item["name"])
        if not point:
            continue
        axes.annotate(
            f"{item['name']}\n{item['value']:,.0f}",
            xy=(point[0], point[1]),
            ha="center",
            va="center",
            fontsize=8,
            color="#1b2430",
            zorder=4,
            bbox={"boxstyle": "round,pad=0.18", "facecolor": "white", "alpha": 0.72, "edgecolor": "none"},
        )

    axes.autoscale_view()
    axes.set_aspect("equal", adjustable="box")
    axes.axis("off")
    axes.set_title(spec.title)

    scalar = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    scalar.set_array([])
    bar = figure.colorbar(scalar, ax=axes, shrink=0.6, pad=0.02)
    bar.set_label(f"{spec.y_label}（{spec.unit}）" if spec.unit else spec.y_label)

    figure.tight_layout()
    figure.savefig(destination)
    plt.close(figure)
