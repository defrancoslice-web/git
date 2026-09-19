"""本地 Web 界面：上传 -> 清洗 -> 分析 -> 出图 -> 报告，全程可视化。"""

from __future__ import annotations

import base64
import json
import mimetypes
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import __release__, __version__
from .. import geo as geo_module
from ..agent import DisasterAgent
from ..analytics import dimension_catalog, metric_catalog
from ..config import DATA_DIR, OUTPUT_DIR, Settings
from ..pipeline import Pipeline
from ..sample_data import generate

STATIC_DIR = Path(__file__).resolve().parent / "static"
UPLOAD_DIR = DATA_DIR / "uploads"


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """独占端口。

    HTTPServer 默认开启 SO_REUSEADDR，Windows 下会允许多个进程绑定同一端口，
    结果是新旧实例同时监听、请求被随机分发，出现「明明启动成功却读不到数据」的怪现象。
    这里关闭该选项，让第二个实例明确报端口占用。
    """

    allow_reuse_address = False
    daemon_threads = True


class Session:
    """一次演示会话的状态。"""

    def __init__(
        self,
        output_dir: str | Path | None = None,
        settings: Settings | None = None,
    ) -> None:
        # settings 必须由外部传入或在此创建：run_pipeline 需要它构造 Pipeline
        self.settings = settings or Settings()
        self.output_dir = Path(output_dir) if output_dir else Path(OUTPUT_DIR)
        self.files: list[str] = []
        self.agent: DisasterAgent | None = None
        self.pipeline: Pipeline | None = None
        self.last_error: str | None = None

    def sample_files(self) -> list[str]:
        files = sorted((DATA_DIR / "sample").glob("*.xlsx"))
        if not files:
            files = generate()
        return [str(path) for path in files]

    def reset(self) -> None:
        self.agent = None
        self.pipeline = None
        self.last_error = None

    def run_pipeline(self) -> None:
        """加载数据并跑通全流程。供 /api/run 与启动预分析共用。"""
        if not self.files:
            self.files = self.sample_files()
        self.reset()
        pipeline = Pipeline(self.settings, output_dir=self.output_dir)
        agent = DisasterAgent(pipeline, model_mode="auto")
        agent.run(self.files, formats=("md", "docx", "pdf"))
        self.pipeline = pipeline
        self.agent = agent


