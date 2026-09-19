"""命令行入口。

    python -m disaster_agent.cli seed                 生成模拟数据
    python -m disaster_agent.cli run                  一键跑通全流程
    python -m disaster_agent.cli ask "近三年洪涝损失趋势"   自然语言问答
    python -m disaster_agent.cli serve                启动本地可视化界面
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __release__, __version__
from .analytics import dimension_catalog, metric_catalog
from .config import DATA_DIR, Settings
from .pipeline import Pipeline
from .sample_data import generate


def _default_inputs() -> list[str]:
    sample_dir = DATA_DIR / "sample"
    files = sorted(sample_dir.glob("*.xlsx")) if sample_dir.exists() else []
    if not files:
        print("未找到示例数据，正在自动生成……")
        files = generate()
    return [str(path) for path in files]


def command_seed(args: argparse.Namespace) -> int:
    for path in generate(out_dir=args.out_dir, seed=args.seed, total=args.total):
        print(f"已生成：{path}")
    return 0


def command_run(args: argparse.Namespace) -> int:
    paths = args.input or _default_inputs()
    pipeline = Pipeline(output_dir=args.output)
    agent_used = args.agent
    formats = tuple(item.strip() for item in args.formats.split(",") if item.strip())

    if agent_used:
        from .agent import DisasterAgent

        agent = DisasterAgent(pipeline, model_mode=args.model)
        agent.run(paths, formats=formats)
        print("\n智能体执行轨迹：")
        for item in agent.trace:
            print(f"  [{item['state']}] {item['detail']}")
    else:
        pipeline.run(paths, formats=formats)

    print("\n处理摘要：")
    for key, value in pipeline.outputs.items():
        print(f"  {key}: {value}")

    print("\n清洗日志摘要：")
    assert pipeline.cleaning_log is not None
    for step in pipeline.cleaning_log.steps:
        print(f"  {step.step:<8} {step.field:<28} {step.action:<32} 影响 {step.affected} 条")
    for issue in pipeline.cleaning_log.issues:
        print(f"  [待确认] {issue.code}: {issue.message}（{issue.count} 条）")
    return 0


def command_ask(args: argparse.Namespace) -> int:
    from .agent import DisasterAgent

    paths = args.input or _default_inputs()
    pipeline = Pipeline(output_dir=args.output)
    agent = DisasterAgent(pipeline, model_mode=args.model)
    agent.run(paths, formats=("md",))
    result = agent.ask(args.question)
    print("\n问题：", result["question"])
    print("规划：", json.dumps(result.get("plan", {}), ensure_ascii=False, indent=2))
    print("回答：", result.get("answer", ""))
    if result.get("chart"):
        print("图表：", result["chart"].get("png_path"))
    return 0


def command_serve(args: argparse.Namespace) -> int:
    from .web.server import serve

    serve(host=args.host, port=args.port, output_dir=args.output, autorun=args.autorun)
    return 0


def command_catalog(args: argparse.Namespace) -> int:
    settings = Settings()
    from .geo import list_maps

    print("行政区划边界文件：")
    for item in list_maps():
        mark = "已安装" if item["installed"] else "缺失"
        print(f"  {item['name']:<16} {item['level']} 级  {mark}  {item['size_kb']} KB")
    print()
    print("可用维度：")
    for item in dimension_catalog(settings):
        flag = "（自定义）" if item["custom"] else ""
        print(f"  {item['name']:<20} {item['label']}{flag}")
    print("\n可用指标：")
    for item in metric_catalog(settings):
        print(f"  {item['name']:<24} {item['label']} ({item['unit']})")
    return 0


def command_llm_setup(args: argparse.Namespace) -> int:
    """交互式写入密钥。用 getpass 读取，密钥不进入命令历史、不回显。"""
    from getpass import getpass

    from .agent.llm import DEFAULT_BASE_URL, DEFAULT_MODEL, save_local_config

    print("配置大模型接入（密钥输入时不显示，也不会写入命令历史）\n")
    base_url = args.base_url or input(f"接口地址 [{DEFAULT_BASE_URL}]: ").strip() or DEFAULT_BASE_URL
    model = args.model or input(f"模型名 [{DEFAULT_MODEL}]: ").strip() or DEFAULT_MODEL
    api_key = getpass("API 密钥（输入时不显示）: ").strip()
    if not api_key:
        print("未输入密钥，已取消。")
        return 1

    path = save_local_config(api_key, base_url, model)
    print(f"\n已写入：{path}")
    print("该文件已加入 .gitignore，不会进入分发包。")
    print("接下来运行  python -m disaster_agent.cli llm-check  验证连通性。")
    return 0


def command_llm_check(args: argparse.Namespace) -> int:
    from .agent.llm import config_status, get_llm

    status = config_status()
    print("模型配置：")
    for key, value in status.items():
        print(f"  {key}: {value}")

    if not status["已配置"]:
        print("\n尚未配置密钥。两种方式：")
        print("  1) python -m disaster_agent.cli llm-setup")
        print("  2) 复制 config/llm.config.example.json 为 config/llm.local.json 并填写")
        return 1

    llm = get_llm("openai")
    print(f"\n正在测试连通性（{status['模型']}）...")
    try:
        reply = llm.ping()
    except Exception as error:
        print(f"连接失败：{type(error).__name__}: {error}")
        print("\n请依次检查：接口地址是否正确、密钥是否有效、模型名是否存在、本机能否访问该服务。")
        return 2
    print(f"连通正常，模型回复：{reply}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="disaster_agent", description="自然灾害灾情数据自动化综合分析辅助决策支撑平台（原型）"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"灾情分析平台 {__release__}（{__version__}）",
    )
    parser.add_argument("--output", default=None, help="输出目录，默认 output/")
    parser.add_argument("--model", default="auto", choices=["auto", "mock", "openai"], help="大模型模式")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed = subparsers.add_parser("seed", help="生成模拟灾情数据")
    seed.add_argument("--out-dir", default=None)
    seed.add_argument("--seed", type=int, default=20260916)
    seed.add_argument("--total", type=int, default=480)
    seed.set_defaults(func=command_seed)

    run = subparsers.add_parser("run", help="一键跑通全流程")
    run.add_argument("--input", nargs="*", help="灾情数据文件，可多个")
    run.add_argument("--formats", default="md,docx,pdf")
    run.add_argument("--agent", action="store_true", help="以智能体状态机方式执行并打印轨迹")
    run.set_defaults(func=command_run)

    ask = subparsers.add_parser("ask", help="自然语言问答")
    ask.add_argument("question")
    ask.add_argument("--input", nargs="*", help="灾情数据文件，可多个")
    ask.set_defaults(func=command_ask)

    serve_parser = subparsers.add_parser("serve", help="启动本地可视化界面")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument(
        "--autorun", action="store_true", help="启动前先跑一次完整分析，页面打开即为结果"
    )
    serve_parser.set_defaults(func=command_serve)

    catalog = subparsers.add_parser("catalog", help="查看可用维度与指标")
    catalog.set_defaults(func=command_catalog)

    llm_check = subparsers.add_parser("llm-check", help="检查大模型配置并测试连通性")
    llm_check.set_defaults(func=command_llm_check)

    llm_setup = subparsers.add_parser("llm-setup", help="交互式配置大模型密钥")
    llm_setup.add_argument("--base-url", default=None, help="接口地址，留空则交互输入")
    llm_setup.add_argument("--model", default=None, help="模型名，留空则交互输入")
    llm_setup.set_defaults(func=command_llm_setup)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
