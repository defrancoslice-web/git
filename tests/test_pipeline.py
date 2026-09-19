"""端到端自检。有 pytest 用 pytest 跑，没有就直接 python tests/test_pipeline.py。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from disaster_agent.agent import DisasterAgent  # noqa: E402
from disaster_agent.analytics import aggregate, label_map  # noqa: E402
from disaster_agent.charts import match_rule  # noqa: E402
from disaster_agent.cleaning import parse_quantity  # noqa: E402
from disaster_agent.config import Settings  # noqa: E402
from disaster_agent.geo import list_maps, load_geo  # noqa: E402
from disaster_agent.models import AnalysisRequest  # noqa: E402
from disaster_agent.pipeline import Pipeline  # noqa: E402
from disaster_agent.sample_data import generate  # noqa: E402

_CACHE: dict = {}


def _fixture():
    """生成一次小规模数据并跑通流水线，供多个用例复用。"""
    if _CACHE:
        return _CACHE
    workdir = Path(__file__).resolve().parent / "_workdir"
    workdir.mkdir(parents=True, exist_ok=True)
    paths = generate(out_dir=workdir / "sample", total=160)
    settings = Settings()
    pipeline = Pipeline(settings, output_dir=workdir / "output")
    agent = DisasterAgent(pipeline, model_mode="mock")
    agent.run([str(path) for path in paths], formats=("md", "docx", "pdf"))
    _CACHE.update({"workdir": workdir, "paths": paths, "settings": settings, "pipeline": pipeline, "agent": agent})
    return _CACHE


def test_quantity_parsing():
    assert parse_quantity("3.2亿元", {"亿元": 10000.0})[0] == 3.2
    assert parse_quantity("1,234人", {"人": 1.0})[0] == 1234
    assert parse_quantity("-", {"人": 1.0})[0] is None
    assert parse_quantity(12.5)[0] == 12.5


def test_chart_rule_selection():
    settings = _fixture()["settings"]
    assert match_rule(["time_year"], settings)["result"] == "trend_area"
    assert match_rule(["time_year", "disaster_type"], settings)["result"] == "trend_line"
    assert match_rule(["loss_structure"], settings)["result"] == "structure_donut"
    assert match_rule(["region_county"], settings)["result"] == "region_rank_bar"
    assert (
        match_rule(["region_county"], settings, geo_available=True)["result"] == "choropleth"
    ), "有行政区划边界文件时应优先使用分级着色图"
    assert match_rule(["disaster_type", "emergency_level"], settings)["result"] == "matrix_heatmap"


def test_geo_maps_installed():
    maps = {item["name"]: item for item in list_maps()}
    assert maps["sichuan_county"]["installed"], "缺少县级行政区划边界文件"
    assets = load_geo("sichuan_county")
    assert assets is not None
    assert len(assets.names) > 150, f"县级要素偏少：{len(assets.names)}"
    assert assets.centroids, "缺少区域中心点坐标，热力图无法定位"


def test_spatial_charts_generated():
    data = _fixture()
    charts = data["pipeline"].charts
    for key, expected in (("county_choropleth", "choropleth"), ("county_heatmap", "spatial_heatmap")):
        spec = charts.get(key)
        assert spec is not None, f"缺少图表 {key}"
        assert spec.chart_type == expected, f"{key} 图型不符：{spec.chart_type}"
        assert spec.png_path and Path(spec.png_path).exists(), f"{key} 未生成静态图"
        assert spec.geo.get("matched_count", 0) > 50, f"{key} 匹配到的区域过少"


def test_ingest_and_clean():
    data = _fixture()
    pipeline = data["pipeline"]
    report = pipeline.ingest_report
    log = pipeline.cleaning_log
    assert report is not None and log is not None
    assert report.matched_rate > 0.7, "字段匹配率过低，模板映射需要检查"
    assert not report.missing_required, f"缺少必需字段：{report.missing_required}"
    assert 0 < log.rows_out <= log.rows_in
    assert len(log.steps) >= 5, "清洗动作过少"

    frame = pipeline.frame
    assert frame is not None
    for name in ["direct_economic_loss", "affected_population"]:
        assert (frame[name] >= 0).all(), f"{name} 清洗后仍存在负值"
        assert frame[name].notna().all(), f"{name} 清洗后仍存在缺失"


def test_all_standard_plans_run():
    data = _fixture()
    analyses = data["pipeline"].analyses
    assert len(analyses) == 10, "标准分析计划数量不符"
    for key, result in analyses.items():
        assert result.records, f"{key} 没有产出任何分组记录"
        for value in result.totals.values():
            assert float(value) >= 0, f"{key} 出现负的合计值"


def test_custom_dimensions_available():
    data = _fixture()
    settings = data["settings"]
    custom = settings.custom_dimensions
    assert len(custom) >= 2, "赛项要求至少 2 个自定义分析维度"
    frame = data["pipeline"].frame
    for name in custom:
        request = AnalysisRequest(
            dimensions=[name], metrics=["direct_economic_loss"], labels=label_map(settings)
        )
        result = aggregate(frame, request, settings)
        assert result.records, f"自定义维度 {name} 无法聚合"


def test_report_outputs():
    data = _fixture()
    outputs = data["pipeline"].outputs
    for key in ["markdown", "docx", "pdf", "cleaning_log", "cleaned_csv"]:
        assert key in outputs, f"缺少输出：{key}"
        path = Path(outputs[key])
        assert path.exists() and path.stat().st_size > 1000, f"{key} 输出文件异常"


def test_agent_ask():
    data = _fixture()
    result = data["agent"].ask("近三年洪涝灾害直接经济损失趋势")
    assert result["plan"]["description"]
    assert result["analysis"]["records"], "问答未产出分析结果"
    assert result["answer"] and len(result["answer"]) > 10
    assert result["chart"]["chart_type"] in {"trend_area", "trend_line"}
    assert "洪涝" in result["plan"]["description"], "灾种筛选未生效"


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as error:
            failed += 1
            print(f"FAIL  {test.__name__}: {error}")
        except Exception as error:  # pragma: no cover
            failed += 1
            print(f"ERROR {test.__name__}: {type(error).__name__}: {error}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
