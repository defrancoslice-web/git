"""标准分析计划库：一次跑通就是赛项要求的全部固定维度加自定义维度。"""

from __future__ import annotations

from typing import Any

from .config import Settings
from .models import AnalysisRequest

STANDARD_PLANS: list[dict[str, Any]] = [
    {
        "key": "by_disaster_type",
        "title": "分灾种直接经济损失",
        "dimensions": ["disaster_type"],
        "metrics": ["direct_economic_loss"],
        "section": "by_disaster_type",
        "file": "01_by_disaster_type",
    },
    {
        "key": "yearly_trend",
        "title": "年度直接经济损失趋势",
        "dimensions": ["time_year"],
        "metrics": ["direct_economic_loss"],
        "section": "spatiotemporal",
        "file": "02_yearly_trend",
    },
    {
        "key": "yearly_trend_by_type",
        "title": "分灾种年度损失趋势",
        "dimensions": ["time_year", "disaster_type"],
        "metrics": ["direct_economic_loss"],
        "section": "spatiotemporal",
        "file": "03_yearly_trend_by_type",
        "limit": 100,
    },
    {
        "key": "county_ranking",
        "title": "分县（区）直接经济损失",
        "dimensions": ["region_county"],
        "metrics": ["direct_economic_loss"],
        "section": "spatiotemporal",
        "file": "04_county_ranking",
        "limit": 20,
        "chart": "region_rank_bar",
    },
    {
        "key": "loss_structure",
        "title": "损失结构构成",
        "dimensions": ["loss_structure"],
        "metrics": [],
        "section": "loss_structure",
        "file": "05_loss_structure",
    },
    {
        "key": "county_choropleth",
        "title": "分县（区）直接经济损失空间分布",
        "dimensions": ["region_county"],
        "metrics": ["direct_economic_loss"],
        "section": "spatiotemporal",
        "file": "09_county_choropleth",
        "chart": "choropleth",
        "limit": 200,
    },
    {
        "key": "county_heatmap",
        "title": "分县（区）直接经济损失热力图",
        "dimensions": ["region_county"],
        "metrics": ["direct_economic_loss"],
        "section": "spatiotemporal",
        "file": "10_county_heatmap",
        "chart": "spatial_heatmap",
        "limit": 200,
    },
    {
        "key": "by_season",
        "title": "汛期与非汛期损失对比（自定义维度）",
        "dimensions": ["custom_season"],
        "metrics": ["direct_economic_loss", "affected_population"],
        "section": "loss_structure",
        "file": "06_season_compare",
    },
    {
        "key": "per_capita_level",
        "title": "分档人均损失分布（自定义维度）",
        "dimensions": ["custom_per_capita"],
        "metrics": ["direct_economic_loss"],
        "section": "loss_structure",
        "file": "07_per_capita_level",
    },
    {
        "key": "type_level_matrix",
        "title": "灾种 × 灾情等级损失矩阵（自定义图表）",
        "dimensions": ["disaster_type", "emergency_level"],
        "metrics": ["direct_economic_loss"],
        "section": "by_disaster_type",
        "file": "08_type_level_matrix",
        "limit": 100,
    },
]


def standard_requests(settings: Settings) -> list[tuple[dict[str, Any], AnalysisRequest]]:
    """返回 (计划元信息, 分析请求) 列表。"""
    result: list[tuple[dict[str, Any], AnalysisRequest]] = []
    for plan in STANDARD_PLANS:
        request = AnalysisRequest(
            dimensions=list(plan["dimensions"]),
            metrics=list(plan["metrics"]),
            limit=plan.get("limit", 40),
        )
        result.append((plan, request))
    return result


def section_chart_map() -> dict[str, list[str]]:
    """报告章节 -> 需要嵌入的图表 key。"""
    mapping: dict[str, list[str]] = {}
    for plan in STANDARD_PLANS:
        mapping.setdefault(plan["section"], []).append(plan["key"])
    return mapping
