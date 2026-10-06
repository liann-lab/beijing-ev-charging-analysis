.# 北京公共电动车充电数据分析

本项目用于分析北京市公共电动车充电交易及充电基础设施数据。

当前状态：已取得数据集论文，原始 Parquet 数据尚未放入项目。

## 目录结构

```text
data/
  raw/          原始数据，只读使用，不提交到版本控制
  processed/    清洗或聚合后的数据
notebooks/      探索性分析笔记
reports/
  figures/      导出的图表
src/            可复用分析脚本
```

## 数据来源

- 论文：A city-scale dataset of public electric vehicle charging transactions and infrastructure
- Figshare DOI：https://doi.org/10.6084/m9.figshare.31952289
- 时间范围：2025年1月和2025年7月
- 预计结构：两张月度交易表和一张站点基础设施表

下载数据后，请
03把原始文件放入 `data/raw/`，不要修改原始文件。

## 环境安装

需要 Python 3.11 或更高版本。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## 首次数据盘点

```powershell
python src/inspect_dataset.py
```

脚本会生成：

- `reports/data_inventory.csv`：文件级清单、行数和列数
- `reports/schema_profile.csv`：字段名、推断类型和所在文件

对于 Parquet 文件，脚本只读取文件元数据，不会把全部交易记录载入内存。

