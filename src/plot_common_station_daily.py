"""Plot observed daily session starts at stations active in both study months."""
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter
import pandas as pd
import pyarrow.parquet as pq

from analyze_grid_followup import CALENDAR_SOURCE, MONTHS, ROOT, common_ids, day_types


def main():
    manifests = sorted((ROOT/'data/processed').glob('source_release2_clean1_*/cleaning_manifest.json'))
    if not manifests:
        raise SystemExit('Run rebuild_release_v2.py first.')
    manifest = manifests[-1]
    run_id = json.loads(manifest.read_text(encoding='utf-8'))['run_id']
    stations = pd.read_parquet(manifest.parent/'stations_monthly_clean.parquet')
    common = common_ids(stations, 'station_id')
    fixed = stations.loc[stations.station_id.isin(common)]
    expected = fixed.groupby('month').monthly_order_count.sum()
    batches = []
    for month in MONTHS:
        source = manifest.parent/f'orders_{month}_clean.parquet'
        for batch in pq.ParquetFile(source).iter_batches(
            batch_size=250_000, columns=['station_id', 'charge_start_time']
        ):
            orders = batch.to_pandas()
            orders = orders.loc[orders.station_id.isin(common)].copy()
            batches.append(orders.groupby([
                orders.charge_start_time.dt.normalize().rename('date'), 'station_id'
            ]).size())
    station_days = pd.concat(batches).groupby(level=['date', 'station_id']).sum()
    daily = station_days.groupby(level='date').sum()

    styles = {
        'workday': ('Ordinary workday', '#1d5a89', 'o'),
        'weekend': ('Ordinary weekend', '#64748b', 's'),
        'makeup': ('Make-up workday', '#7041a0', 'D'),
        'new_year': ("New Year's Day", '#bc751b', '^'),
        'spring': ('Spring Festival break', '#b73b31', 'o'),
    }
    fig, axes = plt.subplots(2, 1, figsize=(11, 7.3), sharex=True, sharey=True, layout='constrained')
    handles = {}
    for month, ax in zip(MONTHS, axes):
        dates = pd.date_range(month+'-01', periods=31)
        counts = daily.reindex(dates, fill_value=0)
        if counts.sum() != expected[month]:
            raise ValueError(f'Daily counts do not reconcile for {month}')
        categories = pd.Series(day_types(dates), index=dates)
        if month == MONTHS[0]:
            categories.loc['2025-01-01'] = 'new_year'
            categories.loc['2025-01-26'] = 'makeup'
            categories.loc['2025-01-28':'2025-01-31'] = 'spring'
            ax.axvspan(27.5, 31.5, color='#b73b31', alpha=.10)
            ax.text(.99, .93, 'Spring Festival: Jan 28–31 shown', transform=ax.transAxes,
                    ha='right', va='top', color='#8b2721')
        ax.plot(dates.day, counts, color='#9aafbd', linewidth=1.3, zorder=1)
        for key, (label, color, marker) in styles.items():
            mask = categories.eq(key)
            if mask.any():
                handles[key] = ax.scatter(dates.day[mask], counts[mask], c=color, marker=marker,
                                          s=32, label=label, zorder=3)
        ax.set(title=month, ylabel='Daily sessions', ylim=(0, daily.max()*1.18))
        ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
        ax.grid(axis='y', alpha=.2)
        print(month, f'total={counts.sum():,}', f'range={counts.min():,}–{counts.max():,}')
        for key, values in counts.groupby(categories):
            print(key, f'{len(values)} days', f'mean={values.mean():,.1f}',
                  f'range={values.min():,}–{values.max():,}')
    axes[-1].set(xlabel='Day of month', xticks=range(1, 32, 2), xlim=(.5, 31.5))
    fig.suptitle(f'Daily charging sessions at {len(common):,} common stations', fontweight='bold')
    fig.legend(handles=[handles[key] for key in styles], loc='outside lower center',
               ncols=3, frameon=False, fontsize=9)
    output = ROOT/'reports/figures/source_release2'/run_id/'grid_followup'
    output.mkdir(parents=True, exist_ok=True)
    fig.savefig(output/'04-common-station-daily-orders.png', dpi=180)
    plt.close(fig)
    active = station_days.groupby(level='date').size()
    dates = pd.DatetimeIndex([date for month in MONTHS
                              for date in pd.date_range(month+'-01', periods=31)])
    counts = daily.reindex(dates, fill_value=0)
    active = active.reindex(dates, fill_value=0)
    orders_per_active = counts / active.where(active.gt(0))
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, layout='constrained')
    for ax, series, label in zip(axes, (active, orders_per_active),
                                ('Stations with orders', 'Orders per active station')):
        for month in MONTHS:
            values = series.loc[month]
            ax.plot(values.index.day, values, 'o-', markersize=3, label=month)
        ax.axvspan(27.5, 31.5, color='#b73b31', alpha=.09, label='January Spring Festival')
        ax.set(ylabel=label, ylim=(0, series.max()*1.12))
        ax.grid(axis='y', alpha=.2)
    axes[0].legend(loc='lower right', frameon=False)
    axes[-1].set(xlabel='Day of month', xticks=range(1, 32, 2), xlim=(.5, 31.5))
    fig.suptitle(f'Daily orders at {len(common):,} common stations: coverage and intensity')
    fig.savefig(output/'05-common-station-daily-breakdown.png', dpi=180)
    plt.close(fig)
    ordinary = pd.Series(day_types(dates) == 'workday', index=dates)
    ordinary.loc['2025-01-26'] = False
    for start, end in [('2025-01-02', '2025-01-14'), ('2025-01-15', '2025-01-27'),
                       ('2025-01-01', '2025-01-31'), ('2025-07-01', '2025-07-31')]:
        selected = ordinary.loc[start:end].loc[lambda mask: mask].index
        print(start, end, f'days={len(selected)}, daily orders={counts.loc[selected].mean():.2f}, '
              f'active stations={active.loc[selected].mean():.2f}, '
              f'orders per active station-day={counts.loc[selected].sum()/active.loc[selected].sum():.2f}')
    print(CALENDAR_SOURCE)


if __name__ == '__main__':
    main()
