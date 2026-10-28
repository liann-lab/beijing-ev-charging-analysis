"""Render a separate chart set from the latest completed cleaning run."""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import create_visualizations as charts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean-dir', type=Path, help='Completed cleaning output directory')
    args = parser.parse_args()
    if args.clean_dir:
        clean_dir = args.clean_dir.resolve()
    else:
        manifests = sorted((charts.PROJECT_ROOT / 'data/processed').glob('clean_v[12]_*/cleaning_manifest.json'),
                           key=lambda path: path.stat().st_mtime_ns)
        if not manifests:
            raise SystemExit('No completed cleaning run found; run src/clean_dataset.py first.')
        clean_dir = manifests[-1].parent
    manifest = json.loads((clean_dir / 'cleaning_manifest.json').read_text(encoding='utf-8'))
    charts.ORDER_FILES = {month: clean_dir / f'orders_{month}_clean.parquet' for month in ('2025-01', '2025-07')}
    charts.STATION_FILE = clean_dir / 'stations_monthly_clean.parquet'
    version = manifest['version']
    charts.FIGURE_DIR = charts.PROJECT_ROOT / 'reports/figures/cleaned'
    if version >= 2:
        charts.FIGURE_DIR /= f"v{version}_{manifest['run_id']}"
    charts.MONTH_LABELS = {'2025-01': 'Jan 2025 (cleaned)', '2025-07': 'Jul 2025 (cleaned)'}
    # Add the processing scope to every saved chart, without changing the original plotting script.
    original_savefig = plt.Figure.savefig
    def save_with_scope(figure, *save_args, **save_kwargs):
        figure.text(0.5, -0.025,
                    f"Cleaning v{version}: " + ', '.join(
                        f"{month}: {result['counts']['excluded_rows']:,} orders excluded"
                        for month, result in manifest['orders'].items()) + '; station-month aggregates unchanged.\n'
                    'Energy is grouped by session start hour, not measured hourly load; file-month cohorts retained.',
                    ha='center', va='top', fontsize=8, color='#555555')
        return original_savefig(figure, *save_args, **save_kwargs)
    plt.Figure.savefig = save_with_scope
    try:
        charts.main()
    finally:
        plt.Figure.savefig = original_savefig
    lines = ['# 清洗前后图表口径与对照', '', f"清洗运行：`{manifest['run_id']}`。", '',
             f'原始及上一版图表保留，新图保存在 `{charts.FIGURE_DIR.relative_to(charts.PROJECT_ROOT)}`。', '',
             '| 月份 | 原始订单数 | 清洗订单数 | 原始电量（GWh） | 清洗电量（GWh） |',
             '| --- | ---: | ---: | ---: | ---: |']
    for month, result in manifest['orders'].items():
        c, e = result['counts'], result['energy']
        lines.append(f"| {month} | {c['input_rows']:,} | {c['clean_rows']:,} | {e['raw_energy_kwh']/1e6:.4f} | {e['clean_energy_kwh']/1e6:.4f} |")
    lines.extend(['', f"清洗版本：v{version}。各月剔除数量及规则计数见清洗清单。", '',
                  '月份比较仍按文件包含的订单群体进行。7月包括6月30日开始、7月结束的会话；分时图按开始小时归类整次电量，不能解释为实际逐小时负荷。', '',
                  '电量累计分布使用固定随机种子的分批抽样，排除零电量；因清洗改变批次组成，抽样曲线的小幅变化不全由隔离记录解释。', '',
                  '场景占比图统一住宅场景名称。利用率来自站点月表，第一版清洗仅统一名称，因此利用率图与原始版本相同。', '',
                  '该版本仍保留跨月、高功率等带标记记录，未据此一律删除。'])
    report_name = 'cleaned_chart_review.md' if version == 1 else f"cleaned_chart_review_v{version}_{manifest['run_id']}.md"
    (charts.PROJECT_ROOT / 'reports' / report_name).write_text('\n'.join(lines)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
