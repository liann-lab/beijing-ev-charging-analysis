"""Audit extracted UrbanEV station series without editing source files."""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main():
    base = ROOT/'data/raw/UrbanEV数据/UrbanEVDataset'
    metadata = pd.read_csv(base/'20220901-20230228_station-raw/station_information.csv')
    files = sorted((base/'20220901-20230228_station-processed').glob('*.csv'))
    if not files:
        raise SystemExit('Extract UrbanEVDataset.zip first.')
    summary = {
        'metadata_stations': len(metadata),
        'duplicate_station_ids': int(metadata.station_id.duplicated().sum()),
        'coordinate_missing_rows': int(metadata[['longitude', 'latitude']].isna().any(axis=1).sum()),
        'coordinate_range': metadata[['longitude', 'latitude']].agg(['min', 'max']).to_dict(),
        'processed_station_files': len(files), 'rows': 0, 'missing_cells': 0,
        'non_five_minute_steps': 0, 'duplicate_timestamps': 0,
        'negative_busy_idle': 0, 'component_mismatch_rows': 0,
        'unmatched_station_files': 0,
    }
    expected = pd.date_range('2022-09-01', '2023-02-28 23:55', freq='5min')
    summary['expected_rows_per_station'] = len(expected)
    summary['stations_with_incomplete_time_axis'] = 0
    ids = set(metadata.station_id.astype(str))
    for i, file in enumerate(files):
        d = pd.read_csv(file)
        time = pd.DatetimeIndex(pd.to_datetime(d.time))
        summary['rows'] += len(d)
        summary['missing_cells'] += int(d.isna().sum().sum())
        summary['duplicate_timestamps'] += int(time.duplicated().sum())
        summary['non_five_minute_steps'] += int((time.to_series().diff().dropna() != pd.Timedelta(minutes=5)).sum())
        summary['stations_with_incomplete_time_axis'] += int(not time.equals(expected))
        summary['negative_busy_idle'] += int(d[['busy', 'idle']].lt(0).any(axis=1).sum())
        summary['component_mismatch_rows'] += int(
            ((d.busy-d.fast_busy-d.slow_busy).abs().gt(1e-6)
             | (d.idle-d.fast_idle-d.slow_idle).abs().gt(1e-6)).sum())
        summary['unmatched_station_files'] += int(file.stem not in ids)
        if i % 200 == 0:
            print(f'Checked {i+1}/{len(files)} files', flush=True)
    destination = ROOT/'data/processed/urbanev_audit'
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