class Handler(BaseHTTPRequestHandler):
    session: Session
    settings = Settings()
    server_version = "DisasterAgent/0.1"

    # ---- 基础 ----
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        print(f"[web] {format % args}")

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _safe_output_path(self, raw: str) -> Path | None:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = Path(self.session.output_dir) / raw
        try:
            candidate = candidate.resolve()
            base = Path(self.session.output_dir).resolve()
        except OSError:
            return None
        if base not in candidate.parents and candidate != base:
            return None
        return candidate

    # ---- 路由 ----
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        if route in {"/", "/index.html"}:
            return self._serve_static("index.html")
        if route.startswith("/static/"):
            return self._serve_static(route[len("/static/") :])
        if route == "/api/schema":
            return self._json(
                {
                    "dimensions": dimension_catalog(self.settings),
                    "metrics": metric_catalog(self.settings),
                    "fields": self.settings.field_names,
                    "custom_dimensions": self.settings.custom_dimensions,
                    "chart_rules": self.settings.chart_rules["rules"],
                    "report_outline": self.settings.outline["sections"],
                }
            )
        if route == "/api/state":
            return self._json(self._state())
        if route == "/api/geo":
            name = (query.get("name") or [""])[0]
            path = geo_module.geo_path(name)
            if not path.exists() or path.parent.resolve() != geo_module.GEO_DIR.resolve():
                return self._json({"error": "地图文件不存在"}, status=404)
            return self._send(200, path.read_bytes(), "application/json; charset=utf-8")
        if route in {"/api/file", "/api/download"}:
            raw = (query.get("path") or [""])[0]
            target = self._safe_output_path(raw)
            if target is None or not target.exists():
                return self._json({"error": "文件不存在或路径越界"}, status=404)
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            extra = None
            if route == "/api/download":
                extra = {"Content-Disposition": f'attachment; filename="{target.name.encode("utf-8").decode("latin-1", "ignore")}"'}
            return self._send(200, target.read_bytes(), content_type, extra)
        return self._json({"error": "未知路由"}, status=404)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        try:
            if route == "/api/seed":
                self.session.files = self.session.sample_files()
                self.session.reset()
                return self._json({"files": [Path(item).name for item in self.session.files], "state": self._state()})
            if route == "/api/upload":
                payload = self._read_json()
                UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                saved: list[str] = []
                for item in payload.get("files", []):
                    name = Path(item.get("name", "upload.xlsx")).name
                    target = UPLOAD_DIR / name
                    target.write_bytes(base64.b64decode(item.get("content", "")))
                    saved.append(str(target))
                self.session.files = sorted(saved)
                self.session.reset()
                return self._json({"files": [Path(item).name for item in self.session.files]})
            if route == "/api/run":
                return self._run()
            if route == "/api/ask":
                payload = self._read_json()
                if not self.session.agent or not self.session.pipeline or self.session.pipeline.frame is None:
                    return self._json({"error": "请先执行一次「一键分析」"}, status=400)
                result = self.session.agent.ask(str(payload.get("question", "")).strip())
                return self._json(result)
            if route == "/api/analyze":
                payload = self._read_json()
                agent = self.session.agent
                if not agent or not self.session.pipeline or self.session.pipeline.frame is None:
                    return self._json({"error": "请先执行一次「一键分析」"}, status=400)
                dimensions = [item for item in payload.get("dimensions", []) if item]
                metrics = [item for item in payload.get("metrics", []) if item]
                if not dimensions:
                    return self._json({"error": "请至少选择一个分析维度"}, status=400)
                title = str(payload.get("title") or "自定义分析")
                chart = agent.toolbox.render_chart(dimensions, metrics, title=title, filename="adhoc_custom")
                return self._json({"chart": chart.to_dict()})
        except Exception as error:  # pragma: no cover - 演示期兜底
            self.session.last_error = f"{type(error).__name__}: {error}"
            traceback.print_exc()
            return self._json({"error": self.session.last_error, "trace": traceback.format_exc()[-2000:]}, status=500)
        return self._json({"error": "未知路由"}, status=404)

    # ---- 具体动作 ----
    def _serve_static(self, name: str) -> None:
        target = (STATIC_DIR / name).resolve()
        if STATIC_DIR.resolve() not in target.parents or not target.exists():
            return self._json({"error": "资源不存在"}, status=404)
        content_type = mimetypes.guess_type(target.name)[0] or "text/plain"
        if target.suffix in {".html", ".css", ".js"}:
            content_type += "; charset=utf-8"
        self._send(200, target.read_bytes(), content_type)

    def _run(self) -> None:
        self.session.run_pipeline()
        assert self.session.agent is not None
        self._json({"state": self._state(), "trace": self.session.agent.trace})

    def _state(self) -> dict:
        pipeline = self.session.pipeline
        if not pipeline:
            return {
                "files": [Path(item).name for item in self.session.files],
                "analyses": [],
                "charts": [],
                "outputs": {},
                "stages": {stage: "pending" for stage in Pipeline.STAGES},
                "summary": {},
                "error": self.session.last_error,
            }
        assert pipeline.ingest_report is not None
        assert pipeline.cleaning_log is not None
        reached = Pipeline.STAGES.index(pipeline.stage) if pipeline.stage in Pipeline.STAGES else -1
        stages = {
            stage: ("done" if index <= reached else "pending")
            for index, stage in enumerate(Pipeline.STAGES)
        }
        return {
            "files": [Path(item).name for item in self.session.files],
            "stages": stages,
            "ingest": pipeline.ingest_report.to_dict(),
            "cleaning": pipeline.cleaning_log.to_dict(),
            "analyses": [
                {
                    "key": key,
                    "title": result.meta.get("plan_title", key),
                    "description": result.request.describe(),
                    "totals": result.totals,
                    "records": result.records[:20],
                    "record_count": len(result.records),
                }
                for key, result in pipeline.analyses.items()
            ],
            "charts": [spec.to_dict() for spec in pipeline.charts.values()],
            "outputs": {
                key: Path(value).name for key, value in pipeline.outputs.items()
            },
            "output_paths": pipeline.outputs,
            "report": pipeline.bundle.to_dict() if pipeline.bundle else None,
            "summary": {},
            "error": self.session.last_error,
        }


def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    output_dir: str | Path | None = None,
    autorun: bool = False,
) -> None:
    session = Session(output_dir, settings=Handler.settings)

    # 预分析：先把示例数据跑完再开始监听，这样页面一打开就是完整结果，
    # 演示时不必当着评委的面点按钮。
    if autorun:
        print("正在预加载示例数据并执行一次完整分析……")
        try:
            session.run_pipeline()
            print("预分析完成。")
        except Exception as error:  # pragma: no cover - 演示期兜底
            print(f"预分析失败（不影响平台启动）：{type(error).__name__}: {error}")

    Handler.session = session
    try:
        httpd = ExclusiveThreadingHTTPServer((host, port), Handler)
    except OSError as error:
        print(f"[错误] 无法监听端口 {port}：{error}")
        print("可能已有平台实例在运行。请先停止，或改用其它端口：--port 8001")
        raise SystemExit(3)
    print("=" * 60)
    print(f"  灾情分析平台 {__release__}（{__version__}）")
    print("=" * 60)
    print(f"  界面地址：http://{host}:{port}")
    print("  提示：先点「加载示例数据」，再点「一键分析」")
    print("  按 Ctrl+C 结束")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
