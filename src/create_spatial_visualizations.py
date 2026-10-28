"""Plot anonymized grid attributes from the latest completed cleaned station table."""
import argparse
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, LogNorm
from matplotlib.ticker import PercentFormatter
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def utilization_color_scale():
    """Shared exploratory bins, with finer resolution where observations concentrate."""
    boundaries = np.array([0, .01, .03, .05, .10, .15, .20, .30, .50, 1.0])
    cmap = plt.get_cmap('viridis', len(boundaries) - 1)
    return boundaries, BoundaryNorm(boundaries, cmap.N, clip=False), cmap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metric', choices=['all', 'orders', 'energy_kwh', 'utilization'], default='all')
    args = parser.parse_args()
    manifests = sorted((ROOT/'data/processed').glob('clean_v1_*/cleaning_manifest.json'))
    if not manifests:
        raise SystemExit('Run src/clean_dataset.py first.')
    manifest = json.loads(manifests[-1].read_text(encoding='utf-8'))
    data = pd.read_parquet(manifests[-1].parent/'stations_monthly_clean.parquet')
    coordinates = data.grid_id.str.extract(r'^(?:GX)?(-?\d+)[_](?:GY)?(-?\d+)$')
    if coordinates.isna().any().any():
        raise ValueError('Unrecognized grid_id; inspect coordinate encoding before plotting.')
    data[['x', 'y']] = coordinates.astype(int).to_numpy()
    # Rows can share a grid; sum additive fields, weight utilization by gun count.
    data['utilization_gun_weight'] = data.monthly_gun_utilization_rate * data.charging_gun_num
    grid = data.groupby(['month', 'grid_id', 'x', 'y'], as_index=False).agg(
        orders=('monthly_order_count', 'sum'),
        energy_kwh=('monthly_total_elec_kwh', 'sum'),
        guns=('charging_gun_num', 'sum'),
        weighted_util=('utilization_gun_weight', 'sum'),
    )
    grid['utilization'] = grid.weighted_util / grid.guns.replace(0, np.nan)
    q1 = grid[['x','y']].quantile(0.25)
    q3 = grid[['x','y']].quantile(0.75)
    spatial_outlier = ((grid[['x','y']] < q1 - 10*(q3-q1)) | (grid[['x','y']] > q3 + 10*(q3-q1))).any(axis=1)
    offscreen = grid.loc[spatial_outlier]
    main_grid = grid.loc[~spatial_outlier]
    output = ROOT/'reports/figures/cleaned/spatial'
    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    specs = [('orders', 'Monthly sessions', '01-grid-orders.png', True),
             ('energy_kwh', 'Monthly energy (kWh)', '02-grid-energy.png', True),
             ('utilization', 'Gun-weighted utilization', '03-grid-utilization.png', False)]
    for metric, title, name, logarithmic in specs:
        if args.metric not in ('all', metric):
            continue
        positive = grid.loc[grid[metric] > 0, metric]
        boundaries = None
        cmap = 'viridis'
        if logarithmic:
            norm = LogNorm(vmin=positive.min(), vmax=positive.max())
        else:
            values = grid[metric].dropna()
            if not values.between(0, 1).all():
                raise ValueError('Utilization outside [0, 1]; audit before plotting.')
            boundaries, norm, cmap = utilization_color_scale()
            # Preserve the original project figure before replacing its color scale.
            original = output/'03-grid-utilization-original-linear.png'
            if (output/name).exists() and not original.exists():
                shutil.copy2(output/name, original)
        fig, axes = plt.subplots(1, 2, figsize=(12, 6), sharex=True, sharey=True, layout='constrained')
        for ax, month in zip(axes, ('2025-01', '2025-07')):
            g = main_grid[main_grid.month == month]
            artist = ax.scatter(g.x, g.y, c=g[metric], norm=norm, cmap=cmap, marker='s', s=10, linewidths=0, rasterized=True)
            ax.set(title=f'{month}: {len(g):,} observed grids', xlabel='Anonymized grid X')
            ax.set_aspect('equal', adjustable='box')
            ax.set_xlim(main_grid.x.min()-2, main_grid.x.max()+2)
            ax.set_ylim(main_grid.y.min()-2, main_grid.y.max()+2)
        axes[0].set_ylabel('Anonymized grid Y')
        colorbar_options = {} if logarithmic else dict(
            boundaries=boundaries, ticks=boundaries, spacing='uniform',
            format=PercentFormatter(xmax=1, decimals=0),
        )
        fig.colorbar(artist, ax=axes, shrink=0.75,
                     label=title + (' (log color scale)' if logarithmic else ' (shared bins)'),
                     **colorbar_options)
        fig.suptitle(title + '\nCleaned station-month table; original aggregate values retained', fontsize=13)
        footer = f'Anonymous relative coordinates. Blank = unobserved. Main cluster view; {len(offscreen)} remote grid-month record listed in report.'
        if not logarithmic:
            footer += '\nUnequal percentage intervals shown as equal-width color bands; identical bins for both months. No values clipped.'
        fig.supxlabel(footer, fontsize=9)
        fig.savefig(output/name, dpi=180)
        plt.close(fig)
    note = f'''# 匿名网格空间可视化

使用清洗运行 `{manifest['run_id']}` 的站点月表。两个月使用相同坐标范围和颜色范围，便于比较。

- 订单量、电量：同月同网格的多行记录求和，颜色使用对数尺度。
- 利用率：以充电枪数量加权的月利用率。零枪数时标记缺失，不置零。
- 利用率色标：两个月份统一使用0%、1%、3%、5%、10%、15%、20%、30%、50%、100%作为分段边界，细分低值区间，不改变利用率、不截断高值。色带等宽展示，但数值区间不等宽；这些是探索性展示分段，不是设施利用优劣的评价标准。
- 原利用率图使用0%—100%线性色标，另存为 `reports/figures/cleaned/spatial/03-grid-utilization-original-linear.png`。新图仍为 `03-grid-utilization.png`。
- 网格坐标来自匿名编码，仅显示相对空间结构，不叠加北京真实边界、道路或区县。
- 空白表示没有观察到记录，不表示需求为零。
- 主图使用各坐标四分位距外扩10倍的筛选展示主要坐标簇；远端网格保留在数据和总体统计中，不擅自改码。远端记录：{offscreen[['month','grid_id','orders','energy_kwh']].to_dict(orient='records')}。`85_111`与其余约`98xx_44xx`编码相距极远，可能采用了不同编码或存在错误，原因待核实；图中不把它强行放进主要网格簇。
- **数据限制**：月表清洗只统一了场景名称，订单数、电量和利用率仍为原始汇总。由于订单不含网格或站点键，无法把隔离的20条交易从对应网格电量中扣除。因此这些图不能称为已剔除异常电量后的空间图。
- 同网格多行不是重复订单，按网格汇总不做简单去重。加权利用率是描述指标，尚不能确认各行枪数不存在重复统计。

运行：`python src/create_spatial_visualizations.py`；只更新利用率图：`python src/create_spatial_visualizations.py --metric utilization`。
'''
    (ROOT/'reports/spatial_review.md').write_text(note, encoding='utf-8')
    print(grid.groupby('month').agg(grids=('grid_id', 'size'), orders=('orders','sum')).to_string())
    print(output)


if __name__ == '__main__':
    main()
