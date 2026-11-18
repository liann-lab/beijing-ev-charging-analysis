"""Compare January start-hour counts at stations observed on all 18 workdays."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.ticker import StrMethodFormatter
import numpy as np
import pandas as pd

from analyze_grid_followup import MONTHS, ROOT, common_ids, day_types


def plot_fee_comparison(raw_rates, matched_rates, coverage, output):
    windows_font = Path('C:/Windows/Fonts/simhei.ttf')
    font_path = windows_font if windows_font.is_file() else findfont(
        FontProperties(family=['Noto Sans CJK SC', 'Microsoft YaHei', 'SimHei']),
        fallback_to_default=False)
    font = FontProperties(fname=font_path)
    fig = plt.figure(figsize=(13, 6.2), facecolor='white')
    grid = fig.add_gridspec(2, 2, width_ratios=[1.12, 1], left=.08, right=.97,
                           top=.76, bottom=.14, hspace=.65, wspace=.17)
    labels = ['05:00–06:59', '12:00–16:59']
    for row, (raw, fixed, label) in enumerate(zip(raw_rates, matched_rates, labels)):
        ax = fig.add_subplot(grid[row, 0])
        for x, (a, b) in enumerate(zip(raw, fixed)):
            ax.plot([x, x], [a, b], color='#a6b5c1', linewidth=2)
            ax.scatter(x, a, color='#b65321', s=55, zorder=3)
            ax.scatter(x, b, color='#24628b', s=45, marker='D', zorder=4)
            ax.annotate(f'{a:.3f}', (x, a), xytext=(-10, 0), textcoords='offset points',
                        ha='right', va='center', color='#943d14', fontsize=10)
            ax.annotate(f'{b:.3f}', (x, b), xytext=(10, 0), textcoords='offset points',
                        ha='left', va='center', color='#194d73', fontsize=10)
        ax.set(title=label, xlim=(-.45, 1.45), ylim=(.6, 2.08),
               xticks=[0, 1], xticklabels=['1/2–1/14', '1/15–1/27'])
        ax.set_ylabel('元/kWh', fontproperties=font)
        ax.grid(axis='y', alpha=.2)
        ax.spines[['top', 'right']].set_visible(False)
    notes = fig.add_subplot(grid[:, 1])
    notes.set_axis_off()
    blocks = [
        ('为什么做这个对照？', '图 27 发现清晨订单减少、午后增加。\n汇总收费恰好一升一降，因此核查：\n换成同一批桩和开始小时，差异还在吗？'),
        ('怎么算？', '橙点：电费和服务费之和 ÷ 电量之和。\n蓝菱形：两段都出现的同站、同桩、\n同开始小时组合，按前段电量统一加权。'),
        ('结果与限制', '配对后，清晨的涨幅消失，午后降幅缩小。\n'
         f'午后配对覆盖前段 {coverage[1][0]:.1%}、后段 {coverage[1][1]:.1%}\n'
         '的正电量订单。整笔收费无法还原分时\n价表，现有结果不足以确认调价。'),
    ]
    for y, (title, body) in zip([1, .66, .32], blocks):
        notes.text(0, y, title, fontproperties=font, fontsize=14, weight='bold', va='top')
        notes.text(0, y-.075, body, fontproperties=font, fontsize=11, va='top', linespacing=1.55)
    fig.text(.08, .94, '1 月收费差异：汇总比较与同桩同小时对照',
             fontproperties=font, fontsize=21, weight='bold')
    fig.text(.08, .875, '固定 1,846 个站点，每段各 9 个普通工作日。收费按会话开始时段归组。',
             fontproperties=font, fontsize=12)
    fig.text(.08, .82, '● 汇总收费     ◆ 固定桩、小时及权重后的收费',
             fontproperties=font, fontsize=11)
    fig.savefig(output/'07-january-matched-fees.png', dpi=180)
    plt.close(fig)


def main():
    manifests = sorted((ROOT/'data/processed').glob('source_release2_clean1_*/cleaning_manifest.json'))
    if not manifests:
        raise SystemExit('Run rebuild_release_v2.py first.')
    manifest = manifests[-1]
    run_id = json.loads(manifest.read_text(encoding='utf-8'))['run_id']
    stations = pd.read_parquet(manifest.parent/'stations_monthly_clean.parquet')
    common = common_ids(stations, 'station_id')
    january = MONTHS[0]
    orders = pd.read_parquet(manifest.parent/f'orders_{january}_clean.parquet',
                             columns=['station_id', 'pile_id', 'charge_start_time', 'total_elec_kwh',
                                      'total_elec_fee', 'total_service_fee'])
    dates = pd.date_range(january+'-02', january+'-27')
    workdays = dates[(day_types(dates) == 'workday') & (dates.day != 26)]
    starts = orders.charge_start_time
    orders = orders.loc[orders.station_id.isin(common) & starts.dt.normalize().isin(workdays)].copy()
    orders['date'] = orders.charge_start_time.dt.normalize()
    observed_days = orders.groupby('station_id').date.nunique()
    fixed = observed_days[observed_days.eq(len(workdays))].index
    orders = orders.loc[orders.station_id.isin(fixed)]
    early = orders.date.dt.day.lt(15)
    counts = orders.groupby([orders.charge_start_time.dt.hour, early]).size().unstack(
        fill_value=0).reindex(range(24), fill_value=0)
    before, after = counts[True], counts[False]
    change = after - before

    fig, (top, bottom) = plt.subplots(2, 1, figsize=(10, 7), sharex=True, layout='constrained')
    top.plot(before.index, before, 'o-', color='#24628b', markersize=4, label='Jan 2–14')
    top.plot(after.index, after, 'o-', color='#b65321', markersize=4, label='Jan 15–27')
    top.set(ylabel='Sessions across 9 workdays')
    top.legend(loc='upper left', frameon=False)
    bottom.bar(change.index, change, color=['#b65321' if value >= 0 else '#24628b' for value in change])
    bottom.axhline(0, color='#52606d', linewidth=.9)
    bottom.set(ylabel='Change in sessions', xlabel='Session start hour', xticks=range(24), xlim=(-.65, 23.65))
    for ax in (top, bottom):
        ax.axvspan(4.5, 6.5, color='#24628b', alpha=.08)
        ax.axvspan(11.5, 16.5, color='#b65321', alpha=.08)
        ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
        ax.grid(axis='y', alpha=.18)
        ax.set_axisbelow(True)
    fig.suptitle(f'January session starts at {len(fixed):,} stations\n'
                 'Same stations observed on all 18 ordinary workdays', fontweight='bold')
    output = ROOT/'reports/figures/source_release2'/run_id/'grid_followup'
    output.mkdir(parents=True, exist_ok=True)
    fig.savefig(output/'06-january-hourly-comparison.png', dpi=180)
    plt.close(fig)
    print(f'Stations: {len(fixed)}; early: {before.sum()}; late: {after.sum()}')
    print(f'05–06 change: {change.loc[5:6].sum()}; 12–16 change: {change.loc[12:16].sum()}')
    hour = orders.charge_start_time.dt.hour
    orders = orders.assign(period=np.where(early, 'Jan 2–14', 'Jan 15–27'),
                           band=np.select([hour.between(5, 6), hour.between(12, 16)],
                                          ['05–06', '12–16'], default='Other'))
    site = stations.loc[stations.month.eq(january)].set_index('station_id').construction_site
    orders['site'] = orders.station_id.map(site)
    paired_counts = orders.groupby(['station_id', 'band', 'period']).size().unstack(fill_value=0)
    changes = (paired_counts['Jan 15–27'] - paired_counts['Jan 2–14']).unstack(fill_value=0)
    both = changes['05–06'].lt(0) & changes['12–16'].gt(0)
    print(f'Stations with fewer morning orders and more midday orders: {both.sum()}')
    print(orders.groupby(['band', 'site', 'period']).size().unstack(fill_value=0).to_string())
    fees = orders.groupby(['band', 'period'])[
        ['total_elec_kwh', 'total_elec_fee', 'total_service_fee']].sum()
    fees['recorded_fee_per_kwh'] = (
        (fees.total_elec_fee + fees.total_service_fee) / fees.total_elec_kwh)
    print(fees.to_string())
    positive = orders.loc[orders.total_elec_kwh.gt(0)].assign(
        hour=hour, fee=orders.total_elec_fee + orders.total_service_fee)
    equipment = positive.groupby(['station_id', 'pile_id', 'hour', 'period']).agg(
        sessions=('fee', 'size'), fee=('fee', 'sum'), energy=('total_elec_kwh', 'sum'))
    equipment['rate'] = equipment.fee / equipment.energy
    matched = equipment[['sessions', 'energy', 'rate']].unstack('period').dropna()
    first, second = 'Jan 2–14', 'Jan 15–27'
    raw_rates, matched_rates, coverage = [], [], []
    for hours in (range(5, 7), range(12, 17)):
        pairs = matched.loc[matched.index.get_level_values('hour').isin(hours)]
        totals = positive.loc[positive.hour.isin(hours)].groupby('period').size()
        for minimum in (1, 5):
            sample = pairs.loc[pairs.sessions.min(axis=1).ge(minimum)]
            weights = sample.energy[first]
            rates = sample.rate.mul(weights, axis=0).sum() / weights.sum()
            median_change = (sample.rate[second] - sample.rate[first]).median()
            if minimum == 1:
                band = '05–06' if hours.start == 5 else '12–16'
                raw_rates.append(fees.loc[band, 'recorded_fee_per_kwh'].reindex([first, second]))
                matched_rates.append(rates.reindex([first, second]))
                coverage.append((sample.sessions.sum()/totals).reindex([first, second]).tolist())
            print(f'Hours {hours.start}–{hours.stop-1}, minimum {minimum}: {len(sample)} pairs; '
                  f'fixed-weight rates {rates.to_dict()}; median change {median_change:.6f}; '
                  f'order coverage {(sample.sessions.sum()/totals).to_dict()}')
    plot_fee_comparison(raw_rates, matched_rates, coverage, output)


if __name__ == '__main__':
    main()
