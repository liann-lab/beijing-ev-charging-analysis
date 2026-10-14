"""Read-only, batch-wise verification of suspicious public charging records."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]

def audit(path, month):
    counts = {}
    examples = {}
    cross_dates = {}
    sums = {"energy": 0.0, "energy_over_200": 0.0, "energy_over_1000": 0.0}
    offset = 0
    for batch in pq.ParquetFile(path).iter_batches(batch_size=250000):
        d = batch.to_pandas()
        d["source_row"] = np.arange(offset, offset + len(d))
        offset += len(d)
        gap = d.total_money - d.total_elec_money - d.total_service_money
        # Round to cents before comparing, avoiding floating-point boundary noise.
        cents = gap.round(2)
        hours = d.duration_min / 60
        masks = {
            "energy_over_200": d.total_elec_kwh > 200,
            "energy_over_1000": d.total_elec_kwh > 1000,
            "power_over_500": d.charge_power_kw > 500,
            "energy_exceeds_rated_capacity": d.total_elec_kwh > d.charge_power_kw * hours * 1.05,
            "fee_gap_over_1cent": cents.abs() > 0.01,
            "total_below_components": cents < -0.01,
            "total_above_components": cents > 0.01,
            "cross_month_start": d.charge_start_time.dt.strftime('%Y-%m') != month,
            "cross_month_end": d.charge_end_time.dt.strftime('%Y-%m') != month,
            "cross_month_dating": d.dating_time.dt.strftime('%Y-%m') != month,
            "missing_equipment_or_power": d.equipment_classification.isna() | d.charge_power_kw.isna(),
        }
        for key, mask in masks.items():
            counts[key] = counts.get(key, 0) + int(mask.sum())
            if key not in examples:
                examples[key] = []
            if len(examples[key]) < 5:
                selected = d.loc[mask].copy()
                selected['fee_gap'] = cents[mask]
                selected = selected.sort_values('total_elec_kwh', ascending=False).head(5-len(examples[key]))
                examples[key].extend(json.loads(selected.to_json(orient='records', date_format='iso')))
        dates = d.loc[masks['cross_month_start'], 'charge_start_time'].dt.strftime('%Y-%m-%d').value_counts()
        for date, count in dates.items():
            cross_dates[date] = cross_dates.get(date, 0) + int(count)
        sums['energy'] += float(d.total_elec_kwh.sum())
        for key in ('energy_over_200', 'energy_over_1000'):
            sums[key] += float(d.loc[masks[key], 'total_elec_kwh'].sum())
    return {'rows': offset, 'counts': counts, 'energy_sums_kwh': sums,
            'cross_month_start_dates': cross_dates, 'examples': examples}

def main():
    results = {}
    for month in ('2025-01', '2025-07'):
        results[month] = audit(ROOT/'data/raw'/f'orders_{month}_public.parquet', month)
        print(month, json.dumps({k:v for k,v in results[month].items() if k != 'examples'}, ensure_ascii=False), flush=True)
    output = ROOT/'reports/anomaly_audit.json'
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output, flush=True)

if __name__ == '__main__':
    main()
