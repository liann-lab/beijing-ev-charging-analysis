"""Render a separate chart set from the latest completed cleaning run."""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import create_visualizations as charts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean-dir', type=Path, help='Completed cleaning output directory')
    parser.add_argument('--month-basis', choices=['start', 'file'], default='start',
                        help='Default attributes cross-month sessions to their start month')
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
    charts.MONTH_BASIS = args.month_basis
    charts.FIGURE_DIR = charts.PROJECT_ROOT / 'reports/figures/cleaned'
    if version >= 2:
        charts.FIGURE_DIR /= f"v{version}_{manifest['run_id']}"
    charts.FIGURE_DIR /= f"month_{args.month_basis}"
    charts.MONTH_LABELS = {'2025-01': 'Jan 2025 (cleaned)', '2025-07': 'Jul 2025 (cleaned)'}
    # Add the processing scope to every saved chart, without changing the original plotting script.
    original_savefig = plt.Figure.savefig
    def save_with_scope(figure, *save_args, **save_kwargs):
        figure.text(0.5, -0.025,
                    f"Cleaning v{version}: " + ', '.join(
                        f"{month}: {result['counts']['excluded_rows']:,} orders excluded"
                        for month, result in manifest['orders'].items()) + '; station-month aggregates unchanged.\n'
                    f'Order month basis: {args.month_basis}. Whole-session energy grouped by start hour, not measured hourly load.',
                    ha='center', va='top', fontsize=8, color='#555555')
        return original_savefig(figure, *save_args, **save_kwargs)
    plt.Figure.savefig = save_with_scope
    try:
        charts.main()
    finally:
        plt.Figure.savefig = original_savefig
    assignment = charts.pd.DataFrame(charts.MONTH_ASSIGNMENT_AUDIT).groupby(
        ['file_month', 'assigned_month'], as_index=False)[['sessions', 'energy_kwh']].sum()
    assignment['sessions'] = assignment.sessions.astype(int)
    (charts.FIGURE_DIR / 'month_assignment.json').write_text(
        json.dumps({'month_basis': args.month_basis,
                    'note': 'Non-target months are partial observations, not complete monthly totals. Station-month aggregates unchanged.',
                    'rows': assignment.to_dict(orient='records')}, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 清洗前后图表口径与对照', '', f"清洗运行：`{manifest['run_id']}`。", '',
             f'原始及上一版图表保留，新图保存在 `{charts.FIGURE_DIR.relative_to(charts.PROJECT_ROOT)}`。', '',
             '| 月份 | 原始文件订单数 | 清洗保留订单数 | 本次绘图订单数 | 本次绘图电量（GWh） |',
             '| --- | ---: | ---: | ---: | ---: |']
    for month, result in manifest['orders'].items():
        c, e = result['counts'], result['energy']
        shown = assignment.loc[assignment.assigned_month.eq(month)]
        lines.append(f"| {month} | {c['input_rows']:,} | {c['clean_rows']:,} | {int(shown.sessions.sum()):,} | {shown.energy_kwh.sum()/1e6:.4f} |")
    lines.extend(['', f"清洗版本：v{version}。各月剔除数量及规则计数见清洗清单。", '',
                  f'本次订单归月依据：`{args.month_basis}`。start表示按开始月归属整笔订单及整次电量，例如6月30日开始、7月结束归6月，1月开始、2月结束仍归1月；跨月记录未从清洗数据中删除。非目标月份只进入归月审计，不能作为完整月份比较。分时图仍不是逐小时负荷。', '',
                  '电量累计分布使用固定随机种子的分批抽样，排除零电量；因清洗改变批次组成，抽样曲线的小幅变化不全由隔离记录解释。', '',
                  '场景占比图统一住宅场景名称。利用率分布来自原站点月表，不受订单剔除或开始月重归属影响，不能与订单图宣称为完全相同的归月口径。', '',
                  '该版本仍保留跨月、高功率等带标记记录，未据此一律删除。'])
    report_name = f"cleaned_chart_review_v{version}_{manifest['run_id']}_month_{args.month_basis}.md"
    (charts.PROJECT_ROOT / 'reports' / report_name).write_text('\n'.join(lines)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
