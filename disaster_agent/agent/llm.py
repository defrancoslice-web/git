"""大模型适配层。

默认使用离线规则模型（MockLLM），没有 API Key 也能完整演示；
配置密钥后自动切换到真实大模型，接口保持一致。

密钥来源（优先级从高到低）：
1. config/llm.local.json            —— 本地文件，已加入 .gitignore，不会进入分发包
2. 环境变量 DISASTER_AGENT_API_KEY / OPENAI_API_KEY
3. 环境变量 OPENAI_API_KEY（兼容既有习惯）
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..config import CONFIG_DIR

LOCAL_CONFIG_PATH = CONFIG_DIR / "llm.local.json"
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


def load_local_config() -> dict[str, Any]:
    """读取本地密钥文件。文件不存在或格式错误时返回空字典，不影响主流程。"""
    path = Path(LOCAL_CONFIG_PATH)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_local_config(api_key: str, base_url: str, model: str) -> Path:
    """写入本地密钥文件。返回文件路径。"""
    path = Path(LOCAL_CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_说明": "本文件包含 API 密钥，已加入 .gitignore。打包发版前请确认不要随包分发。",
        "api_key": api_key.strip(),
        "base_url": base_url.strip(),
        "model": model.strip(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return key[:2] + "***"
    return f"{key[:5]}****{key[-4:]}"


def resolve_credentials() -> dict[str, str]:
    """按优先级汇总密钥配置，不返回未设置的占位值。"""
    local = load_local_config()
    api_key = (
        str(local.get("api_key") or "").strip()
        or os.environ.get("DISASTER_AGENT_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
    )
    base_url = (
        str(local.get("base_url") or "").strip()
        or os.environ.get("DISASTER_AGENT_BASE_URL", "").strip()
        or DEFAULT_BASE_URL
    )
    model = (
        str(local.get("model") or "").strip()
        or os.environ.get("DISASTER_AGENT_MODEL", "").strip()
        or DEFAULT_MODEL
    )
    source = "未配置"
    if local.get("api_key"):
        source = "config/llm.local.json"
    elif os.environ.get("DISASTER_AGENT_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        source = "环境变量"
    return {"api_key": api_key, "base_url": base_url, "model": model, "source": source}


def config_status() -> dict[str, Any]:
    """给命令行和界面看的配置状态（密钥脱敏）。"""
    creds = resolve_credentials()
    return {
        "已配置": bool(creds["api_key"]),
        "密钥来源": creds["source"],
        "密钥": _mask(creds["api_key"]),
        "接口地址": creds["base_url"],
        "模型": creds["model"],
        "本地文件": str(LOCAL_CONFIG_PATH),
        "本地文件存在": Path(LOCAL_CONFIG_PATH).exists(),
    }


class MockLLM:
    """离线意图解析：关键词到分析计划的映射，保证演示不依赖网络。"""

    name = "mock-rule-based"

    def ping(self) -> str:
        return "离线规则模型，无需联网"

    DISASTER_KEYWORDS = ["洪涝", "干旱", "地震", "地质灾害", "风雹", "低温冷冻", "雪灾", "森林火灾"]

    def plan(self, question: str, context: dict[str, Any]) -> dict[str, Any]:
        text = question or ""
        dimensions: list[str] = []
        metrics: list[str] = []
        filters: dict[str, Any] = {}

        if any(word in text for word in ["结构", "占比", "构成", "比重"]):
            dimensions.append("loss_structure")
        if any(word in text for word in ["汛期", "季节"]):
            dimensions.append("custom_season")
        if any(word in text for word in ["等级", "级别", "响应"]):
            dimensions.append("emergency_level")
        if any(word in text for word in ["年份", "每年", "逐年", "趋势", "年际"]):
            dimensions.append("time_year")
        if any(word in text for word in ["季度"]):
            dimensions.append("time_quarter")
        if any(word in text for word in ["月份", "月度", "逐月"]):
            dimensions.append("time_month")
        if any(word in text for word in ["日", "逐日"]):
            dimensions.append("time_day")
        if any(word in text for word in ["县", "县域", "区县"]):
            dimensions.append("region_county")
        if any(word in text for word in ["市", "市州"]):
            dimensions.append("region_city")
        if any(word in text for word in ["乡", "镇", "村落"]):
            dimensions.append("region_town")
        if any(word in text for word in ["灾种", "灾害类型", "哪类灾害"]) and "loss_structure" not in dimensions:
            dimensions.append("disaster_type")

        if any(word in text for word in ["人口", "人", "伤亡"]):
            metrics.extend(["affected_population", "deaths"])
        if any(word in text for word in ["面积", "农作物"]):
            metrics.append("affected_crop_area")
        if any(word in text for word in ["房屋", "倒房"]):
            metrics.append("collapsed_houses")
        if not metrics:
            metrics.append("direct_economic_loss")

        for disaster in self.DISASTER_KEYWORDS:
            if disaster in text:
                filters["disaster_type"] = disaster
                break
        for level in ["特别重大", "重大", "较大", "一般"]:
            if level in text:
                filters["emergency_level"] = level
                break

        if not dimensions:
            dimensions = ["time_year"]

        return {
            "dimensions": dimensions[:2],
            "metrics": metrics[:3],
            "filters": filters,
            "reasoning": f"离线规则解析：从问题中识别到维度 {dimensions[:2]}、指标 {metrics[:3]}",
        }

    def polish(self, title: str, text: str) -> str:
        return text

    def answer(self, question: str, facts: dict[str, Any]) -> str:
        return ""


class OpenAICompatLLM:
    """OpenAI 兼容接口的极简客户端，只依赖标准库。"""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.fallback = MockLLM()

    @property
    def name(self) -> str:
        return f"llm:{self.model}"

    def ping(self) -> str:
        """连通性自检：发一条最短的请求确认密钥与模型可用。"""
        return self._chat(
            [{"role": "user", "content": "只回复两个字：正常"}], temperature=0.0
        ).strip()

    def _chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        import urllib.request

        payload = json.dumps(
            {"model": self.model, "messages": messages, "temperature": temperature},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]

    def plan(self, question: str, context: dict[str, Any]) -> dict[str, Any]:
        system = (
            "你是自然灾害灾情分析平台的规划器。请把用户问题翻译成分析计划，只输出 JSON，"
            '格式为 {"dimensions": [...], "metrics": [...], "filters": {...}, "reasoning": "..."}。\n'
            f"可用维度：{json.dumps(context.get('dimensions', []), ensure_ascii=False)}；"
            f"可用指标：{json.dumps(context.get('metrics', []), ensure_ascii=False)}。\n"
            "filters 的取值必须从下面的候选值中原样选取，禁止使用「近五年」「近几年」「最近」这类描述性说法："
            f"{json.dumps(context.get('filter_hints', {}), ensure_ascii=False)}。\n"
            "如果问题中的时间范围或条件无法用候选值表达，就不要添加对应的筛选条件。"
        )
        try:
            content = self._chat(
                [{"role": "system", "content": system}, {"role": "user", "content": question}]
            )
            start, end = content.find("{"), content.rfind("}")
            return json.loads(content[start : end + 1])
        except Exception:
            return self.fallback.plan(question, context)

    def polish(self, title: str, text: str) -> str:
        system = (
            "你是应急管理领域的报告编辑。请在不改变任何数字、单位和结论的前提下润色下面这段文字，"
            "只输出润色后的正文，不要添加新数据。"
        )
        try:
            return self._chat(
                [{"role": "system", "content": system}, {"role": "user", "content": text}],
                temperature=0.3,
            ).strip()
        except Exception:
            return text

    def answer(self, question: str, facts: dict[str, Any]) -> str:
        system = (
            "你是灾情分析助手。只能使用给定的事实数据作答，禁止编造数字，"
            "如数据不足以回答请直接说明。"
        )
        try:
            return self._chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"问题：{question}\n事实数据：{json.dumps(facts, ensure_ascii=False)}"},
                ]
            ).strip()
        except Exception:
            return ""


def get_llm(mode: str = "auto"):
    """mode: auto / mock / openai。auto 时有 API Key 就用真模型。"""
    if mode == "mock":
        return MockLLM()
    creds = resolve_credentials()
    if mode == "openai" or (mode == "auto" and creds["api_key"]):
        if not creds["api_key"]:
            return MockLLM()
        return OpenAICompatLLM(
            api_key=creds["api_key"],
            base_url=creds["base_url"],
            model=creds["model"],
        )
    return MockLLM()
