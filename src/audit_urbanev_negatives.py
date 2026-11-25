"""Locate negative UrbanEV duration/volume values and test adjacent-state patterns."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main():
    base = ROOT/'data/raw/UrbanEV数据/UrbanEVDataset/20220901-20230228_station-processed'
    records = []
    summary = dict(stations=0, rows=0, negative_duration=0, negative_volume=0,
                   both_negative=0, busy_decreased=0, preceding_busy_decreased=0,
                   following_busy_decreased=0, duration_matches_busy_difference=0,
                   unchanged_busy=0)
    for i, file in enumerate(sorted(base.glob('*.csv'))):
        d = pd.read_csv(file, usecols=['time', 'busy', 'duration', 'volume'])
        mask = d.duration.lt(0) | d.volume.lt(0)
        if mask.any():
            summary['stations'] += 1
            summary['rows'] += int(mask.sum())
            summary['negative_duration'] += int(d.duration.lt(0).sum())
            summary['negative_volume'] += int(d.volume.lt(0).sum())
            summary['both_negative'] += int((d.duration.lt(0) & d.volume.lt(0)).sum())
            diff = d.busy.diff()
            summary['busy_decreased'] += int(diff.loc[mask].lt(0).sum())
            summary['preceding_busy_decreased'] += int(diff.shift(1).loc[mask].lt(0).sum())
            summary['following_busy_decreased'] += int(diff.shift(-1).loc[mask].lt(0).sum())
            summary['unchanged_busy'] += int(diff.loc[mask].eq(0).sum())
            summary['duration_matches_busy_difference'] += int(
                np.isclose(d.loc[mask, 'duration'], diff.loc[mask]/12, atol=1e-8).sum())
            selected = d.loc[mask].copy()
            selected['station_id'] = file.stem
            selected['busy_difference'] = diff.loc[mask]
            records.append(selected)
        if i % 300 == 0:
            print(f'Scanned {i+1} stations', flush=True)
    if not records:
        raise ValueError('Previously reported negative values not found')
    negatives = pd.concat(records, ignore_index=True)
    dates = pd.to_datetime(negatives.time)
    summary['monthly_counts'] = dates.dt.strftime('%Y-%m').value_counts().sort_index().to_dict()
    summary['distinct_dates'] = int(dates.dt.date.nunique())
    summary['top_date_counts'] = dates.dt.strftime('%Y-%m-%d').value_counts().head(5).to_dict()
    summary['top_station_counts'] = negatives.station_id.value_counts().head(5).to_dict()
    local = ROOT/'data/processed/urbanev_audit'
    local.mkdir(parents=True, exist_ok=True)
    negatives.to_parquet(local/'negative_records.parquet', index=False)
    (local/'negative_review.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
