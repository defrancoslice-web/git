"""模块一（上）：灾情数据自动化导入与模板比对。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .config import Settings
from .models import IngestReport, Issue

_SPACE_RE = re.compile(r"[\s\u3000]+")
_PAREN_RE = re.compile(r"[（(].*?[)）]")


def normalize_column(name: Any) -> str:
    """列名归一化：去空格、去括号注释、统一大小写。"""
    text = "" if name is None else str(name)
    text = _PAREN_RE.sub("", text)
    text = _SPACE_RE.sub("", text)
    text = text.replace("_", "").replace("-", "").strip()
    return text.lower()


def build_column_map(settings: Settings) -> dict[str, str]:
    """把「规范化后的列名」映射到「标准字段名」。"""
    mapping: dict[str, str] = {}
    for field_spec in settings.fields:
        name = field_spec["name"]
        mapping[normalize_column(name)] = name
        mapping[normalize_column(field_spec.get("label", ""))] = name
        mapping[normalize_column(field_spec.get("label", "").split("（")[0])] = name
    for name, metric_spec in settings.metrics.items():
        mapping[normalize_column(name)] = name
        mapping[normalize_column(metric_spec.get("label", ""))] = name
    for alias, target in settings.aliases.items():
        mapping[normalize_column(alias)] = target
    return {key: value for key, value in mapping.items() if key}


def read_table(path: str | Path) -> dict[str, pd.DataFrame]:
    """读取一个文件的全部工作表，返回 {工作表名: DataFrame}。"""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in {".csv", ".txt"}:
        last_error: Exception | None = None
        for encoding in ("utf-8-sig", "gbk", "utf-8"):
            try:
                frame = pd.read_csv(path, dtype=object, encoding=encoding)
                return {path.stem: frame}
            except UnicodeDecodeError as error:
                last_error = error
        raise ValueError(f"无法识别文本编码：{path}") from last_error

    if suffix in {".xlsx", ".xlsm"}:
        sheets = pd.read_excel(path, sheet_name=None, dtype=object, engine="openpyxl")
        return {name: frame for name, frame in sheets.items() if not frame.empty}

    raise ValueError(f"暂不支持的文件类型：{path.suffix}")


def _looks_like_title_row(frame: pd.DataFrame) -> bool:
    """判断第一行是否为标题行（只有一个非空单元格）。"""
    if frame.empty or len(frame.columns) < 3:
        return False
    filled = frame.iloc[0].notna().sum()
    return bool(filled == 1)


def align_header(frame: pd.DataFrame, raw_path: str | Path, sheet: str) -> pd.DataFrame:
    """模板表头前可能有标题行或空行，最多向下探测 3 行。"""
    if not _looks_like_title_row(frame):
        return frame
    for skip in (1, 2, 3):
        try:
            retry = pd.read_excel(
                raw_path, sheet_name=sheet, dtype=object, engine="openpyxl", header=skip
            )
        except Exception:
            return frame
        if not _looks_like_title_row(retry):
            return retry
    return frame


def map_columns(
    frame: pd.DataFrame, settings: Settings
) -> tuple[pd.DataFrame, dict[str, str], list[str], list[str]]:
    """把原始列名映射为标准字段名，并给出未识别列与缺失的必需字段。"""
    column_map = build_column_map(settings)
    matched: dict[str, str] = {}
    unmapped: list[str] = []
    rename: dict[Any, str] = {}

    for column in frame.columns:
        key = normalize_column(column)
        target = column_map.get(key)
        if target and target not in matched:
            matched[target] = str(column)
            rename[column] = target
        else:
            unmapped.append(str(column))

    result = frame.rename(columns=rename)
    keep = [column for column in result.columns if column in set(rename.values())]
    result = result[keep]
    missing_required = [name for name in settings.required_fields if name not in result.columns]
    return result, matched, unmapped, missing_required


def ingest(paths: Iterable[str | Path], settings: Settings) -> tuple[pd.DataFrame, IngestReport]:
    """批量导入：读取 -> 对齐表头 -> 字段映射 -> 纵向合并。"""
    report = IngestReport()
    frames: list[pd.DataFrame] = []

    for raw_path in paths:
        raw_path = Path(raw_path)
        report.files.append(str(raw_path))
        sheets = read_table(raw_path)
        for sheet_name, frame in sheets.items():
            report.sheets.append(f"{raw_path.name}#{sheet_name}")
            frame = align_header(frame, raw_path, sheet_name)
            mapped, matched, unmapped, missing = map_columns(frame, settings)
            report.rows_read += int(len(frame))
            report.columns_raw.extend(str(column) for column in frame.columns)
            report.matched_columns.update(matched)
            for column in unmapped:
                if column not in report.unmapped_columns:
                    report.unmapped_columns.append(column)
            for name in missing:
                if name not in report.missing_required:
                    report.missing_required.append(name)
            if mapped.empty:
                report.issues.append(
                    Issue(
                        "error",
                        "SHEET_EMPTY",
                        f"{raw_path.name}#{sheet_name} 未识别到任何标准字段",
                    )
                )
                continue
            mapped = mapped.copy()
            mapped["_source_file"] = raw_path.name
            mapped["_source_sheet"] = sheet_name
            frames.append(mapped)

    standard_columns = settings.field_names + settings.metric_names
    if not frames:
        frame = pd.DataFrame(columns=standard_columns)
    else:
        frame = pd.concat(frames, ignore_index=True, sort=False)
        for name in standard_columns:
            if name not in frame.columns:
                frame[name] = pd.NA
        frame = frame[standard_columns + ["_source_file", "_source_sheet"]]

    # 必需字段是否缺失，以合并后的整体数据为准（单个工作表缺字段不算）
    report.missing_required = [
        name
        for name in settings.required_fields
        if name not in frame.columns or frame[name].isna().all()
    ]
    if report.missing_required:
        report.issues.append(
            Issue(
                "error",
                "MISSING_REQUIRED_FIELD",
                "缺失赛项要求的必需字段：" + "、".join(report.missing_required),
                count=len(report.missing_required),
            )
        )
    if report.unmapped_columns:
        report.issues.append(
            Issue(
                "warning",
                "UNMAPPED_COLUMN",
                "模板中存在未识别列，需确认是否补充字段映射",
                count=len(report.unmapped_columns),
                samples=report.unmapped_columns[:10],
            )
        )
    report.rows_out = int(len(frame))
    return frame, report
