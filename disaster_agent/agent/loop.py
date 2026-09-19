"""智能体主循环：状态机 + 工具调用 + 结果校验。"""

from __future__ import annotations

from typing import Any, Iterable

from ..analytics import dimension_catalog, filter_hints, metric_catalog
from ..models import AnalysisRequest
from ..pipeline import Pipeline
from .llm import get_llm
from .tools import ToolBox

STATE_FLOW = ["idle", "loaded", "profiled", "cleaned", "analyzed", "charted", "reported"]


class DisasterAgent:
    """灾情分析智能体。

    - run()  ：按状态机一次跑通全部模块，演示「自动化」
    - ask()  ：自然语言问答，演示「意图理解 -> 规划 -> 调工具 -> 校验」
    """

    def __init__(self, pipeline: Pipeline | None = None, model_mode: str = "auto") -> None:
        self.pipeline = pipeline or Pipeline()
        self.llm = get_llm(model_mode)
        self.toolbox = ToolBox(self.pipeline)
        self.state = "idle"
        self.trace: list[dict[str, Any]] = []

    # ---- 状态机 ----
    def _advance(self, state: str, detail: str) -> None:
        self.state = state
        self.trace.append({"state": state, "detail": detail})

    def run(self, paths: Iterable[str], formats: tuple[str, ...] = ("md", "docx", "pdf")):
        """一键跑通：接入 -> 体检 -> 清洗 -> 分析 -> 出图 -> 报告。"""
        self.trace = []

        report = self.toolbox.load_template(paths)
        self._advance(
            "loaded",
            f"识别 {len(report['matched_columns'])} 个标准字段，未识别 {len(report['unmapped_columns'])} 列",
        )

        profile = self.toolbox.profile_data()
        self._advance("profiled", f"体检 {profile['rows']} 行动数据，字段 {profile['columns']} 个")

        cleaning = self.toolbox.clean_data()
        self._advance(
            "cleaned",
            f"{cleaning['rows_in']} -> {cleaning['rows_out']} 行，{len(cleaning['steps'])} 项清洗动作",
        )
        self._validate_cleaning(cleaning)

        analyses = self.pipeline.run_analyze()
        self._advance("analyzed", f"完成 {len(analyses)} 个标准分析计划")
        self._validate_analysis(analyses)

        charts = self.pipeline.run_charts()
        self._advance(
            "charted", "生成图表：" + "、".join(spec.label for spec in charts.values())
        )

        self.toolbox.write_report(list(formats))
        self._advance("reported", f"输出 {len(self.pipeline.outputs)} 个文件")
        return self.pipeline

    # ---- 结果校验 ----
    def _validate_cleaning(self, cleaning: dict[str, Any]) -> None:
        if cleaning["rows_out"] == 0:
            raise RuntimeError("校验失败：清洗后没有可用记录，请检查模板字段是否匹配")
        if cleaning["rows_out"] > cleaning["rows_in"]:
            raise RuntimeError("校验失败：清洗后记录数多于原始记录数")
        self.trace.append({"state": "cleaned", "detail": "校验通过：记录数单调收敛"})

    def _validate_analysis(self, analyses: dict[str, Any]) -> None:
        empty = [key for key, result in analyses.items() if not result.records]
        negative = [
            key
            for key, result in analyses.items()
            if any(float(value or 0) < 0 for value in result.totals.values())
        ]
        if negative:
            raise RuntimeError(f"校验失败：以下分析出现负值 {negative}")
        self.trace.append(
            {
                "state": "analyzed",
                "detail": f"校验通过：{len(analyses) - len(empty)} 个分析有结果，空结果 {len(empty)} 个",
            }
        )

    # ---- 自然语言问答 ----
    def ask(self, question: str) -> dict[str, Any]:
        frame = self.pipeline.frame
        if frame is None:
            return {"question": question, "answer": "尚未导入数据，请先上传灾情数据文件。", "plan": None}

        context = {
            "dimensions": dimension_catalog(self.pipeline.settings),
            "metrics": metric_catalog(self.pipeline.settings),
            "filter_hints": filter_hints(frame, self.pipeline.settings),
        }
        plan = self.llm.plan(question, context)
        dimensions = [item for item in plan.get("dimensions", []) if item in self.pipeline.settings.dimensions]
        metrics = [item for item in plan.get("metrics", []) if item in self.pipeline.settings.metrics]
        if not dimensions:
            dimensions = ["time_year"]
        if not metrics:
            metrics = ["direct_economic_loss"]

        request = AnalysisRequest(
            dimensions=dimensions[:2],
            metrics=metrics[:2],
            filters=plan.get("filters", {}) or {},
            limit=30,
        )
        analysis = self.pipeline.analyze(request)
        chart = self._render_answer_chart(question, analysis)

        facts = {
            "分析计划": request.describe(),
            "明细记录": analysis.records[:12],
            "合计": analysis.totals,
            "指标单位": {
                self.pipeline.settings.metric(name)["label"]: self.pipeline.settings.metric(name)["unit"]
                for name in request.metrics
            },
            "已忽略的筛选条件": analysis.meta.get("已忽略筛选", []),
        }
        answer = self.llm.answer(question, facts) or self._template_answer(question, analysis, chart)
        ignored = analysis.meta.get("已忽略筛选", [])
        if ignored:
            answer = "（筛选条件 " + "、".join(ignored) + " 在数据中匹配不到，已忽略该条件作答）\n" + answer
        return {
            "question": question,
            "model": self.llm.name,
            "plan": request.to_dict(),
            "reasoning": plan.get("reasoning", ""),
            "answer": answer,
            "analysis": analysis.to_dict(),
            "chart": chart.to_dict(),
            "trace": self.trace,
        }

    def _render_answer_chart(self, question: str, analysis):
        """按问题里的措辞选择图型：提到热力图/地图时优先出空间分布图。"""
        title = question[:28] or "智能问答图表"
        wants_heatmap = "热力" in question
        wants_map = any(word in question for word in ("分布图", "地图", "空间分布"))
        if wants_heatmap or wants_map:
            chart_type = "spatial_heatmap" if wants_heatmap else "choropleth"
            try:
                return self.pipeline.render_geo_chart(
                    analysis, title=title, chart_type=chart_type, filename="adhoc_query"
                )
            except (FileNotFoundError, ValueError):
                pass
        return self.pipeline.render_chart(analysis, title=title, filename="adhoc_query")

    @staticmethod
    def _template_answer(question: str, analysis, chart) -> str:
        if not analysis.records:
            return "当前筛选条件下没有检索到记录，请调整灾种、区域或时间条件后重试。"
        columns = analysis.meta.get("columns", [])
        label = columns[0]["key"] if columns else "对象"
        metric_label = columns[-1]["key"] if columns else "数值"
        unit = columns[-1].get("unit", "") if columns else ""
        top = sorted(analysis.records, key=lambda item: item.get(metric_label) or 0, reverse=True)[:3]
        detail = "、".join(
            f"{item.get(label)}为 {item.get(metric_label):,.2f}{unit}"
            for item in top
            if item.get(metric_label) is not None
        )
        total = analysis.totals.get(metric_label)
        total_text = f"，合计 {total:,.2f}{unit}" if total is not None else ""
        return (
            f"按「{analysis.request.describe()}」计算{total_text}。"
            f"排名前三的对象为：{detail}。该结果已自动匹配为{chart.label}呈现。"
        )
