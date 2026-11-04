"""Audit the Figshare release v2 independently of the legacy cleaning versions."""
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/redownloaded/31952289'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    sources = list(SOURCE.glob('*.parquet'))
    hashes = {p.name: digest(p) for p in sources}
    stations = pd.read_parquet(SOURCE / 'stations_public.parquet')
    station_summary = {
        'rows': len(stations), 'unique_station_ids': int(stations.station_id.nunique()),
        'duplicate_station_id_rows': int(stations.station_id.duplicated(keep=False).sum()),
        'nulls': stations.isna().sum().astype(int).to_dict(),
        'columns': stations.columns.tolist(),
    }
    if stations.station_id.isna().any() or stations.station_id.duplicated().any():
        raise ValueError('Station key is not unique and non-null; do not join until resolved.')
    coords = stations.geocoding.str.extract(r'^(?:GX)?(-?\d+)_(?:GY)?(-?\d+)$')
    station_summary['unparseable_grid_rows'] = int(coords.isna().any(axis=1).sum())
    station_summary['grid_count'] = int(stations.geocoding.nunique())
    station_summary['pile_component_mismatch'] = int((stations.piles_num != stations.dc_piles_num + stations.ac_piles_num).sum())
    station_summary['gun_component_mismatch'] = int((stations.charging_gun_num != stations.dc_charging_gun_num + stations.ac_charging_gun_num).sum())
    result = {'source_release': 'Figshare Version 2 (user-downloaded; not legacy cleaning v2)',
              'source_directory': str(SOURCE.relative_to(ROOT)), 'source_sha256': hashes,
              'stations': station_summary, 'orders': {}}
    for month in ['2025-01', '2025-07']:
        source = SOURCE / f'orders_{month}_public.parquet'
        old = ROOT / 'data/raw' / source.name
        old_iter = pq.ParquetFile(old).iter_batches(batch_size=250000,
            columns=['dating_time', 'charge_power_kw', 'charge_start_time', 'charge_end_time', 'total_elec_kwh'])
        count = Counter()
        sums = Counter()
        nulls = Counter()
        dates = Counter()
        station_ids, pile_ids = set(), set()
        examples = []
        for batch in pq.ParquetFile(source).iter_batches(batch_size=250000):
            d = batch.to_pandas()
            legacy = next(old_iter).to_pandas()
            nulls.update(d.isna().sum().astype(int).to_dict())
            count['rows'] += len(d)
            if len(d) != len(legacy):
                raise ValueError('Legacy/new row boundaries differ; positional comparison invalid.')
            for col in ['charge_start_time', 'charge_end_time', 'total_elec_kwh']:
                count[f'diff_vs_legacy_{col}'] += int((~(d[col].eq(legacy[col]) | (d[col].isna() & legacy[col].isna()))).sum())
            count['diff_vs_legacy_power'] += int((~(d.rated_gun_power_kw.eq(legacy.charge_power_kw) | (d.rated_gun_power_kw.isna() & legacy.charge_power_kw.isna()))).sum())
            td = pd.to_datetime(d.transaction_date)
            count['diff_transaction_date_vs_legacy_dating_time'] += int((td != legacy.dating_time).sum())
            count['transaction_date_not_start_date'] += int((td != d.charge_start_time.dt.normalize()).sum())
            count['transaction_date_not_end_date'] += int((td != d.charge_end_time.dt.normalize()).sum())
            start_month = d.charge_start_time.dt.strftime('%Y-%m')
            dates.update(start_month.value_counts().to_dict())
            count['start_outside_file_month'] += int((start_month != month).sum())
            count['end_not_after_start'] += int((d.charge_end_time <= d.charge_start_time).sum())
            count['duration_difference_gt_1min'] += int(((d.charge_end_time-d.charge_start_time).dt.total_seconds().div(60).sub(d.duration_min).abs() > 1).sum())
            count['duration_gt_24h'] += int((d.duration_min > 1440).sum())
            joined = d.merge(stations[['station_id', 'geocoding', 'construction_site']], how='left', on='station_id', validate='many_to_one', indicator=True)
            count['unmatched_station_rows'] += int((joined['_merge'] != 'both').sum())
            station_ids.update(d.station_id.dropna())
            pile_ids.update(d.pile_id.dropna())
            missing = d[['equipment_classification', 'rated_gun_power_kw', 'station_id', 'pile_id', 'transaction_date', 'charge_start_time', 'charge_end_time', 'duration_min', 'total_elec_kwh', 'total_elec_fee', 'total_service_fee', 'total_fee']].isna().any(axis=1)
            cap = d.total_elec_kwh > d.rated_gun_power_kw*d.duration_min/60*1.05
            extreme = (d.total_elec_kwh > 1000) & cap
            count['missing_any_order_field'] += int(missing.sum())
            count['energy_gt_200'] += int((d.total_elec_kwh > 200).sum())
            count['energy_gt_200_non_bus'] += int(((joined.total_elec_kwh > 200) & joined.construction_site.ne('公交场站')).sum())
            count['energy_gt_1000'] += int((d.total_elec_kwh > 1000).sum())
            count['capacity_mismatch_105pct'] += int(cap.sum())
            count['extreme_joint_rule'] += int(extreme.sum())
            count['missing_or_extreme_joint'] += int((missing | extreme).sum())
            numeric = ['rated_gun_power_kw', 'duration_min', 'total_elec_kwh', 'total_elec_fee', 'total_service_fee', 'total_fee']
            count['any_negative_numeric'] += int(d[numeric].lt(0).any(axis=1).sum())
            count['fee_gap_gt_cent'] += int(((d.total_elec_fee + d.total_service_fee-d.total_fee).round(2).abs() > .01).sum())
            sums['energy_kwh'] += float(d.total_elec_kwh.sum())
            sums['max_energy_kwh'] = max(sums['max_energy_kwh'], float(d.total_elec_kwh.max()))
            sums['max_rated_power_kw'] = max(sums['max_rated_power_kw'], float(d.rated_gun_power_kw.max()))
            if len(examples) < 3:
                examples.extend(d.loc[extreme, ['station_id', 'rated_gun_power_kw', 'duration_min', 'total_elec_kwh']].head(3-len(examples)).to_dict('records'))
        result['orders'][month] = {'columns': pq.ParquetFile(source).schema.names,
            'counts': dict(count), 'nulls': dict(nulls), 'metrics': dict(sums),
            'observed_stations': len(station_ids), 'observed_piles': len(pile_ids),
            'start_month_counts': dict(dates), 'extreme_examples': examples}
        print(month, json.dumps(result['orders'][month], ensure_ascii=False), flush=True)
    for p in sources:
        assert digest(p) == hashes[p.name], 'Source changed during audit'
    out = ROOT/'reports/release_v2_audit.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out, flush=True)


if __name__ == '__main__':
    main()
