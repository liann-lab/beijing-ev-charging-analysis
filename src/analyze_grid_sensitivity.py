"""Separate paper-style display filters from facility-count sensitivity scenarios."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm
from matplotlib.ticker import PercentFormatter
import numpy as np
import pandas as pd

from audit_release_v2 import digest
from create_spatial_visualizations import utilization_color_scale

ROOT=Path(__file__).resolve().parents[1]
MONTHS=('2025-01','2025-07')


def aggregate(stations):
    if stations.duplicated(['month','station_id']).any():
        raise ValueError('Repeated station-month rows would double count infrastructure')
    g=stations.groupby(['month','grid_id'],as_index=False).agg(
        orders=('monthly_order_count','sum'),energy_kwh=('monthly_total_elec_kwh','sum'),
        duration_min=('monthly_duration_min','sum'),guns=('charging_gun_num','sum'),
        station_count=('station_id','nunique'))
    g['mean_energy']=g.energy_kwh/g.orders.replace(0,np.nan)
    # Both selected months have 31 days. Whole sessions follow start-month attribution.
    g['utilization']=g.duration_min/(g.guns.replace(0,np.nan)*31*1440)
    xy=g.grid_id.str.extract(r'^(-?\d+)_(-?\d+)$')
    if xy.isna().any().any():
        raise ValueError('Unknown grid encoding')
    g[['x','y']]=xy.astype(int).to_numpy()
    return g


def display_sample(grid,metric):
    # Paper Fig.2: mean session energy >=5 sessions; utilization >=5 connectors.
    return grid.loc[grid.orders.ge(5) if metric=='mean_energy' else grid.guns.ge(5)].copy()


def sample_stats(g):
    return {'grids':len(g),'orders':int(g.orders.sum()),'energy_kwh':float(g.energy_kwh.sum()),
            'guns':float(g.guns.sum()),'stations':int(g.station_count.sum())}


def paired_changes(base,alternative,metric):
    a=display_sample(base,metric).set_index('grid_id')[metric]
    b=display_sample(alternative,metric).set_index('grid_id')[metric]
    paired=pd.concat([a.rename('baseline'),b.rename('alternative')],axis=1).dropna()
    delta=paired.alternative-paired.baseline
    rho=paired.baseline.rank().corr(paired.alternative.rank()) if len(paired)>1 else None
    return {'paired_grids':len(paired),'baseline_only_eligible_grids':len(a.index.difference(b.index)),
            'alternative_only_eligible_grids':len(b.index.difference(a.index)),
            'median_abs_difference':float(delta.abs().median()),
            'p95_abs_difference':float(delta.abs().quantile(.95)),
            'max_abs_difference':float(delta.abs().max()),
            'rank_correlation':None if rho is None or pd.isna(rho) else float(rho),
            'units':'fraction (multiply by 100 for percentage points)' if metric=='utilization' else 'kWh/session'}


def plot_comparison(base,alt,metric,row_names,title,out,main_ids,limits):
    b,norm,cmap=utilization_color_scale()
    if metric=='mean_energy':
        # Common thresholds for both months and both comparisons. All observed
        # values remain visible; dense central values receive more color steps.
        b=np.array([0,10,15,20,23,26,30,35,45,60,100,200],dtype=float)
        values=pd.concat([base[metric],alt[metric]]).dropna()
        if values.min()<b[0] or values.max()>b[-1]:
            raise ValueError('Mean-energy range exceeded: revise explicit display boundaries')
        cmap=plt.get_cmap('viridis',len(b)-1)
        norm=BoundaryNorm(b,cmap.N)
    fig,axes=plt.subplots(2,2,figsize=(13,10),sharex=True,sharey=True,layout='constrained')
    for row,g in enumerate([base,alt]):
        for col,month in enumerate(MONTHS):
            eligible=g.loc[g.month.eq(month)]
            visible=eligible.loc[eligible.grid_id.isin(main_ids)]
            artist=axes[row,col].scatter(visible.x,visible.y,c=visible[metric],cmap=cmap,norm=norm,
                s=10,marker='s',linewidths=0,rasterized=True)
            annotation=''
            if row==1 and metric=='mean_energy':
                prior=base.loc[base.month.eq(month)].set_index('grid_id')
                current=g.loc[g.month.eq(month)].set_index('grid_id')
                lost=prior.loc[prior.index.difference(current.index)]
                lost_visible=lost.loc[lost.index.isin(main_ids)]
                axes[row,col].scatter(lost_visible.x,lost_visible.y,s=15,marker='x',c='#777777',linewidths=.8)
                shared=prior.index.intersection(current.index)
                changed=(current.loc[shared,metric]-prior.loc[shared,metric]).abs().gt(1e-9)
                changed_ids=shared[changed]
                changed_visible=current.loc[current.index.isin(changed_ids)&current.index.isin(main_ids)]
                axes[row,col].scatter(changed_visible.x,changed_visible.y,s=30,facecolors='none',edgecolors='#111111',linewidths=.8)
                annotation=f'\n{len(lost)} no longer eligible (gray x); {len(changed_ids)} changed (outlined)'
            axes[row,col].set(title=f'{row_names[row]} | {month}\n{len(visible):,} shown / {len(eligible):,} eligible grids',
                              xlim=limits[:2],ylim=limits[2:])
            axes[row,col].set_aspect('equal',adjustable='box')
            if row==1: axes[row,col].set_xlabel('Anonymized grid X')
            if col==0: axes[row,col].set_ylabel('Anonymized grid Y')
            if annotation:
                axes[row,col].text(.01,.01,annotation.strip(),transform=axes[row,col].transAxes,fontsize=8,
                    bbox=dict(facecolor='white',alpha=.9,edgecolor='none'))
    options=dict(boundaries=b,ticks=b,spacing='uniform')
    if metric!='mean_energy':options['format']=PercentFormatter(1,decimals=0)
    fig.colorbar(artist,ax=axes,shrink=.7,label='Mean energy (kWh/session, unequal bins)' if metric=='mean_energy' else 'Estimated connector utilization',**options)
    fig.suptitle(title,fontsize=14)
    extra='Mean-energy bins are narrower near 20-30 kWh; bin widths are unequal. No values clipped.\n' if metric=='mean_energy' else ''
    fig.supxlabel(extra+'Same coordinates and color scale across all panels. Blank = unobserved or excluded by the stated display rule.\n'
                  'Remote grid retained in totals, omitted from main-cluster view. Whole sessions assigned to start month.',fontsize=9)
    fig.savefig(out,dpi=170)
    plt.close(fig)


def main():
    manifests=sorted((ROOT/'data/processed').glob('source_release2_clean1_*/cleaning_manifest.json'))
    if not manifests: raise SystemExit('Run rebuild_release_v2.py first')
    manifest=json.loads(manifests[-1].read_text(encoding='utf-8'))
    source=manifests[-1].parent/'stations_monthly_clean.parquet'
    source_hash=digest(source)
    stations=pd.read_parquet(source)
    stations=stations.loc[stations.month.isin(MONTHS)].copy()
    bad=stations.flag_pile_component_mismatch | stations.flag_gun_component_mismatch
    baseline=aggregate(stations)
    alternative=aggregate(stations.loc[~bad])
    q1,q3=baseline[['x','y']].quantile(.25),baseline[['x','y']].quantile(.75)
    remote=((baseline[['x','y']]<q1-10*(q3-q1)) | (baseline[['x','y']]>q3+10*(q3-q1))).any(axis=1)
    main=baseline.loc[~remote]
    main_ids=set(main.grid_id)
    limits=(main.x.min()-2,main.x.max()+2,main.y.min()-2,main.y.max()+2)
    output=ROOT/'reports/figures/source_release2'/manifest['run_id']/'paper_filters_sensitivity'
    output.mkdir(parents=True,exist_ok=True)
    report={'run_id':manifest['run_id'],'source_sha256':source_hash,
        'policy':{'mean_energy_display':'orders >= 5','utilization_display':'guns >= 5',
                  'sensitivity':'remove whole stations with either total/component mismatch, never replace published total with component sum',
                  'coverage':'observed station-months only; not a complete infrastructure census',
                  'baseline_reference':'current conservative cleaning, not a full replication of upstream paper cleaning'},
        'remote_records':baseline.loc[remote,['month','grid_id']].to_dict('records'),
        'months':{}}
    for month in MONTHS:
        a,b=baseline.loc[baseline.month.eq(month)],alternative.loc[alternative.month.eq(month)]
        d=stations.loc[stations.month.eq(month)]
        flags=d.flag_pile_component_mismatch | d.flag_gun_component_mismatch
        report['months'][month]={'baseline':sample_stats(a),'exclude_bad_facilities':sample_stats(b),
            'affected_stations':int(d.loc[flags,'station_id'].nunique()),
            'affected_order_share':float(d.loc[flags,'monthly_order_count'].sum()/d.monthly_order_count.sum()),
            'affected_energy_share':float(d.loc[flags,'monthly_total_elec_kwh'].sum()/d.monthly_total_elec_kwh.sum()),
            'metrics':{}}
        assert int(a.orders.sum())==int(d.monthly_order_count.sum())
        for metric in ['mean_energy','utilization']:
            filtered=display_sample(a,metric)
            report['months'][month]['metrics'][metric]={
                'unfiltered':sample_stats(a),'filtered':sample_stats(filtered),
                'excluded_from_display':len(a)-len(filtered),
                'alternative_filtered':sample_stats(display_sample(b,metric)),
                'paired_changes':paired_changes(a,b,metric)}
    for metric,label in [('mean_energy','Mean energy per session'),('utilization','Estimated connector utilization')]:
        plot_comparison(baseline,display_sample(baseline,metric),metric,['Before display filter','Paper display filter'],
            f'{label}: display filtering only (data retained)',output/f'{metric}_display_filter.png',main_ids,limits)
        plot_comparison(display_sample(baseline,metric),display_sample(alternative,metric),metric,
            ['Published facility totals','Exclude inconsistent facilities'],f'{label}: facility-count sensitivity (same paper display filter)',
            output/f'{metric}_facility_sensitivity.png',main_ids,limits)
    assert digest(source)==source_hash
    (output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 低样本展示筛选与设施计数敏感性','',f"运行：`{manifest['run_id']}`。新图与完整数值见 `{output.relative_to(ROOT).as_posix()}`。",'',
        '论文依据：北京充电论文PDF第14页。平均单次电量图只展示至少5笔订单的网格，利用率图只展示至少5把枪的网格。两项不是同一个筛选条件，筛选仅影响展示，不修改源数据。',
        '设施计数敏感性属于本项目额外设计，原文未提供总分项不一致的修正规则；基准保留公布总数，另一方案移除桩数或枪数总分项不一致的整个站点。两方案均重新汇总，比较使用共同达标网格。','',
        '| 月份 | 平均单次电量：筛前→筛后网格 | 利用率：筛前→筛后网格 | 涉及异常计数站点 | 涉及订单占比 | 涉及电量占比 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for month,d in report['months'].items():
        e,u=d['metrics']['mean_energy'],d['metrics']['utilization']
        lines.append(f"| {month} | {e['unfiltered']['grids']} → {e['filtered']['grids']} | {u['unfiltered']['grids']} → {u['filtered']['grids']} | {d['affected_stations']} | {d['affected_order_share']:.3%} | {d['affected_energy_share']:.3%} |")
    lines+=['','## 达标共同网格上的变化','',
        '| 月份 | 利用率差绝对值中位数（百分点） | 利用率差绝对值95分位（百分点） | 利用率差绝对值最大值（百分点） | 利用率排名相关 |',
        '| --- | ---: | ---: | ---: | ---: |']
    for month,d in report['months'].items():
        c=d['metrics']['utilization']['paired_changes']
        lines.append(f"| {month} | {c['median_abs_difference']*100:.4f} | {c['p95_abs_difference']*100:.4f} | {c['max_abs_difference']*100:.4f} | {c['rank_correlation']:.4f} |")
    lines+=['','指标差异为替代方案减基准的绝对值；排名相关使用共同达标网格的平均秩Pearson相关（Spearman定义）。低样本或移除站点导致不达标的网格另计，不以零填补。',
        '总体影响小不代表每个网格均不受影响，局部差异需单独核查。本组分析使用静态枪数、整月可用及开始月整笔归属假设，未校正停机或会话重叠。独立的自然月时长对照见[自然月报告](calendar_month_review.md)。',
        '图上主坐标簇与所有统计使用的完整网格范围分开报告，空间离群点未从数据删除。共同站点比较见[冬夏报告](winter_summer_comparison.md)，当前未作因果分析。',
        '', '## 图表标尺修订', '',
        '平均单次电量两张图使用相同的分段色标：0、10、15、20、23、26、30、35、45、60、100、200 kWh。常见20—30 kWh区间细分，所有观测值保留，色条各段宽度不等，不再使用跨多个数量级的对数色标。',
        '下排灰色叉号标记不再达标的网格，黑色空心圈标记在共同达标样本中均值变化超过数值容差1e-9 kWh的网格。数量按完整样本统计，远端网格仍按主图范围规则隐藏。展示筛选不会改变保留网格的均值，前后颜色一致具有实际含义。']
    (ROOT/'reports/release_v2_filters_sensitivity.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(report['months'],ensure_ascii=False,indent=2),flush=True)
    print(output)


if __name__=='__main__':main()
