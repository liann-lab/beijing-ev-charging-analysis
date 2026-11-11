"""Complete the paired-grid and fixed-station comparisons for January and July."""
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import SymLogNorm
from matplotlib.ticker import StrMethodFormatter
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from analyze_grid_sensitivity import MONTHS, ROOT, aggregate
from compare_winter_summer import common_ids

JAN, JUL = MONTHS
METRICS = ['orders', 'energy_kwh', 'duration_min', 'guns', 'station_count', 'utilization']
CALENDAR_SOURCE = 'https://www.gov.cn/zhengce/zhengceku/202411/content_6986383.htm'


def day_types(dates):
    dates = pd.DatetimeIndex(dates).normalize()
    types = np.where(dates.dayofweek < 5, 'workday', 'weekend')
    holiday = dates == pd.Timestamp('2025-01-01')
    holiday |= (dates >= pd.Timestamp('2025-01-28')) & (dates <= pd.Timestamp('2025-01-31'))
    types[holiday] = 'holiday'
    types[dates == pd.Timestamp('2025-01-26')] = 'workday'
    return types


def pairs(grid):
    months = [grid.loc[grid.month.eq(month)].set_index('grid_id')[METRICS] for month in MONTHS]
    result = months[0].join(months[1], how='inner', lsuffix='_jan', rsuffix='_jul')
    result['delta_orders'] = result.orders_jul - result.orders_jan
    result['delta_energy_kwh'] = result.energy_kwh_jul - result.energy_kwh_jan
    result['delta_util_pp'] = (result.utilization_jul - result.utilization_jan) * 100
    return result


def direction(delta):
    return pd.Series(np.select([delta.gt(1e-9), delta.lt(-1e-9), delta.notna()],
                               ['up', 'down', 'flat'], default='unpaired'), index=delta.index)


def metrics_for_case(row):
    return {
        'orders': [int(row.orders_jan), int(row.orders_jul)],
        'guns': [int(row.guns_jan), int(row.guns_jul)],
        'duration_min': [row.duration_min_jan, row.duration_min_jul],
        'mean_minutes': [row.duration_min_jan / row.orders_jan, row.duration_min_jul / row.orders_jul],
        'util_percent': [100 * row.utilization_jan, 100 * row.utilization_jul],
        'delta_util_pp': row.delta_util_pp,
    }


def read_order_breakdowns(clean, fixed, case_rows):
    station_site = fixed.drop_duplicates('station_id').set_index('station_id').construction_site
    case_grid = case_rows.drop_duplicates('station_id').set_index('station_id').grid_id
    fixed_batches, case_batches = [], []
    for file_month in MONTHS:
        source = clean / f'orders_{file_month}_clean.parquet'
        for batch in pq.ParquetFile(source).iter_batches(
            batch_size=250_000, columns=['station_id', 'charge_start_time', 'total_elec_kwh']
        ):
            data = batch.to_pandas()
            data['month'] = data.charge_start_time.dt.strftime('%Y-%m')
            data = data.loc[data.month.isin(MONTHS)].copy()
            data['hour'] = data.charge_start_time.dt.hour
            observed_cases = data.loc[data.station_id.isin(case_grid.index)].copy()
            observed_cases['grid_id'] = observed_cases.station_id.map(case_grid)
            observed_cases['fixed'] = observed_cases.station_id.isin(station_site.index)
            case_batches.append(observed_cases.groupby(['grid_id', 'month', 'hour', 'fixed']).size())
            cohort = data.loc[data.station_id.isin(station_site.index)].copy()
            cohort['site'] = cohort.station_id.map(station_site).fillna('未分类')
            cohort['day_type'] = day_types(cohort.charge_start_time)
            fixed_batches.append(cohort.groupby(['month', 'hour', 'day_type', 'site']).agg(
                orders=('station_id', 'size'), energy_kwh=('total_elec_kwh', 'sum')))
    fixed_totals = pd.concat(fixed_batches).groupby(level=[0, 1, 2, 3]).sum()
    case_hours = pd.concat(case_batches).groupby(level=[0, 1, 2, 3]).sum()
    return fixed_totals, case_hours


def contribution(totals, dimension):
    table = totals.groupby(level=[dimension, 'month']).sum().unstack(fill_value=0)
    table.columns = [f'{metric}_{month}' for metric, month in table.columns]
    for metric in ('orders', 'energy_kwh'):
        table[f'delta_{metric}'] = table[f'{metric}_{JUL}'] - table[f'{metric}_{JAN}']
    return table.sort_values('delta_orders', ascending=False)


