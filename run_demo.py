"""一键演示脚本：生成模拟数据 -> 跑通全流程 -> 打印摘要。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from disaster_agent.agent import DisasterAgent  # noqa: E402
from disaster_agent.sample_data import generate  # noqa: E402


def main() -> int:
    print("=" * 68)
    print("自然灾害灾情数据自动化综合分析辅助决策支撑平台 —— 原型演示")
    print("=" * 68)
    paths = generate()
    print("\n[1/2] 已生成模拟数据：")
    for path in paths:
        print("      ", path)

    agent = DisasterAgent(model_mode="mock")
    agent.run([str(path) for path in paths], formats=("md", "docx", "pdf"))

    print("\n[2/2] 智能体执行轨迹：")
    for item in agent.trace:
        print(f"       [{item['state']}] {item['detail']}")

    print("\n输出文件：")
    for key, value in agent.pipeline.outputs.items():
        print(f"       {key:<14} {value}")

    print("\n用自然语言问答试试：")
    result = agent.ask("近五年洪涝灾害直接经济损失趋势")
    print("       " + result["answer"][:160] + "……")

    print("\n下一步：")
    print("       python -m disaster_agent.cli serve       # 打开可视化界面")
    print("       把组委会的模板放进 data/sample/ 后重跑即可")
    return 0


if __name__ == "__main__":
    sys.exit(main())

