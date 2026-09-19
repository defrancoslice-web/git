"""模块一（下）：数据清洗与标准化 —— 规则优先，模型不参与数值改写。"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import Settings, load_json
from .models import CleaningLog, Issue

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_NULL_TOKENS = {"", "-", "--", "—", "－", "/", "无", "nan", "none", "null", "na", "n/a", "不详"}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if value is pd.NaT:
        return True
    if isinstance(value, str) and value.strip().lower() in _NULL_TOKENS:
        return True
    return False


def parse_quantity(
    raw: Any, unit_table: dict[str, float] | None = None
) -> tuple[float | None, str | None]:
    """把 "3.2亿元" / "1,234人" / "-" 解析成 (数值, 原始单位)。"""
    if _is_missing(raw):
        return None, None
    if isinstance(raw, (int, float, np.integer, np.floating)) and not isinstance(raw, bool):
        return float(raw), None

    text = str(raw).strip().replace(",", "").replace("，", "")
    unit: str | None = None
    if unit_table:
        for candidate in sorted(unit_table.keys(), key=len, reverse=True):
            if candidate in text:
                unit = candidate
                break
    match = _NUM_RE.search(text)
    if not match:
        return None, None
    return float(match.group()), unit


def parse_date(raw: Any, formats: list[str]) -> pd.Timestamp | None:
    """按配置的多格式列表解析日期。"""
    if _is_missing(raw):
        return None
    if isinstance(raw, pd.Timestamp):
        return raw
    if hasattr(raw, "year") and not isinstance(raw, str):
        return pd.Timestamp(raw)
    text = str(raw).strip()
    for fmt in formats:
        try:
            return pd.to_datetime(text, format=fmt)
        except (ValueError, TypeError):
            continue
    try:
        return pd.to_datetime(text, dayfirst=False)
    except (ValueError, TypeError):
        return None


def load_reference(settings: Settings) -> dict[str, Any]:
    path = settings.project_path(settings.cleaning["hierarchy"]["reference_file"])
    if Path(path).exists():
        return load_json(path)
    return {}


def _as_code(value: Any) -> str | None:
    if _is_missing(value):
        return None
    return re.sub(r"\.0$", "", str(value)).strip()


def clean(
    frame: pd.DataFrame, settings: Settings, reference: dict[str, Any] | None = None
) -> tuple[pd.DataFrame, CleaningLog]:
    """主清洗流程。每一步都会写入清洗日志。"""
    log = CleaningLog(rows_in=int(len(frame)))
    data = frame.copy()
    rules = settings.cleaning
    reference = reference if reference is not None else load_reference(settings)
    metric_columns = [name for name in settings.metric_names if name in data.columns]

    # --- 1. 整行空值剔除 ---
    before = len(data)
    data = data.dropna(how="all")
    log.add("空行处理", "*", "删除整行为空的记录", before - len(data))

    # --- 2. 文本字段归一化 ---
    text_fields = [
        spec["name"]
        for spec in settings.fields
        if spec["dtype"] == "string" and spec["role"] in {"disaster", "region", "attr"}
    ]
    touched = 0
    hit_fields: list[str] = []
    for name in text_fields:
        if name not in data.columns:
            continue
        original = data[name].copy()
        data[name] = data[name].map(
            lambda value: re.sub(r"\s+", "", str(value)).strip() if not _is_missing(value) else pd.NA
        )
        changed = int((original.fillna("__N__") != data[name].fillna("__N__")).sum())
        if changed:
            touched += changed
            hit_fields.append(name)
    log.add(
        "文本标准化",
        "、".join(hit_fields[:5]) if hit_fields else "文本字段",
        "去除空白字符与全角空格",
        touched,
    )

    # --- 3. 时间解析 ---
    date_field = "occur_date"
    if date_field in data.columns:
        was_null = int(data[date_field].isna().sum())
        parsed = data[date_field].map(lambda value: parse_date(value, rules["date_formats"]))
        failed = int(parsed.isna().sum()) - was_null
        data[date_field] = parsed
        log.add(
            "时间解析",
            date_field,
            "按配置的多格式列表解析为日期",
            int(parsed.notna().sum()),
            detail=f"解析失败 {max(failed, 0)} 条",
        )
        if failed > 0:
            log.issues.append(
                Issue("warning", "DATE_PARSE_FAILED", "存在无法解析的时间值", count=int(failed))
            )

    # --- 4. 派生时间字段 ---
    if date_field in data.columns and data[date_field].notna().any():
        moments = pd.to_datetime(data[date_field], errors="coerce")
        data["year"] = moments.dt.year
        data["quarter"] = moments.dt.quarter
        data["month"] = moments.dt.month
        data["day"] = moments.dt.day
        log.add(
            "时间派生",
            "year/quarter/month/day",
            "由发生时间派生统计时段字段",
            int(moments.notna().sum()),
        )

    # --- 5. 数值解析与单位换算 ---
    for name in metric_columns:
        unit_table = rules["unit_conversion"].get(name, {})
        parsed_pairs = data[name].map(lambda value: parse_quantity(value, unit_table))
        values = list(parsed_pairs.map(lambda pair: pair[0]))
        units = list(parsed_pairs.map(lambda pair: pair[1]))

        converted = 0
        result: list[float | None] = []
        for value, unit in zip(values, units):
            if value is None:
                result.append(None)
                continue
            factor = 1.0
            if unit and unit_table:
                factor = float(unit_table.get(unit, 1.0))
                if factor != 1.0:
                    converted += 1
            result.append(value * factor)
        data[name] = pd.to_numeric(pd.Series(result, index=data.index), errors="coerce")
        log.add("单位换算", name, "按规则表换算为标准单位", converted)

    # --- 6. 缺失值处理 ---
    reported_columns = [name for name in metric_columns if data[name].notna().any()]
    if reported_columns:
        data["_imputed_metrics"] = data[reported_columns].isna().sum(axis=1).astype(int)
    else:
        data["_imputed_metrics"] = 0

    fill_info = rules["missing"]
    filled_by_field: list[str] = []
    numeric_filled = 0
    for name in metric_columns:
        spec = settings.metric(name)
        if fill_info["numeric_policy"] == "zero_with_flag" and spec.get("fill") == 0:
            count = int(data[name].isna().sum())
            if count:
                data[name] = data[name].fillna(0)
                numeric_filled += count
                filled_by_field.append(name)
    log.add(
        "缺失值填充",
        "、".join(filled_by_field[:5]) if filled_by_field else "损失类指标",
        "按规则填充为 0（未上报损失），并写入 _imputed_metrics 标记",
        numeric_filled,
    )

    region_fields = [
        spec["name"] for spec in settings.fields if spec["role"] == "region" and spec.get("required")
    ]
    if fill_info["region_policy"] == "drop_row":
        before = len(data)
        mask = pd.Series(False, index=data.index)
        for name in region_fields:
            if name in data.columns:
                mask |= data[name].isna()
        data = data[~mask]
        log.add("缺失值处理", "、".join(region_fields), "关键区域字段缺失则剔除该行", before - len(data))

    if fill_info["categorical_policy"] == "fill_其他" and "disaster_type" in data.columns:
        count = int(data["disaster_type"].isna().sum())
        if count:
            data["disaster_type"] = data["disaster_type"].fillna("其他")
            log.add("缺失值填充", "disaster_type", "归入「其他」灾种", count)

    # --- 7. 异常值识别与处理 ---
    outlier_rule = rules["outlier"]
    hard_bounds = 0
    for name in metric_columns:
        spec = settings.metric(name)
        low, high = spec.get("bounds", [None, None])
        series = data[name]

        if low is not None:
            negative = int((series < low).sum())
            if negative:
                hard_bounds += negative
                data.loc[series < low, name] = low

        if outlier_rule["method"] == "iqr" and "disaster_type" in data.columns:
            capped: list[Any] = []
            for _, index in data.groupby("disaster_type").groups.items():
                subset = data.loc[index, name]
                if len(subset) < outlier_rule["min_group_size"]:
                    continue
                q1, q3 = subset.quantile(0.25), subset.quantile(0.75)
                iqr = q3 - q1
                if iqr <= 0:
                    continue
                upper = q3 + outlier_rule["iqr_factor"] * iqr
                hit = subset[subset > upper]
                if outlier_rule["action"] == "cap" and len(hit):
                    data.loc[hit.index, name] = upper
                    capped.extend(list(hit.index))
            log.add(
                "异常值处理",
                name,
                f"按灾种分组 IQR 盖帽（{outlier_rule['iqr_factor']} 倍）",
                len(capped),
            )

        if high is not None:
            over = int((data[name] > high).sum())
            if over:
                hard_bounds += over
                data.loc[data[name] > high, name] = high
    log.add("异常值处理", "全部损失类指标", "超出业务上下限的取值截断", hard_bounds)

    # --- 8. 行政层级关系校验 ---
    hierarchy = rules["hierarchy"]
    conflict_mask = pd.Series(False, index=data.index)
    samples: list[str] = []

    if "county_code" in data.columns:
        normalized = data["county_code"].map(_as_code)
        data["county_code"] = normalized
        if hierarchy.get("check_code_prefix"):
            for column, level in (("province_code", 2), ("city_code", 4)):
                if column not in data.columns:
                    continue
                parent = data[column].map(_as_code)
                mismatch = (
                    normalized.notna()
                    & parent.notna()
                    & (normalized.str[:level] != parent.str[:level])
                )
                if mismatch.any():
                    conflict_mask |= mismatch
                    for index in list(data.index[mismatch])[:5]:
                        samples.append(
                            f"{data.loc[index, 'county']}({normalized[index]}) 与上级 {parent[index]} 前缀不符"
                        )

    if hierarchy.get("check_name_against_reference") and reference:
        counties = reference.get("counties", {})
        if "county" in data.columns and "county_code" in data.columns:
            for index, code, name in zip(data.index, data["county_code"], data["county"]):
                if _is_missing(code) or _is_missing(name):
                    continue
                expected = counties.get(str(code))
                if expected and expected != str(name):
                    conflict_mask.loc[index] = True
                    if len(samples) < 8:
                        samples.append(f"{name}/{code} 参照表记录为 {expected}")

    data["_hierarchy_ok"] = ~conflict_mask
    conflicts = int(conflict_mask.sum())
    if conflicts:
        log.add("层级校验", "省/市/县代码", "前缀一致性与名称比对", conflicts)
        log.issues.append(
            Issue(
                "warning",
                "HIERARCHY_CONFLICT",
                "行政区划代码与名称、上下级前缀不一致，相关记录已标记待人工确认",
                count=conflicts,
                samples=samples[:8],
            )
        )

    # --- 9. 自定义维度派生 ---
    season_months = set(rules["season_rule"]["flood_season_months"])
    if "month" in data.columns:
        data["season"] = np.where(data["month"].isin(season_months), "汛期", "非汛期")
    if {"direct_economic_loss", "affected_population"} <= set(data.columns):
        per_capita = data["direct_economic_loss"] / data["affected_population"].replace(0, np.nan)
        data["per_capita_level"] = pd.cut(
            per_capita, bins=rules["per_capita_loss_bins"], labels=rules["per_capita_loss_labels"], right=False
        )
        data["per_capita_level"] = data["per_capita_level"].astype(object).fillna("无受灾人口")
    log.add("维度派生", "season/per_capita_level", "派生自定义分析维度", int(len(data)))

    # --- 10. 重复记录 ---
    dedupe_on = [name for name in rules["dedupe_on"] if name in data.columns]
    if dedupe_on:
        before = len(data)
        data = data.drop_duplicates(subset=dedupe_on, keep="first")
        log.add("重复记录", "、".join(dedupe_on), "按业务主键去重保留首条", before - len(data))

    log.rows_out = int(len(data))
    data = data.reset_index(drop=True)
    return data, log
