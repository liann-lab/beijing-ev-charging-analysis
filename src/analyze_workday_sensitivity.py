"""Compare July ordinary workdays with two January baselines at fixed stations."""
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from analyze_grid_followup import MONTHS, ROOT, common_ids, day_types


def main():
    manifest = sorted((ROOT/'data/processed').glob('source_release2_clean1_*/cleaning_manifest.json'))[-1]
    run_id = json.loads(manifest.read_text(encoding='utf-8'))['run_id']
    stations = pd.read_parquet(manifest.parent/'stations_monthly_clean.parquet')
    common = common_ids(stations, 'station_id')
    fixed = stations.loc[stations.month.eq(MONTHS[0]) & stations.station_id.isin(common)]
    station_grid = fixed.set_index('station_id').grid_id
    capacity = fixed.groupby('grid_id').charging_gun_num.sum()
    windows = {
        'early': pd.date_range('2025-01-02', '2025-01-14'),
        'late': pd.date_range('2025-01-15', '2025-01-27'),
        'july': pd.date_range('2025-07-01', '2025-07-31'),
    }
    date_labels = {}
    day_counts = {}
    for label, dates in windows.items():
        selected = dates[(day_types(dates) == 'workday') & (dates != pd.Timestamp('2025-01-26'))]
        date_labels.update(dict.fromkeys(selected, label))
        day_counts[label] = len(selected)

    batches = []
    for month in MONTHS:
        source = manifest.parent/f'orders_{month}_clean.parquet'
        for batch in pq.ParquetFile(source).iter_batches(
            batch_size=250_000, columns=['station_id', 'charge_start_time', 'duration_min']
        ):
            orders = batch.to_pandas()
            orders['window'] = orders.charge_start_time.dt.normalize().map(date_labels)
            orders['grid_id'] = orders.station_id.map(station_grid)
            batches.append(orders.groupby(['window', 'grid_id']).agg(
                orders=('duration_min', 'size'), minutes=('duration_min', 'sum')))
    totals = pd.concat(batches).groupby(level=['window', 'grid_id']).sum()

    daily, utilization, order_counts = {}, {}, {}
    for label, days in day_counts.items():
        rows = totals.loc[label].reindex(capacity.index, fill_value=0)
        order_counts[label] = rows.orders
        daily[label] = rows.orders / days
        utilization[label] = 100 * rows.minutes / (capacity * days * 1440)
        print(label, days, int(rows.orders.sum()), daily[label].sum(),
              100 * rows.minutes.sum() / (capacity.sum() * days * 1440))
    observed = pd.DataFrame(order_counts).gt(0).all(axis=1)
    compared = pd.DataFrame(index=capacity.index[observed])
    for label in ('early', 'late'):
        compared[f'daily_delta_{label}'] = daily['july'] - daily[label]
        compared[f'util_delta_{label}'] = utilization['july'] - utilization[label]
    print('fixed stations/grids and grids observed in all windows:', len(fixed), len(capacity), len(compared))
    discordant = {}
    for label in ('early', 'late'):
        order_change, util_change = compared[f'daily_delta_{label}'], compared[f'util_delta_{label}']
        discordant[label] = order_change.gt(0) & util_change.lt(-1e-9)
        print(label, 'orders up', order_change.gt(0).sum(), 'util up', util_change.gt(1e-9).sum(),
              'discordant', discordant[label].sum(), 'median pp', util_change.median())
    x, y = compared.util_delta_early, compared.util_delta_late
    flips = (x.gt(1e-9) & y.lt(-1e-9)) | (x.lt(-1e-9) & y.gt(1e-9))
    print('utilization sign flips', flips.sum(), 'discordant in both',
          (discordant['early'] & discordant['late']).sum())

    fig, ax = plt.subplots(figsize=(8.4, 7), layout='constrained')
    ax.scatter(x[~flips], y[~flips], s=10, alpha=.4, color='#24628b', label='No reversal')
    ax.scatter(x[flips], y[flips], s=17, alpha=.82, color='#b65321',
               label=f'Opposite signs ({flips.sum():,})')
    low, high = min(x.min(), y.min(), 0), max(x.max(), y.max(), 0)
    ax.plot([low, high], [low, high], color='#a9a9a9', linestyle='--', linewidth=.9)
    ax.axhline(0, color='#606b76', linewidth=.8)
    ax.axvline(0, color='#606b76', linewidth=.8)
    padding = .04 * (high-low)
    ax.set(xlabel='July minus Jan 2–14 (percentage points)',
           ylabel='July minus Jan 15–27 (percentage points)',
           xlim=(low-padding, high+padding), ylim=(low-padding, high+padding), aspect='equal')
    ax.legend(frameon=False, loc='upper left')
    fig.suptitle('Does the January baseline change the July utilization comparison?\n'
                 f'{len(compared):,} grids with recorded orders in all three windows')
    fig.supxlabel('Ordinary workdays only; common-station capacity fixed. '
                  'Whole session duration assigned to its start date.', fontsize=9)
    output = ROOT/'reports/figures/source_release2'/run_id/'grid_followup'
    output.mkdir(parents=True, exist_ok=True)
    fig.savefig(output/'09-january-baseline-sensitivity.png', dpi=180)
    plt.close(fig)
    classes = pd.Series(np.select(
        [x.gt(1e-9)&y.gt(1e-9), x.lt(-1e-9)&y.lt(-1e-9), flips],
        ['Higher in both', 'Lower in both', 'Reversal'], default='Includes tie'), index=compared.index)
    xy = compared.index.to_series().str.split('_', expand=True).astype(int)
    fig, ax = plt.subplots(figsize=(8, 7), layout='constrained')
    for label, color in [('Higher in both', '#b5462e'), ('Lower in both', '#24628b'),
                         ('Reversal', '#c89a27'), ('Includes tie', '#888888')]:
        mask = classes.eq(label)
        ax.scatter(xy.loc[mask, 0], xy.loc[mask, 1], s=8, marker='s', color=color,
                   label=f'{label} ({mask.sum():,})', linewidths=0)
    ax.set(xlabel='Anonymized grid X', ylabel='Anonymized grid Y', aspect='equal',
           title='July utilization direction under two January workday baselines')
    ax.legend(frameon=False, fontsize=8)
    fig.savefig(output/'10-grid-stability-map.png', dpi=180)
    plt.close(fig)
    bad = fixed.groupby('grid_id')[['flag_gun_component_mismatch',
                                    'flag_pile_component_mismatch']].any().any(axis=1)
    enough = pd.DataFrame(order_counts).min(axis=1).ge(30).reindex(compared.index)
    eligible = enough & ~bad.reindex(compared.index)
    stable = discordant['early'] & discordant['late'] & eligible
    reversal = flips & eligible
    if not stable.any() or not reversal.any():
        raise ValueError('No sufficiently observed consistent-capacity case')
    case_ids = [compared.loc[stable, 'daily_delta_late'].idxmax(),
                (x-y).abs().loc[reversal].idxmax()]
    fig, axes = plt.subplots(2, 3, figsize=(12, 6), layout='constrained')
    result = {'classes': classes.value_counts().to_dict(), 'cases': {}}
    for row, grid_id in enumerate(case_ids):
        values = totals.xs(grid_id, level='grid_id').reindex(['early', 'late', 'july'])
        guns = capacity.loc[grid_id]
        sessions = values.orders.to_numpy()
        days = np.array([day_counts[k] for k in values.index])
        means = values.minutes.to_numpy()/sessions
        rates = sessions/days/guns
        util = rates*means/1440*100
        result['cases'][grid_id] = dict(guns=float(guns), orders=sessions.tolist(),
                                       sessions_per_gun_day=rates.tolist(),
                                       mean_minutes=means.tolist(), utilization_percent=util.tolist())
        for col, (numbers, title) in enumerate(zip([rates, means, util],
                ['Sessions / gun / day', 'Minutes / session', 'Utilization (%)'])):
            ax = axes[row, col]
            bars = ax.bar(['Jan early', 'Jan late', 'July'], numbers,
                          color=['#8096a9', '#24628b', '#b5462e'])
            ax.bar_label(bars, fmt='%.2f', fontsize=8)
            ax.set(title=f'{grid_id} | {title}', ylim=(0, max(numbers)*1.22))
    fig.suptitle('Fixed-capacity cases | utilization (%) = sessions/gun/day × minutes/session ÷ 1,440 × 100')
    fig.savefig(output/'11-grid-case-decomposition.png', dpi=180)
    plt.close(fig)
    local = ROOT/'data/processed/grid_stability'
    local.mkdir(parents=True, exist_ok=True)
    (local/'case_summary.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
