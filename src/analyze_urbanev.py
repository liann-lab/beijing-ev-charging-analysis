"""Audit capacities and plot UrbanEV pooled occupancy from processed snapshots."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter

ROOT = Path(__file__).resolve().parents[1]


def main():
    base = ROOT/'data/raw/UrbanEV数据/UrbanEVDataset'
    meta = pd.read_csv(base/'20220901-20230228_station-raw/station_information.csv').set_index('station_id')
    files = sorted((base/'20220901-20230228_station-processed').glob('*.csv'))
    if not files:
        raise SystemExit('Extract UrbanEV data first.')
    time = pd.date_range('2022-09-01', '2023-02-28 23:55', freq='5min')
    busy, capacity = np.zeros(len(time)), np.zeros(len(time))
    review = dict(rows=0, zero_capacity_rows=0, variable_capacity_stations=0,
                  metadata_capacity_mismatch_stations=0, negative_price_rows=0,
                  negative_duration_volume_rows=0)
    fields = ['e_price', 's_price', 'duration', 'volume']
    bounds = {field: [np.inf, -np.inf] for field in fields}
    for i, file in enumerate(files):
        d = pd.read_csv(file)
        if not pd.DatetimeIndex(pd.to_datetime(d.time)).equals(time):
            raise ValueError(f'Time axis mismatch: {file.name}')
        total = d.busy + d.idle
        if d[['busy', 'idle']].lt(0).any().any():
            raise ValueError(f'Negative occupancy: {file.name}')
        busy += d.busy.to_numpy()
        capacity += total.to_numpy()
        review['rows'] += len(d)
        review['zero_capacity_rows'] += int(total.eq(0).sum())
        review['variable_capacity_stations'] += int(total.nunique() > 1)
        review['metadata_capacity_mismatch_stations'] += int(
            total.sub(meta.loc[int(file.stem), 'charge_count']).abs().gt(1e-6).any())
        review['negative_price_rows'] += int(d[['e_price', 's_price']].lt(0).any(axis=1).sum())
        review['negative_duration_volume_rows'] += int(d[['duration', 'volume']].lt(0).any(axis=1).sum())
        for field in fields:
            bounds[field] = [min(bounds[field][0], float(d[field].min())),
                             max(bounds[field][1], float(d[field].max()))]
        if i % 200 == 0:
            print(f'Checked {i+1}/{len(files)}', flush=True)
    totals = pd.DataFrame({'busy': busy, 'capacity': capacity}, index=time)
    if totals.capacity.le(0).any():
        raise ValueError('Nonpositive pooled capacity.')
    totals['month'] = time.strftime('%Y-%m')
    totals['weekday'] = time.dayofweek < 5
    totals['hour'] = time.hour
    grouped = totals.groupby(['month', 'weekday', 'hour'])[['busy', 'capacity']].sum()
    grouped['occupancy'] = grouped.busy / grouped.capacity
    monthly = totals.groupby('month')[['busy', 'capacity']].sum()
    review.update(field_ranges=bounds, processed_stations=len(files),
                  monthly_pooled_occupancy=(monthly.busy/monthly.capacity).to_dict())
    local = ROOT/'data/processed/urbanev_audit'
    local.mkdir(parents=True, exist_ok=True)
    (local/'occupancy_review.json').write_text(json.dumps(review, indent=2)+'\n', encoding='utf-8')
    totals.to_parquet(local/'pooled_snapshots.parquet')
    output = ROOT/'reports/figures/urbanev'
    output.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 3, figsize=(12, 6.5), sharex=True, sharey=True, layout='constrained')
    for ax, month in zip(axes.flat, monthly.index):
        for weekday, label, color in [(True, 'Mon–Fri', '#24628b'), (False, 'Sat–Sun', '#b65321')]:
            part = grouped.loc[(month, weekday)]
            ax.plot(part.index, part.occupancy, color=color, label=label)
        ax.set(title=month, xlabel='Hour', ylabel='Pooled busy share', xticks=range(0, 24, 6))
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.grid(alpha=.18)
    axes[0, 0].legend(frameon=False)
    fig.suptitle('UrbanEV | snapshot occupancy by month and calendar weekday')
    fig.supxlabel('Sum of busy piles / sum of busy + idle across snapshots and stations. '
                  'Processed and imputed data; holidays not reclassified.', fontsize=9)
    fig.savefig(output/'02-monthly-hourly-occupancy.png', dpi=180)
    plt.close(fig)
    selected = meta.loc[[int(file.stem) for file in files]]
    fig, ax = plt.subplots(figsize=(9, 6), layout='constrained')
    ax.scatter(meta.longitude, meta.latitude, s=5, color='#c5cbd1', label='Metadata stations')
    points = ax.scatter(selected.longitude, selected.latitude, s=9, c=selected.charge_count,
                        cmap='viridis', norm=matplotlib.colors.LogNorm(), linewidths=0)
    ax.set(xlabel='Longitude (GCJ-02)', ylabel='Latitude (GCJ-02)',
           title=f'UrbanEV | {len(selected):,} processed stations; {len(meta):,} metadata stations')
    ax.set_aspect(1/np.cos(np.deg2rad(selected.latitude.mean())))
    fig.colorbar(points, ax=ax, label='Metadata pile count (log scale)')
    ax.legend(frameon=False)
    fig.savefig(output/'01-station-distribution.png', dpi=180)
    plt.close(fig)
    print(json.dumps(review, indent=2), flush=True)


if __name__ == '__main__':
    main()
