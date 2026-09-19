"""流水线编排：把五个模块串成可独立调用、也可一键跑通的状态机。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from . import analytics, charts as chart_module
from .cleaning import clean
from .config import OUTPUT_DIR, Settings
from .ingest import ingest
from .models import AnalysisResult, ChartSpec, CleaningLog, IngestReport
from .plans import section_chart_map, standard_requests
from .report import ReportBuilder, ReportBundle, write_docx, write_markdown, write_pdf


@dataclass
class PipelineResult:
    settings: Settings
    frame: pd.DataFrame
    ingest_report: IngestReport
    cleaning_log: CleaningLog
    analyses: dict[str, AnalysisResult] = field(default_factory=dict)
    charts: dict[str, ChartSpec] = field(default_factory=dict)
    bundle: ReportBundle | None = None
    outputs: dict[str, str] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "原始记录数": self.ingest_report.rows_read,
            "清洗后记录数": self.cleaning_log.rows_out,
            "字段匹配率": f"{round(self.ingest_report.matched_rate * 100, 2)}%",
            "清洗动作数": len(self.cleaning_log.steps),
            "待确认问题数": len(self.cleaning_log.issues),
            "标准分析数": len(self.analyses),
            "生成图表数": len(self.charts),
            "输出文件": self.outputs,
        }


class Pipeline:
    """五模块流水线。每个阶段都可以单独调用，便于前端分步演示。"""

    STAGES = ["ingest", "clean", "analyze", "chart", "report"]

    def __init__(
        self,
        settings: Settings | None = None,
        output_dir: str | Path | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.output_dir = Path(output_dir) if output_dir else Path(OUTPUT_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.stage = "init"
        self.raw: pd.DataFrame | None = None
        self.ingest_report: IngestReport | None = None
        self.frame: pd.DataFrame | None = None
        self.cleaning_log: CleaningLog | None = None
        self.analyses: dict[str, AnalysisResult] = {}
        self.charts: dict[str, ChartSpec] = {}
        self.bundle: ReportBundle | None = None
        self.outputs: dict[str, str] = {}
        self.trace: list[dict[str, Any]] = []

    # ---- 工具方法 ----
    def _require(self, attribute: str, stage: str) -> Any:
        value = getattr(self, attribute)
        if value is None:
            raise RuntimeError(f"请先执行 {stage} 阶段")
        return value

    def _log(self, tool: str, detail: str, payload: dict[str, Any] | None = None) -> None:
        self.trace.append({"tool": tool, "detail": detail, "payload": payload or {}})

    # ---- 1. 接入 ----
    def run_ingest(self, paths: Iterable[str | Path]) -> IngestReport:
        frame, report = ingest(paths, self.settings)
        self.raw = frame
        self.ingest_report = report
        self.stage = "ingest"
        self._log(
            "load_template",
            f"导入 {len(report.files)} 个文件、{len(report.sheets)} 个工作表，共 {report.rows_read} 行",
            {
                "matched": len(report.matched_columns),
                "unmapped": report.unmapped_columns[:8],
                "missing_required": report.missing_required,
            },
        )
        return report

    # ---- 2. 清洗 ----
    def run_clean(self) -> CleaningLog:
        raw = self._require("raw", "ingest")
        frame, log = clean(raw, self.settings)
        self.frame = frame
        self.cleaning_log = log
        self.stage = "clean"
        cleaned_path = self.output_dir / "processed" / "cleaned_records.csv"
        cleaned_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(cleaned_path, index=False, encoding="utf-8-sig")
        self.outputs["cleaned_csv"] = str(cleaned_path)
        self._log(
            "clean_data",
            f"{log.rows_in} 行 -> {log.rows_out} 行，执行 {len(log.steps)} 项清洗动作",
            {"issues": [issue.code for issue in log.issues]},
        )
        return log

    # ---- 3. 分析 ----
    def run_analyze(self) -> dict[str, AnalysisResult]:
        frame = self._require("frame", "clean")
        self.analyses = {}
        for plan, request in standard_requests(self.settings):
            result = analytics.aggregate(frame, request, self.settings)
            result.meta["plan_title"] = plan["title"]
            self.analyses[plan["key"]] = result
        self.stage = "analyze"
        self._log("aggregate_analysis", f"执行 {len(self.analyses)} 个标准分析计划")
        return self.analyses

    def analyze(self, request) -> AnalysisResult:
        """按需执行一个自定义分析计划（智能体问答走这个入口）。"""
        frame = self._require("frame", "clean")
        result = analytics.aggregate(frame, request, self.settings)
        self._log("aggregate_analysis", request.describe(), {"records": len(result.records)})
        return result

    # ---- 4. 图表 ----
    def run_charts(self) -> dict[str, ChartSpec]:
        if not self.analyses:
            raise RuntimeError("请先执行 analyze 阶段")
        chart_dir = self.output_dir / "charts"
        self.charts = {}
        for plan, _ in standard_requests(self.settings):
            analysis = self.analyses.get(plan["key"])
            if analysis is None:
                continue
            try:
                spec = chart_module.build_chart(
                    analysis,
                    self.settings,
                    title=plan["title"],
                    filename=plan["file"],
                    output_dir=chart_dir,
                    force_type=plan.get("chart"),
                )
            except (FileNotFoundError, ValueError) as error:
                spec = chart_module.build_chart(
                    analysis,
                    self.settings,
                    title=plan["title"],
                    filename=plan["file"],
                    output_dir=chart_dir,
                    force_type="region_rank_bar",
                )
                spec.why = f"{spec.why}；缺少行政区划边界文件，本图已降级（{error}）"
                spec.label = "空间分布类-分级排序条形图（降级）"
            self.charts[plan["key"]] = spec
        self.stage = "chart"
        self._log("render_chart", f"生成 {len(self.charts)} 张图表（PNG + ECharts 配置）")
        return self.charts

    def render_chart(self, analysis: AnalysisResult, title: str, filename: str) -> ChartSpec:
        spec = chart_module.build_chart(
            analysis,
            self.settings,
            title=title,
            filename=filename,
            output_dir=self.output_dir / "charts",
        )
        self._log("render_chart", title, {"chart_type": spec.chart_type})
        return spec

    def render_geo_chart(
        self,
        analysis: AnalysisResult,
        title: str,
        chart_type: str = "spatial_heatmap",
        filename: str = "adhoc_geo",
    ) -> ChartSpec:
        """生成空间分布图（热力图或分级着色图）。"""
        spec = chart_module.build_geo_chart(
            analysis,
            self.settings,
            title,
            chart_type,
            filename,
            output_dir=self.output_dir / "charts",
        )
        self._log(
            "render_heatmap",
            title,
            {"chart_type": spec.chart_type, "map": spec.geo.get("map")},
        )
        return spec

    # ---- 5. 报告 ----
    def run_report(self, formats: tuple[str, ...] = ("md", "docx", "pdf")) -> ReportBundle:
        frame = self._require("frame", "clean")
        report = self._require("ingest_report", "ingest")
        log = self._require("cleaning_log", "clean")
        if not self.charts:
            self.run_charts()

        builder = ReportBuilder(self.settings, frame, report, log, self.analyses, self.charts)
        self.bundle = builder.build()
        report_dir = self.output_dir / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = self.bundle.generated_at.replace("-", "").replace(":", "").replace(" ", "_")

        if "md" in formats:
            self.outputs["markdown"] = str(write_markdown(self.bundle, report_dir / f"report_{stamp}.md"))
        if "docx" in formats:
            self.outputs["docx"] = str(write_docx(self.bundle, report_dir / f"report_{stamp}.docx"))
        if "pdf" in formats:
            self.outputs["pdf"] = str(write_pdf(self.bundle, report_dir / f"report_{stamp}.pdf"))
        self.outputs["cleaning_log"] = str(
            write_markdown(
                ReportBundle(
                    title="数据清洗日志",
                    subtitle="记录每一次数据修改及其依据",
                    generated_at=self.bundle.generated_at,
                    meta={"原始记录数": log.rows_in, "清洗后记录数": log.rows_out},
                    sections=[builder._section_data_quality()],
                ),
                report_dir / f"cleaning_log_{stamp}.md",
            )
        )
        self.stage = "report"
        self._log("write_report", f"生成报告：{', '.join(sorted(self.outputs))}")
        return self.bundle

    # ---- 一键跑通 ----
    def run(self, paths: Iterable[str | Path], formats: tuple[str, ...] = ("md", "docx", "pdf")) -> PipelineResult:
        self.run_ingest(paths)
        self.run_clean()
        self.run_analyze()
        self.run_charts()
        self.run_report(formats)
        assert self.frame is not None
        return PipelineResult(
            settings=self.settings,
            frame=self.frame,
            ingest_report=self.ingest_report or IngestReport(),
            cleaning_log=self.cleaning_log or CleaningLog(),
            analyses=self.analyses,
            charts=self.charts,
            bundle=self.bundle,
            outputs=self.outputs,
        )

    def chart_sections(self) -> dict[str, list[str]]:
        return section_chart_map()
