"""Plot the latest independently rebuilt release-v2 cleaned dataset."""
import json
from pathlib import Path
import subprocess
import sys

import matplotlib.pyplot as plt
import create_visualizations as charts

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifests=sorted((ROOT/'data/processed').glob('source_release2_clean1_*/cleaning_manifest.json'))
    if not manifests:
        raise SystemExit('Run rebuild_release_v2.py first')
    manifest=json.loads(manifests[-1].read_text(encoding='utf-8'))
    clean=manifests[-1].parent
    output=ROOT/'reports/figures/source_release2'/manifest['run_id']
    charts.ORDER_FILES={m:clean/f'orders_{m}_clean.parquet' for m in ['2025-01','2025-07']}
    charts.STATION_FILE=clean/'stations_monthly_clean.parquet'
    charts.FIGURE_DIR=output
    charts.MONTH_BASIS='start'
    charts.MONTH_LABELS={'2025-01':'Jan 2025 (release v2, cleaned)', '2025-07':'Jul 2025 (release v2, cleaned)'}
    original=plt.Figure.savefig
    def save(figure,*args,**kwargs):
        figure.text(.5,-.025,'Release v2: linked cleaned orders, start-month attribution. Station-month measures rebuilt from the same orders.\n'
                    'Utilization uses recorded session duration / static guns / full-month minutes; not measured charging load.',
                    ha='center',va='top',fontsize=8,color='#555555')
        return original(figure,*args,**kwargs)
    plt.Figure.savefig=save
    try:
        charts.main()
    finally:
        plt.Figure.savefig=original
    subprocess.run([sys.executable,str(ROOT/'src/create_spatial_visualizations.py'),
                    '--clean-dir',str(clean),'--output-dir',str(output/'spatial')],check=True)
    (output/'month_assignment.json').write_text(json.dumps(charts.MONTH_ASSIGNMENT_AUDIT,indent=2),encoding='utf-8')
    print(output)


if __name__=='__main__':
    main()
