"""模拟灾情数据生成器。

用于在没有组委会数据时跑通全流程，并故意注入典型数据质量问题，
让清洗模块的每一项处理都有真实来源。正式参赛时替换为组委会下发的模拟数据。
"""

from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

from .config import DATA_DIR, load_json

TEMPLATE_COLUMNS = [
    "记录编号",
    "灾种",
    "发生时间",
    "灾情等级",
    "省",
    "省级代码",
    "市（州）",
    "市级代码",
    "县（区）",
    "县级代码",
    "乡（镇）",
    "乡镇代码",
    "受灾人口（人）",
    "因灾死亡失踪人口（人）",
    "因灾受伤人口（人）",
    "紧急转移安置人口（人）",
    "倒塌房屋（间）",
    "损坏房屋（间）",
    "农作物受灾面积（千公顷）",
    "农作物绝收面积（千公顷）",
    "直接经济损失（万元）",
    "基础设施损失（万元）",
    "农业损失（万元）",
    "房屋及家庭财产损失（万元）",
]

DISASTER_PROFILE = {
    "洪涝": {"months": [5, 6, 7, 8, 9], "weight": 26, "severity": 1.35},
    "地质灾害": {"months": [5, 6, 7, 8, 9], "weight": 16, "severity": 0.95},
    "干旱": {"months": [3, 4, 5, 6, 7, 8], "weight": 12, "severity": 1.10},
    "风雹": {"months": [4, 5, 6, 7, 8], "weight": 11, "severity": 0.70},
    "地震": {"months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], "weight": 6, "severity": 1.60},
    "低温冷冻": {"months": [1, 2, 3, 11, 12], "weight": 8, "severity": 0.62},
    "雪灾": {"months": [1, 2, 12], "weight": 7, "severity": 0.66},
    "森林火灾": {"months": [2, 3, 4, 5], "weight": 7, "severity": 0.58},
    "其他": {"months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], "weight": 7, "severity": 0.50},
}


def _load_regions() -> dict:
    return load_json(DATA_DIR / "reference" / "regions.json")


def _build_catalog(regions: dict, seed: int) -> list[dict]:
    rng = random.Random(seed)
    towns_by_county: dict[str, list[tuple[str, str]]] = {}
    for code, name in regions["towns"].items():
        towns_by_county.setdefault(code[:6], []).append((code, name))

    catalog: list[dict] = []
    for county_code, county_name in regions["counties"].items():
        city_code = county_code[:4]
        city_name = regions["cities"].get(city_code)
        if not city_name:
            continue
        entry = {
            "省": regions["provinces"].get(county_code[:2], "四川省"),
            "省级代码": county_code[:2],
            "市（州）": city_name,
            "市级代码": city_code,
            "县（区）": county_name,
            "县级代码": county_code,
            "乡（镇）": "",
            "乡镇代码": "",
        }
        towns = towns_by_county.get(county_code)
        if towns and rng.random() < 0.9:
            code, name = rng.choice(towns)
            entry["乡（镇）"] = name
            entry["乡镇代码"] = code
        catalog.append(entry)
    return catalog


def _severity_value(severity: float, rng: random.Random, low: float, high: float) -> float:
    shape = rng.random() ** 2.6  # 长尾：大多数灾情损失较小，少数事件损失很大
    return round((low + (high - low) * shape) * severity, 2)


def build_records(years: list[int], count: int, seed: int) -> pd.DataFrame:
    regions = _load_regions()
    catalog = _build_catalog(regions, seed)
    rng = random.Random(seed)
    rows: list[dict] = []

    types = list(DISASTER_PROFILE.keys())
    weights = [DISASTER_PROFILE[item]["weight"] for item in types]
    counter = 1

    for _ in range(count):
        disaster = rng.choices(types, weights=weights, k=1)[0]
        profile = DISASTER_PROFILE[disaster]
        year = rng.choice(years)
        month = rng.choice(profile["months"])
        day = rng.randint(1, 28)
        severity = profile["severity"] * rng.uniform(0.6, 1.5)

        place = rng.choice(catalog)
        affected = max(int(_severity_value(severity, rng, 120, 260000)), 30)
        deaths = int(_severity_value(severity, rng, 0, 26))
        injured = int(_severity_value(severity, rng, 0, 90))
        evacuated = int(affected * rng.uniform(0.02, 0.28))
        collapsed = int(_severity_value(severity, rng, 0, 3600))
        damaged = collapsed * rng.randint(2, 7) + rng.randint(0, 260)
        crop = _severity_value(severity, rng, 0.05, 32, )
        destroyed = round(crop * rng.uniform(0.05, 0.35), 3)

        loss = _severity_value(severity, rng, 60, 68000)
        infrastructure = round(loss * rng.uniform(0.22, 0.42), 2)
        agriculture = round(loss * rng.uniform(0.16, 0.34), 2)
        housing = round(loss * rng.uniform(0.08, 0.24), 2)

        if loss > 40000:
            level = "特别重大"
        elif loss > 15000:
            level = "重大"
        elif loss > 4000:
            level = "较大"
        else:
            level = "一般"

        rows.append(
            {
                "记录编号": f"SC{year}{counter:05d}",
                "灾种": disaster,
                "发生时间": f"{year:04d}-{month:02d}-{day:02d}",
                "灾情等级": level,
                **place,
                "受灾人口（人）": affected,
                "因灾死亡失踪人口（人）": deaths,
                "因灾受伤人口（人）": injured,
                "紧急转移安置人口（人）": evacuated,
                "倒塌房屋（间）": collapsed,
                "损坏房屋（间）": damaged,
                "农作物受灾面积（千公顷）": crop,
                "农作物绝收面积（千公顷）": destroyed,
                "直接经济损失（万元）": loss,
                "基础设施损失（万元）": infrastructure,
                "农业损失（万元）": agriculture,
                "房屋及家庭财产损失（万元）": housing,
            }
        )
        counter += 1

    return pd.DataFrame(rows)


def inject_dirt(frame: pd.DataFrame, seed: int) -> pd.DataFrame:
    """注入典型数据质量问题：文本单位、混合日期格式、缺失、异常值、层级冲突、重复。"""
    rng = random.Random(seed + 7)
    # 统一转成 object 列，便于把数值替换成带单位的文本（模拟真实上报数据）
    data = frame.astype(object).copy()
    size = len(data)

    money_fields = ["直接经济损失（万元）", "基础设施损失（万元）", "农业损失（万元）"]
    for field in money_fields:
        for index in rng.sample(range(size), k=max(int(size * 0.08), 1)):
            value = data.at[index, field]
            data.at[index, field] = f"{value / 10000:.2f}亿元" if value >= 8000 else f"{value:.1f}"

    for index in rng.sample(range(size), k=max(int(size * 0.12), 1)):
        value = data.at[index, "受灾人口（人）"]
        data.at[index, "受灾人口（人）"] = (
            f"{value / 10000:.2f}万人" if value >= 10000 else f"{value}人"
        )

    for index in rng.sample(range(size), k=max(int(size * 0.06), 1)):
        text = str(data.at[index, "发生时间"])
        year, month, day = text.split("-")
        data.at[index, "发生时间"] = f"{year}年{int(month)}月{int(day)}日"
    for index in rng.sample(range(size), k=max(int(size * 0.05), 1)):
        text = str(data.at[index, "发生时间"])
        data.at[index, "发生时间"] = text.replace("-", "/")

    for field in ["直接经济损失（万元）", "倒塌房屋（间）", "农作物受灾面积（千公顷）"]:
        for index in rng.sample(range(size), k=max(int(size * 0.05), 1)):
            data.at[index, field] = rng.choice(["", "-", None])

    for index in rng.sample(range(size), k=3):
        data.at[index, "直接经济损失（万元）"] = 999999
    for index in rng.sample(range(size), k=2):
        data.at[index, "受灾人口（人）"] = -120

    field = "农作物受灾面积（千公顷）"
    for index in rng.sample(range(size), k=max(int(size * 0.06), 1)):
        value = data.at[index, field]
        if isinstance(value, (int, float)):
            data.at[index, field] = f"{value * 15:.1f}万亩"

    for index in rng.sample(range(size), k=5):
        code = str(data.at[index, "县级代码"])
        data.at[index, "县级代码"] = "5107" + code[4:] if code[:4] != "5107" else "5101" + code[4:]

    duplicates = data.sample(n=4, random_state=seed)
    data = pd.concat([data, duplicates], ignore_index=True)

    for index in rng.sample(range(size), k=2):
        data.at[index, "县（区）"] = None
    return data


def generate(out_dir: str | Path | None = None, seed: int = 20260916, total: int = 480) -> list[Path]:
    """生成两个批次文件，用于演示批量上传。"""
    out_dir = Path(out_dir) if out_dir else DATA_DIR / "sample"
    out_dir.mkdir(parents=True, exist_ok=True)

    batches = [
        ("灾情数据_2021-2023.xlsx", [2021, 2022, 2023], total // 2),
        ("灾情数据_2024-2025.xlsx", [2024, 2025], total - total // 2),
    ]
    written: list[Path] = []
    for offset, (name, years, count) in enumerate(batches):
        frame = build_records(years, count, seed + offset)
        frame = inject_dirt(frame, seed + offset)
        for column in TEMPLATE_COLUMNS:
            if column not in frame.columns:
                frame[column] = ""
        frame = frame[TEMPLATE_COLUMNS]

        path = out_dir / name
        notes = pd.DataFrame(
            {
                "列名": TEMPLATE_COLUMNS,
                "说明": [
                    "灾情记录唯一编号",
                    "洪涝/干旱/地震/地质灾害/风雹/低温冷冻/雪灾/森林火灾/其他",
                    "建议 YYYY-MM-DD，平台兼容多种常见格式",
                    "特别重大/重大/较大/一般",
                    "省级行政区名称",
                    "省级行政区划代码，2 位",
                    "市（州）名称",
                    "市级行政区划代码，4 位",
                    "县（区）名称",
                    "县级行政区划代码，6 位",
                    "乡（镇）名称，可选",
                    "乡级行政区划代码，9 位，可选",
                ]
                + [
                    "受灾人口，单位：人",
                    "因灾死亡失踪人口，单位：人",
                    "因灾受伤人口，单位：人",
                    "紧急转移安置人口，单位：人",
                    "倒塌房屋，单位：间",
                    "损坏房屋，单位：间",
                    "农作物受灾面积，单位：千公顷",
                    "农作物绝收面积，单位：千公顷",
                    "直接经济损失，单位：万元",
                    "基础设施损失，单位：万元",
                    "农业损失，单位：万元",
                    "房屋及家庭财产损失，单位：万元",
                ],
            }
        )
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            frame.to_excel(writer, sheet_name="灾情数据", index=False)
            notes.to_excel(writer, sheet_name="字段说明", index=False)
        written.append(path)
    return written


if __name__ == "__main__":  # pragma: no cover
    for item in generate():
        print("已生成", item)
