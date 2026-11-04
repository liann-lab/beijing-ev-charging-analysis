"""Clean linked release-v2 orders and reconstruct station-month measures from them."""
import calendar
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from audit_release_v2 import SOURCE, ROOT, digest


def monthly_utilization(duration_minutes, guns, month):
    year, number = map(int, month.split('-'))
    return duration_minutes / (guns.replace(0, np.nan) * 1440 * calendar.monthrange(year, number)[1])


def main():
    run = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = ROOT/'data/processed'/f'source_release2_clean1_{run}'
    out.mkdir(parents=True, exist_ok=False)
    station_hash = digest(SOURCE/'stations_public.parquet')
    stations = pd.read_parquet(SOURCE/'stations_public.parquet')
    if stations.station_id.isna().any() or stations.station_id.duplicated().any():
        raise ValueError('Invalid station keys')
    stations['construction_site_raw'] = stations.construction_site
    stations['construction_site'] = stations.construction_site.replace({'居民区': '居住区'})
    stations['flag_pile_component_mismatch'] = stations.piles_num.ne(stations.dc_piles_num+stations.ac_piles_num)
    stations['flag_gun_component_mismatch'] = stations.charging_gun_num.ne(stations.dc_charging_gun_num+stations.ac_charging_gun_num)
    pq.write_table(pa.Table.from_pandas(stations, preserve_index=False), out/'stations_clean.parquet')
    report = {'source_release': 2, 'cleaning_version': 1, 'run_id': run,
              'output_directory': str(out.relative_to(ROOT)), 'source_sha256': {}, 'orders': {},
              'rules': {'missing': 'any missing original order field', 'extreme': 'energy > 1000 kWh AND energy > rated power * duration_hours * 1.05',
                        'time': 'whole session assigned to start month; June partial observations retained',
                        'utilization': 'sum recorded duration / (static total guns * 24 hours * days); no occupancy overlap correction',
                        'not_applied': 'No arbitrary station deduplication, 200kWh cutoff or Z-score deletion; these remain flags.'}}
    aggregates = []
    for month in ['2025-01', '2025-07']:
        source = SOURCE/f'orders_{month}_public.parquet'
        report['source_sha256'][source.name] = digest(source)
        writers = {}
        counts, totals = Counter(), Counter()
        offset = 0
        try:
            for batch in pq.ParquetFile(source).iter_batches(batch_size=250000):
                d = batch.to_pandas()
                missing = d.isna().any(axis=1)
                cap = d.total_elec_kwh.gt(d.rated_gun_power_kw * d.duration_min / 60 * 1.05)
                extreme = d.total_elec_kwh.gt(1000) & cap
                d['source_file'], d['source_row'], d['file_month'] = source.name, np.arange(offset, offset+len(d)), month
                offset += len(d)
                d['analysis_month'] = d.charge_start_time.dt.strftime('%Y-%m')
                d['flag_missing_original_field'], d['flag_energy_capacity_mismatch'] = missing, cap
                d['flag_energy_over_200'] = d.total_elec_kwh.gt(200)
                d['exclusion_reason'] = np.select([missing & extreme, missing, extreme],
                    ['missing_original_field;extreme_energy', 'missing_original_field', 'extreme_energy'], default='')
                d = d.merge(stations[['station_id','construction_site','geocoding']], on='station_id', how='left', validate='many_to_one', indicator=True)
                if d['_merge'].ne('both').any():
                    raise ValueError('Unmatched station: stop instead of silently dropping')
                d = d.drop(columns='_merge')
                excluded = d.exclusion_reason.ne('')
                counts.update({'input':len(d), 'excluded_missing':int(missing.sum()), 'excluded_extreme':int(extreme.sum()),
                               'rule_overlap':int((missing & extreme).sum()), 'excluded':int(excluded.sum()), 'clean':int((~excluded).sum())})
                totals['raw_energy_kwh'] += float(d.total_elec_kwh.sum())
                totals['excluded_energy_kwh'] += float(d.loc[excluded,'total_elec_kwh'].sum())
                totals['clean_energy_kwh'] += float(d.loc[~excluded,'total_elec_kwh'].sum())
                full_table = pa.Table.from_pandas(d, preserve_index=False)
                for label, mask in [('clean',~excluded),('excluded',excluded)]:
                    table = full_table.filter(pa.array(mask.to_numpy()))
                    if label not in writers:
                        writers[label] = pq.ParquetWriter(out/f'orders_{month}_{label}.parquet', table.schema, compression='snappy')
                    writers[label].write_table(table)
                kept = d.loc[~excluded]
                aggregates.append(kept.groupby(['analysis_month','station_id'],as_index=False).agg(
                    monthly_order_count=('total_elec_kwh','size'), monthly_total_elec_kwh=('total_elec_kwh','sum'),
                    monthly_duration_min=('duration_min','sum')))
        finally:
            for writer in writers.values():
                writer.close()
        assert counts['input']==counts['clean']+counts['excluded']
        assert np.isclose(totals['raw_energy_kwh'],totals['excluded_energy_kwh']+totals['clean_energy_kwh'])
        for label in ['clean','excluded']:
            assert pq.ParquetFile(out/f'orders_{month}_{label}.parquet').metadata.num_rows==counts[label]
        report['orders'][month]={'counts':dict(counts),'energy':dict(totals)}
        print(month,dict(counts),flush=True)
    monthly = pd.concat(aggregates).groupby(['analysis_month','station_id'],as_index=False)[
        ['monthly_order_count','monthly_total_elec_kwh','monthly_duration_min']].sum()
    monthly = monthly.rename(columns={'analysis_month':'month'}).merge(stations,on='station_id',validate='many_to_one')
    monthly['grid_id']=monthly.geocoding
    monthly['monthly_gun_utilization_rate']=np.nan
    for month in monthly.month.unique():
        idx=monthly.month.eq(month)
        monthly.loc[idx,'monthly_gun_utilization_rate']=monthly_utilization(monthly.loc[idx,'monthly_duration_min'],monthly.loc[idx,'charging_gun_num'],month)
    monthly['flag_utilization_gt_one']=monthly.monthly_gun_utilization_rate.gt(1)
    monthly['flag_zero_guns']=monthly.charging_gun_num.eq(0)
    pq.write_table(pa.Table.from_pandas(monthly,preserve_index=False),out/'stations_monthly_clean.parquet')
    summary=monthly.groupby('month').agg(orders=('monthly_order_count','sum'),energy_kwh=('monthly_total_elec_kwh','sum'),
        observed_stations=('station_id','nunique'),observed_grids=('grid_id','nunique'),
        utilization_gt_one=('flag_utilization_gt_one','sum'),zero_gun_stations=('flag_zero_guns','sum'))
    assert summary.orders.sum()==sum(x['counts']['clean'] for x in report['orders'].values())
    assert np.isclose(summary.energy_kwh.sum(),sum(x['energy']['clean_energy_kwh'] for x in report['orders'].values()))
    report['station_month_summary']=json.loads(summary.to_json(orient='index'))
    report['stations']={'rows':len(stations),'pile_component_mismatch':int(stations.flag_pile_component_mismatch.sum()),
                        'gun_component_mismatch':int(stations.flag_gun_component_mismatch.sum())}
    report['source_sha256']['stations_public.parquet']=station_hash
    for name,h in report['source_sha256'].items():
        assert digest(SOURCE/name)==h
    payload=json.dumps(report,ensure_ascii=False,indent=2)
    (out/'cleaning_manifest.json').write_text(payload,encoding='utf-8')
    (ROOT/'reports'/f'source_release2_clean1_{run}.json').write_text(payload,encoding='utf-8')
    print(summary.to_string(),flush=True)
    print(out,flush=True)


if __name__=='__main__':
    main()