def plot_energy(grid, changes, output):
    xy = grid.set_index('grid_id').loc[lambda frame: ~frame.index.duplicated(), ['x', 'y']]
    plotted = changes.join(xy)
    limit = max(1_000, plotted.delta_energy_kwh.abs().max())
    fig, ax = plt.subplots(figsize=(8, 7), layout='constrained')
    artist = ax.scatter(plotted.x, plotted.y, c=plotted.delta_energy_kwh, marker='s', s=5,
                        cmap='RdBu_r', norm=SymLogNorm(1_000, vmin=-limit, vmax=limit),
                        linewidths=.15, edgecolors='#999999')
    ax.set(xlabel='Anonymized grid X', ylabel='Anonymized grid Y', aspect='equal')
    fig.suptitle(f'Change in charging energy: July minus January 2025\n{len(plotted):,} paired grids')
    ticks = [value for value in (1_000, 10_000, 100_000, 1_000_000) if value <= limit]
    fig.colorbar(artist, ax=ax, shrink=.77, label='Change in charging energy (kWh)',
                 ticks=[-value for value in reversed(ticks)] + [0] + ticks,
                 format=StrMethodFormatter('{x:,.0f}'))
    fig.supxlabel('Red = increase; blue = decrease. Symmetric log color scale, linear within ±1,000 kWh.',
                  fontsize=9)
    fig.savefig(output/'01-energy-change-map.png', dpi=180)
    plt.close(fig)


