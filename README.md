# 北京公共电动车充电数据分析

研究北京市公共充电设施需求与利用的网格差异，比较2025年1月和7月。当前仅使用Figshare发布版Version 2作为正式分析主线，已完成清洗、站点关联、网格重建、设施计数敏感性、共同站点比较及可观测自然月时长对照。

## 当前结果入口

- [阶段总结与后续任务](reports/新版数据阶段总结与后续任务.md)
- [共同网格与共同站点冬夏比较](reports/winter_summer_comparison.md)
- [自然月占用时长对照](reports/calendar_month_review.md)
- [文献依据与可视化扩展方案](reports/文献参考与可视化扩展方案.md)
- [论文展示门槛与设施计数敏感性](reports/release_v2_filters_sensitivity.md)
- [阶段PPT](deliverables/北京充电数据分析_新版数据与冬夏比较_1104修订版.pptx)及[逐页讲稿](reports/新版数据_五分钟逐页讲稿.md)。PPT尚未加入后续自然月对照和新增热图。

固定共同站点后，1月、7月按开始月统计的汇总利用率为4.555%、8.975%。现有会话按自然月拆分后为4.540948%、9.008884%。这属于两个观察月份、观测活跃样本的描述性差异，不能推断完整季节因果或未满足的设施需求。

## 数据与版本

- 论文：*A city-scale dataset of public electric vehicle charging transactions and infrastructure*，DOI：[10.1038/s41597-026-07918-5](https://doi.org/10.1038/s41597-026-07918-5)。
- 数据集：[Figshare DOI](https://doi.org/10.6084/m9.figshare.31952289)，当前使用发布方Version 2，原文件保存在本地`data/redownloaded/31952289/`。
- `orders_2025-01_public.parquet`：2,137,234条订单。
- `orders_2025-07_public.parquet`：6,407,461条订单。
- `stations_public.parquet`：8,553个唯一站点。订单通过`station_id`全部关联到站点及匿名网格。

发布方Version 2与此前项目自行命名的“清洗v2”不同。旧发布版原文件仍保存在`data/raw/`以备版本核验，正式分析不再从该目录读取数据。旧版本派生数据、图表及多数旧PPT已清理，旧1102版PPT因文件占用暂未删除，清单见[清理记录](reports/legacy_v1_cleanup.json)。Git中曾提交的旧内容仍可通过历史提交找回。

原始数据、ZIP、处理中间数据和论文译稿不上传仓库。译稿仅用于本地阅读，原始文件不修改。

## 处理与复现

需要Python 3.11或以上，在项目目录安装依赖：

```powershell
python -m pip install -e .
```

按以下顺序运行：

```powershell
python src/audit_release_v2.py
python src/rebuild_release_v2.py
python src/plot_release_v2.py
python src/analyze_grid_sensitivity.py
python src/compare_winter_summer.py
python src/analyze_calendar_month.py
```

清洗和图表脚本选择有完成清单的最新运行，失败的部分输出不会进入正式分析。

当前清洗运行：`20261104T011749595890Z`，文件位于`data/processed/source_release2_clean1_20261104T011749595890Z/`，图表位于`reports/figures/source_release2/20261104T011749595890Z/`。自然月派生运行：`20261104T075413371066Z`，位于`data/processed/calendar_month_20261104T075413371066Z/`。

1月剔除20条联合极端电量记录及1,179条关键字段缺失记录，两类无重叠。正式开始月样本为1月2,136,035条、7月6,393,968条；13,493条6月开始的订单单独保留。清洗规则、哈希和分区核对见[完成清单](reports/source_release2_clean1_20261104T011749595890Z.json)。

## 图表与解释

![新版月度活动](reports/figures/source_release2/20261104T011749595890Z/01-monthly-overview.png)

![新版网格利用率](reports/figures/source_release2/20261104T011749595890Z/spatial/03-grid-utilization.png)

网格利用率为记录会话时长之和／静态枪数／整月分钟数，未校正停机和重叠会话。平均单次电量与利用率展示分别使用至少5笔订单、至少5把枪的门槛，对照图独立保留。设施总分项不一致需要进一步核实，不能凭敏感性分析擅自修正原值。

自然月对照只拆分会话时长，不分摊电量或费用。1月文件可延续至2月，7月文件结束却止于7月底，且相邻月份边界会话未必完整，因此当前不是严格完整自然月利用率。星期×小时热图表示到达次数，不是电力负荷；Lorenz曲线描述网格集中程度，不代表人口公平性。

## 目录

```text
data/raw/          旧发布版原文件，仅保留用于版本核验
data/redownloaded/ 发布版Version 2原文件，不上传
data/processed/    新版清洗与自然月派生数据，不上传
reports/           新版审计、分析和说明
reports/figures/source_release2/ 新版图表
deliverables/      新版汇报PPT
src/               分析代码，包含新版仍使用的通用绘图函数
tests/             分析校验
translations/      本地论文译稿，不上传
```

早期清洗脚本和校验保留作为实现历史，不是当前分析入口。正式流程以上述发布版Version 2命令为准。
