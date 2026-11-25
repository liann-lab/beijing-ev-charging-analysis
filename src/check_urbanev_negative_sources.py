"""Match every processed negative value to the corresponding downloaded raw row."""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main():
    local = ROOT/'data/processed/urbanev_audit'
    negative = pd.read_parquet(local/'negative_records.parquet')
    raw = ROOT/'data/raw/UrbanEV数据/UrbanEVDataset/20220901-20230228_station-raw/charge_5min'
    result = dict(negative_rows=len(negative), raw_rows_found=0, raw_all_fields_missing=0,
                  raw_duration_or_volume_missing=0, raw_duration_or_volume_negative=0,
                  raw_valid_nonnegative_duration_volume=0, raw_busy_missing=0)
    for i, (station, rows) in enumerate(negative.groupby('station_id')):
        d = pd.read_csv(raw/f'{station}.csv')
        if d.time.duplicated().any():
            raise ValueError(f'Duplicate raw timestamp: {station}')
        found = d.set_index('time').reindex(rows.time)
        result['raw_rows_found'] += int(rows.time.isin(d.time).sum())
        result['raw_all_fields_missing'] += int(found.isna().all(axis=1).sum())
        result['raw_duration_or_volume_missing'] += int(found[['duration', 'volume']].isna().any(axis=1).sum())
        result['raw_duration_or_volume_negative'] += int(found[['duration', 'volume']].lt(0).any(axis=1).sum())
        result['raw_valid_nonnegative_duration_volume'] += int(
            (found[['duration', 'volume']].notna().all(axis=1)
             & found[['duration', 'volume']].ge(0).all(axis=1)).sum())
        result['raw_busy_missing'] += int(found.busy.isna().sum())
        if i % 250 == 0:
            print(f'Compared {i+1} stations', flush=True)
    if result['raw_rows_found'] != result['negative_rows']:
        raise ValueError('Unmatched negative timestamps')
    (local/'negative_source_review.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
