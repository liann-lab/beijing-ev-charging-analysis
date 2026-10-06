"""Create a lightweight inventory of the raw dataset files.

Parquet files are inspected through metadata only, so the full transaction
tables are not loaded into memory.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports"
SUPPORTED_SUFFIXES = {".parquet", ".csv", ".tsv", ".xlsx", ".xls"}


def inspect_parquet(path: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    try:
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "读取 Parquet 需要 pyarrow。请先运行 `python -m pip install -e .` 安装项目依赖。"
        ) from exc

    parquet_file = pq.ParquetFile(path)
    metadata = parquet_file.metadata
    schema = parquet_file.schema_arrow
    inventory = {
        "file_name": path.name,
        "format": "parquet",
        "size_mb": round(path.stat().st_size / 1024**2, 2),
        "row_count": metadata.num_rows,
        "column_count": metadata.num_columns,
        "sheet_name": "",
    }
    fields = [
        {
            "file_name": path.name,
            "sheet_name": "",
            "column_name": field.name,
            "data_type": str(field.type),
        }
        for field in schema
    ]
    return inventory, fields


def inspect_delimited(path: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    separator = "\t" if path.suffix.lower() == ".tsv" else ","
    sample = pd.read_csv(path, sep=separator, nrows=1000)
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        row_count = max(sum(1 for _ in handle) - 1, 0)
    inventory = {
        "file_name": path.name,
        "format": path.suffix.lower().lstrip("."),
        "size_mb": round(path.stat().st_size / 1024**2, 2),
        "row_count": row_count,
        "column_count": len(sample.columns),
        "sheet_name": "",
    }
    fields = [
        {
            "file_name": path.name,
            "sheet_name": "",
            "column_name": column,
            "data_type": str(sample[column].dtype),
        }
        for column in sample.columns
    ]
    return inventory, fields


def inspect_excel(path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    inventories: list[dict[str, object]] = []
    fields: list[dict[str, object]] = []
    workbook = pd.ExcelFile(path)
    for sheet_name in workbook.sheet_names:
        sample = pd.read_excel(path, sheet_name=sheet_name, nrows=1000)
        inventories.append(
            {
                "file_name": path.name,
                "format": path.suffix.lower().lstrip("."),
                "size_mb": round(path.stat().st_size / 1024**2, 2),
                "row_count": "sampled_only",
                "column_count": len(sample.columns),
                "sheet_name": sheet_name,
            }
        )
        fields.extend(
            {
                "file_name": path.name,
                "sheet_name": sheet_name,
                "column_name": column,
                "data_type": str(sample[column].dtype),
            }
            for column in sample.columns
        )
    return inventories, fields


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()

    raw_dir = args.raw_dir.resolve()
    report_dir = args.report_dir.resolve()
    files = sorted(
        path
        for path in raw_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )

    if not files:
        print(f"未在 {raw_dir} 找到 Parquet、CSV、TSV 或 Excel 数据文件。")
        print("请先将 Figshare 原始数据放入 data/raw/，再重新运行本脚本。")
        return 0

    inventory_rows: list[dict[str, object]] = []
    schema_rows: list[dict[str, object]] = []
    for path in files:
        suffix = path.suffix.lower()
        if suffix == ".parquet":
            inventory, fields = inspect_parquet(path)
            inventory_rows.append(inventory)
            schema_rows.extend(fields)
        elif suffix in {".csv", ".tsv"}:
            inventory, fields = inspect_delimited(path)
            inventory_rows.append(inventory)
            schema_rows.extend(fields)
        else:
            inventories, fields = inspect_excel(path)
            inventory_rows.extend(inventories)
            schema_rows.extend(fields)

    write_csv(
        report_dir / "data_inventory.csv",
        inventory_rows,
        ["file_name", "format", "size_mb", "row_count", "column_count", "sheet_name"],
    )
    write_csv(
        report_dir / "schema_profile.csv",
        schema_rows,
        ["file_name", "sheet_name", "column_name", "data_type"],
    )
    print(f"已盘点 {len(files)} 个数据文件。结果写入 {report_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

