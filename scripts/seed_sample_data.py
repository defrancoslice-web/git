"""生成模拟灾情数据（批量上传演示用）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from disaster_agent.sample_data import generate  # noqa: E402


def main() -> None:
    for path in generate():
        print(f"已生成：{path}")


if __name__ == "__main__":
    main()

