"""Conservative cleaning v1: create new files, preserve sources and provenance."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def clean_orders(source, month, output):
    counts = Counter()
    totals = Counter()
    source_hash = sha256(source)
    writers = {}
    offset = 0
    try:
        for batch in pq.ParquetFile(source).iter_batches(batch_size=250000):
            data = batch.to_pandas()
            data['source_file'] = source.name
            data['source_row'] = np.arange(offset, offset + len(data))
            offset += len(data)
            data['construction_site_raw'] = data.construction_site
            data['construction_site'] = data.construction_site.replace({'居民区': '居住区'})
            counts['site_names_normalized'] += int((data.construction_site_raw != data.construction_site).sum())
            data['file_month'] = month
            data['analysis_date'] = data.charge_start_time.dt.normalize()
            data['analysis_month'] = data.charge_start_time.dt.strftime('%Y-%m')
            flags = {
                'flag_missing_equipment_or_power': data.equipment_classification.isna() | data.charge_power_kw.isna(),
                'flag_energy_over_200': data.total_elec_kwh > 200,
                'flag_power_over_500': data.charge_power_kw > 500,
                'flag_energy_capacity_mismatch': data.total_elec_kwh > data.charge_power_kw * data.duration_min / 60 * 1.05,
                'flag_cross_month_start': data.analysis_month != month,
                'flag_cross_month_end': data.charge_end_time.dt.strftime('%Y-%m') != month,
                'flag_dating_month_mismatch': data.dating_time.dt.strftime('%Y-%m') != month,
            }
            for name, mask in flags.items():
                data[name] = mask
                counts[name] += int(mask.sum())
            excluded = (data.total_elec_kwh > 1000) & data.flag_energy_capacity_mismatch
            data['exclusion_reason'] = np.where(excluded, 'energy_gt_1000_and_capacity_mismatch', '')
            counts['input_rows'] += len(data)
            counts['excluded_rows'] += int(excluded.sum())
            counts['clean_rows'] += int((~excluded).sum())
            totals['raw_energy_kwh'] += float(data.total_elec_kwh.sum())
            totals['excluded_energy_kwh'] += float(data.loc[excluded, 'total_elec_kwh'].sum())
            totals['clean_energy_kwh'] += float(data.loc[~excluded, 'total_elec_kwh'].sum())
            full_table = pa.Table.from_pandas(data, preserve_index=False)
            for label, mask in [('clean', ~excluded), ('excluded', excluded)]:
                table = full_table.filter(pa.array(mask.to_numpy()))
                if label not in writers:
                    writers[label] = pq.ParquetWriter(output / f'orders_{month}_{label}.parquet', table.schema, compression='snappy')
                writers[label].write_table(table)
    finally:
        for writer in writers.values():
            writer.close()
    assert sha256(source) == source_hash, 'Source file changed'
    assert counts['input_rows'] == counts['clean_rows'] + counts['excluded_rows']
    assert np.isclose(totals['raw_energy_kwh'], totals['clean_energy_kwh'] + totals['excluded_energy_kwh'])
    for label in ('clean', 'excluded'):
        assert pq.ParquetFile(output / f'orders_{month}_{label}.parquet').metadata.num_rows == counts[f'{label}_rows']
    return {'source_file': source.name, 'source_sha256': source_hash, 'counts': dict(counts), 'energy': dict(totals)}


def main():
    # Each run gets a new directory; previous outputs are preserved.
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = ROOT / 'data/processed' / f'clean_v1_{run_id}'
    output.mkdir(parents=True, exist_ok=False)
    report = {'version': 1, 'run_id': run_id, 'output_directory': str(output), 'orders': {}}
    for month in ('2025-01', '2025-07'):
        report['orders'][month] = clean_orders(ROOT/'data/raw'/f'orders_{month}_public.parquet', month, output)
        print(month, json.dumps(report['orders'][month]['counts']), flush=True)
    source = ROOT/'data/raw/stations_monthly_public.parquet'
    digest = sha256(source)
    stations = pq.read_table(source).to_pandas()
    stations['source_file'] = source.name
    stations['source_row'] = np.arange(len(stations))
    stations['construction_site_raw'] = stations.construction_site
    stations['construction_site'] = stations.construction_site.replace({'居民区': '居住区'})
    pq.write_table(pa.Table.from_pandas(stations, preserve_index=False), output/'stations_monthly_clean.parquet')
    assert sha256(source) == digest
    assert pq.ParquetFile(output/'stations_monthly_clean.parquet').metadata.num_rows == len(stations)
    report['stations'] = {'source_sha256': digest, 'rows': len(stations), 'site_names_normalized': int((stations.construction_site_raw != stations.construction_site).sum())}
    (output/'cleaning_manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    report_path = ROOT/'reports'/f'cleaning_v1_{run_id}.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Output:', output, flush=True)


if __name__ == '__main__':
    main()