def plot_contributions(tables, cases, output):
    hour = tables['hour'].sort_index()
    fig, ax = plt.subplots(figsize=(9, 4), layout='constrained')
    ax.bar(hour.index, hour.delta_orders, color=np.where(hour.delta_orders >= 0, '#b5462e', '#3674aa'))
    ax.set(xticks=range(0, 24, 2), xlabel='Session start hour', ylabel='Additional sessions',
           title='Fixed stations: July minus January session counts by start hour')
    fig.savefig(output/'02-hourly-contribution.png', dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(len(cases), 1, figsize=(8, 2.1 * len(cases)),
                             sharex=True, sharey=True, layout='constrained', squeeze=False)
    for ax, (grid_id, case) in zip(axes[:, 0], cases.items()):
        for month, label in zip(MONTHS, ('January', 'July')):
            counts = np.array(case['hourly_observed'][month])
            ax.plot(range(24), 100 * counts / counts.sum(), label=label)
        ax.set(title=grid_id, ylabel='Sessions (%)')
    axes[0, 0].legend(loc='upper right')
    axes[-1, 0].set(xlabel='Session start hour', xticks=range(0, 24, 2))
    fig.suptitle('Case grids: within-month share of sessions by start hour')
    fig.savefig(output/'03-case-hour-profiles.png', dpi=180)
    plt.close(fig)


def main():
    manifest = sorted((ROOT/'data/processed').glob('source_release2_clean1_*/cleaning_manifest.json'))[-1]
    clean = manifest.parent
    run_id = json.loads(manifest.read_text(encoding='utf-8'))['run_id']
    output = ROOT/'reports/figures/source_release2'/run_id/'grid_followup'
    output.mkdir(parents=True, exist_ok=True)
    details = ROOT/'data/processed'/f'grid_followup_{run_id}'
    details.mkdir(parents=True, exist_ok=True)

    stations = pd.read_parquet(clean/'stations_monthly_clean.parquet')
    stations = stations.loc[stations.month.isin(MONTHS)].copy()
    fixed = stations.loc[stations.station_id.isin(common_ids(stations, 'station_id'))]
    mismatch = stations.flag_pile_component_mismatch | stations.flag_gun_component_mismatch
    grid = aggregate(stations)
    observed, paired_fixed = pairs(grid), pairs(aggregate(fixed))
    observed_ok = pairs(aggregate(stations.loc[~mismatch]))
    fixed_ok = pairs(aggregate(fixed.loc[~mismatch.loc[fixed.index]]))
    comparison = observed.join(paired_fixed.add_prefix('fixed_'))
    comparison['observed_direction'] = direction(comparison.delta_util_pp)
    comparison['fixed_direction'] = direction(comparison.fixed_delta_util_pp)
    transitions = pd.crosstab(comparison.observed_direction, comparison.fixed_direction)
    opposite = comparison.loc[
        comparison.observed_direction.eq('up') & comparison.fixed_direction.eq('down')
        | comparison.observed_direction.eq('down') & comparison.fixed_direction.eq('up')]
    discordant = comparison.loc[comparison.delta_orders.gt(0) & comparison.observed_direction.eq('down')]
    persistent = discordant.fixed_delta_orders.gt(0) & discordant.fixed_direction.eq('down')
    sensitivity = (discordant.delta_util_pp - observed_ok.delta_util_pp.reindex(discordant.index)).abs()
    affected_cases = sensitivity.loc[sensitivity.gt(1e-9)].nlargest(1).index
    case_ids = list(dict.fromkeys([
        discordant.delta_orders.idxmax(),
        *discordant.loc[persistent].delta_orders.nlargest(2).index,
        *discordant.loc[~persistent & discordant.fixed_direction.eq('up')].delta_orders.nlargest(2).index,
        *affected_cases,
    ]))
    case_rows = stations.loc[stations.grid_id.isin(case_ids)]
    totals, hourly_cases = read_order_breakdowns(clean, fixed, case_rows)
    expected = fixed.groupby('month').agg(
        orders=('monthly_order_count', 'sum'), energy_kwh=('monthly_total_elec_kwh', 'sum'))
    actual = totals.groupby(level='month').sum()
    if not actual.orders.equals(expected.orders) or not np.allclose(actual.energy_kwh, expected.energy_kwh,
                                                                     rtol=0, atol=.001):
        raise ValueError('Fixed-station orders or energy do not reconcile to the monthly table')
    tables = {key: contribution(totals, key) for key in ('hour', 'day_type', 'site')}
    days = {month: pd.Series(day_types(pd.date_range(month+'-01', periods=31))).value_counts().to_dict()
            for month in MONTHS}
    for month in MONTHS:
        day_denominator = pd.Series(days[month]).reindex(tables['day_type'].index)
        tables['day_type'][f'days_{month}'] = day_denominator.fillna(0).astype(int)
        tables['day_type'][f'orders_per_day_{month}'] = (
            tables['day_type'][f'orders_{month}'] / day_denominator)

    one_month = stations.loc[~stations.station_id.isin(fixed.station_id)]
    local = one_month.loc[one_month.grid_id.isin(opposite.index.union(pd.Index(case_ids)))]
    membership = {
        grid_id: {
            month: rows.loc[rows.month.eq(month), [
                'station_id', 'charging_gun_num', 'monthly_order_count', 'monthly_duration_min',
                'flag_pile_component_mismatch', 'flag_gun_component_mismatch']].to_dict('records')
            for month in MONTHS
        }
        for grid_id, rows in local.groupby('grid_id')
    }
    cases = {}
    for grid_id in case_ids:
        case = {'single_month_stations': membership.get(grid_id, {})}
        for name, frame in [('observed', observed), ('fixed', paired_fixed),
                            ('observed_consistent', observed_ok), ('fixed_consistent', fixed_ok)]:
            case[name] = metrics_for_case(frame.loc[grid_id]) if grid_id in frame.index else None
        case['flagged_stations'] = sorted(case_rows.loc[case_rows.grid_id.eq(grid_id) & mismatch,
                                                      'station_id'].unique())
        counts = hourly_cases.loc[grid_id]
        case['hourly_observed'], case['hourly_fixed'] = {}, {}
        for i, month in enumerate(MONTHS):
            month_counts = counts.loc[month]
            for name, selection in [('hourly_observed', month_counts),
                                    ('hourly_fixed', month_counts[month_counts.index.get_level_values('fixed')])]:
                case[name][month] = selection.groupby(level='hour').sum().reindex(range(24), fill_value=0).tolist()
            if sum(case['hourly_observed'][month]) != case['observed']['orders'][i]:
                raise ValueError(f'Case order counts do not reconcile for {grid_id} in {month}')
            if case['fixed'] and sum(case['hourly_fixed'][month]) != case['fixed']['orders'][i]:
                raise ValueError(f'Fixed case order counts do not reconcile for {grid_id} in {month}')
        cases[grid_id] = case

    plot_energy(grid, observed, output)
    plot_contributions(tables, cases, output)
    comparison.reset_index().to_json(details/'paired-grid-results.json', orient='records',
                                      indent=2, force_ascii=False, double_precision=12)
    grid.loc[~grid.grid_id.isin(observed.index), ['grid_id', 'month', *METRICS]].to_json(
        details/'single-month-grids.json', orient='records', indent=2, double_precision=12)
    result = {
        'run_id': run_id, 'calendar_source': CALENDAR_SOURCE, 'day_counts': days,
        'fixed_station_count': int(fixed.station_id.nunique()),
        'energy_change': {'up': int(observed.delta_energy_kwh.gt(0).sum()),
                          'down': int(observed.delta_energy_kwh.lt(0).sum()),
                          'median_kwh': float(observed.delta_energy_kwh.median()),
                          'largest_increase': observed.delta_energy_kwh.nlargest(5).to_dict()},
        'directions': transitions.to_dict(orient='index'),
        'reversed_grids': opposite[['delta_util_pp', 'fixed_delta_util_pp']].to_dict('index'),
        'discordant_grids': {'observed': len(discordant), 'still_discordant': int(persistent.sum()),
                             'unpaired': int(discordant.fixed_direction.eq('unpaired').sum()),
                             'fixed_directions': discordant.fixed_direction.value_counts().to_dict()},
        'single_month_stations_in_reversed_grids': {key: membership.get(key, {}) for key in opposite.index},
        'cases': cases,
        'contributions': {key: table.astype(object).where(table.notna(), None).to_dict(orient='index')
                          for key, table in tables.items()},
    }
    (details/'summary.json').write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)+'\n',
                                       encoding='utf-8')
    print(output)
    print(details)


if __name__ == '__main__':
    main()
