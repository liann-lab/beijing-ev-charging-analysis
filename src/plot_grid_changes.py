"""Compare July minus January on grids with observed sessions in both months."""
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import SymLogNorm
from matplotlib.ticker import StrMethodFormatter
import pandas as pd

from analyze_grid_sensitivity import MONTHS, ROOT, aggregate


def describe(changes):
    orders, util = changes.delta_orders, changes.delta_util_pp
    return {
        'grids': len(changes),
        'orders_up': int(orders.gt(0).sum()),
        'util_up': int(util.gt(0).sum()),
        'both_up': int((orders.gt(0) & util.gt(0)).sum()),
        'orders_up_util_down': int((orders.gt(0) & util.lt(0)).sum()),
        'orders_down_util_up': int((orders.lt(0) & util.gt(0)).sum()),
        'both_down': int((orders.lt(0) & util.lt(0)).sum()),
        'either_unchanged': int((orders.eq(0) | util.eq(0)).sum()),
        'median_orders_change': float(orders.median()),
        'median_util_change_pp': float(util.median()),
        'spearman': float(orders.rank().corr(util.rank())),
    }


def main():
    manifest_path = sorted((ROOT/'data/processed').glob(
        'source_release2_clean1_*/cleaning_manifest.json'))[-1]
    run_id = json.loads(manifest_path.read_text(encoding='utf-8'))['run_id']
    stations = pd.read_parquet(manifest_path.parent/'stations_monthly_clean.parquet')
    grid = aggregate(stations.loc[stations.month.isin(MONTHS)])
    jan, july = [grid.loc[grid.month.eq(month)].set_index('grid_id') for month in MONTHS]
    changes = jan.join(july.drop(columns=['x', 'y']), how='inner', lsuffix='_jan', rsuffix='_jul')
    if not changes[['utilization_jan', 'utilization_jul']].apply(
        lambda column: column.between(0, 1)).all().all():
        raise ValueError('Invalid utilization on a paired grid')
    changes['delta_orders'] = changes.orders_jul - changes.orders_jan
    changes['delta_util_pp'] = 100 * (changes.utilization_jul - changes.utilization_jan)
    output = ROOT/'reports/figures/source_release2'/run_id/'grid_changes'
    output.mkdir(parents=True, exist_ok=True)

    coordinates = grid[['x', 'y']]
    q1, q3 = coordinates.quantile(.25), coordinates.quantile(.75)
    spread = 10 * (q3 - q1)
    xy = changes[['x', 'y']]
    visible = changes.loc[xy.ge(q1 - spread).all(axis=1) & xy.le(q3 + spread).all(axis=1)]
    for metric, label, linear, filename in [
        ('delta_orders', 'Change in sessions', 100, '01-orders-change-map.png'),
        ('delta_util_pp', 'Change in utilization (percentage points)', 1, '02-utilization-change-map.png'),
    ]:
        limit = max(linear, changes[metric].abs().max())
        fig, ax = plt.subplots(figsize=(8, 7), layout='constrained')
        points = ax.scatter(visible.x, visible.y, c=visible[metric], marker='s', s=5,
                            cmap='RdBu_r', norm=SymLogNorm(linear, vmin=-limit, vmax=limit),
                            linewidths=.15, edgecolors='#999999')
        ax.set(xlabel='Anonymized grid X', ylabel='Anonymized grid Y', aspect='equal')
        fig.suptitle(f'{label}: July minus January 2025\n{len(visible):,} of {len(changes):,} paired grids shown')
        fig.colorbar(points, ax=ax, shrink=.77, label=label,
                     format=StrMethodFormatter('{x:,.0f}'))
        fig.supxlabel(f'Red = increase; blue = decrease. Symmetric log color scale, linear within ±{linear}.\n'
                      'Blank cells are outside the paired sample. Coordinates are relative.', fontsize=9)
        fig.savefig(output/filename, dpi=180)
        plt.close(fig)

    orders, util = changes.delta_orders, changes.delta_util_pp
    groups = [
        (orders.gt(0) & util.gt(0), 'Both increased', '#b5462e'),
        (orders.gt(0) & util.lt(0), 'Sessions up, utilization down', '#623e96'),
        (orders.lt(0) & util.gt(0), 'Sessions down, utilization up', '#228674'),
        (orders.lt(0) & util.lt(0), 'Both decreased', '#3674aa'),
        (orders.eq(0) | util.eq(0), 'Either unchanged', '#666666'),
    ]
    fig, ax = plt.subplots(figsize=(9, 6), layout='constrained')
    ax.axvline(0, color='#777777', linewidth=.8)
    ax.axhline(0, color='#777777', linewidth=.8)
    for mask, label, color in groups:
        ax.scatter(orders[mask], util[mask], color=color, label=f'{label} ({mask.sum():,})',
                   s=16, alpha=.62, linewidths=0)
    ax.set_xscale('symlog', linthresh=100)
    ax.xaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    ax.set(xlabel='Change in sessions (symmetric log axis, linear within ±100)',
           ylabel='Change in utilization (percentage points)')
    ax.legend(loc='best', fontsize=9)
    fig.suptitle(f'Sessions and utilization: July minus January 2025\n{len(changes):,} paired grids')
    fig.savefig(output/'03-orders-vs-utilization-change.png', dpi=180)
    plt.close(fig)

    result = {
        'run_id': run_id,
        'january_only_grids': len(jan) - len(changes),
        'july_only_grids': len(july) - len(changes),
        'outside_map': changes.index.difference(visible.index).tolist(),
        'all_paired': describe(changes),
        'at_least_five_guns_both_months': describe(changes.loc[
            changes.guns_jan.ge(5) & changes.guns_jul.ge(5)]),
        'largest_session_increases': changes.delta_orders.nlargest(5).to_dict(),
        'largest_utilization_increases_pp': util.nlargest(5).to_dict(),
        'largest_session_increases_with_utilization_decline': changes.loc[
            orders.gt(0) & util.lt(0)].nlargest(5, 'delta_orders')[
                ['delta_orders', 'delta_util_pp', 'guns_jan', 'guns_jul',
                 'orders_jan', 'orders_jul', 'duration_min_jan', 'duration_min_jul']
            ].to_dict(orient='index'),
    }
    (output/'summary.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
