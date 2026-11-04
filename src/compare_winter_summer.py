"""Paired descriptive comparisons, preserving coverage and facility-count caveats."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from analyze_grid_sensitivity import aggregate, display_sample
from audit_release_v2 import digest

ROOT=Path(__file__).resolve().parents[1]
MONTHS=['2025-01','2025-07']


def common_ids(data,key):
    return set(data.loc[data.month.eq(MONTHS[0]),key]) & set(data.loc[data.month.eq(MONTHS[1]),key])


def paired(g,metric,threshold):
    if threshold=='guns':g=g.loc[g.guns.ge(5)]
    if threshold=='orders':g=g.loc[g.orders.ge(5)]
    p=g.pivot(index='grid_id',columns='month',values=metric).dropna(subset=MONTHS)
    return p


def main():
    paths=sorted((ROOT/'data/processed').glob('source_release2_clean1_*/cleaning_manifest.json'))
    manifest=json.loads(paths[-1].read_text(encoding='utf-8'))
    source=paths[-1].parent/'stations_monthly_clean.parquet'
    before=digest(source)
    s=pd.read_parquet(source);s=s.loc[s.month.isin(MONTHS)].copy()
    bad=s.flag_pile_component_mismatch|s.flag_gun_component_mismatch
    grid_ids,station_ids=common_ids(s,'grid_id'),common_ids(s,'station_id')
    fixed=s.loc[s.station_id.isin(station_ids)]
    fixed_ok=fixed.loc[~(fixed.flag_pile_component_mismatch|fixed.flag_gun_component_mismatch)]
    cohorts={'all_observed':s,'common_grids':s.loc[s.grid_id.isin(grid_ids)],
             'common_stations':fixed,'common_stations_consistent_facilities':fixed_ok}
    output=ROOT/'reports/figures/source_release2'/manifest['run_id']/'winter_summer'
    output.mkdir(parents=True,exist_ok=True)
    result={'run_id':manifest['run_id'],'source_sha256':before,'common_grids':len(grid_ids),
            'common_stations':len(station_ids),'cohorts':{},'large_local_changes':{}}
    grid_frames={}
    for name,d in cohorts.items():
        g=aggregate(d)
        g['sessions_per_gun_day']=g.orders/g.guns/31
        g['energy_per_gun_day']=g.energy_kwh/g.guns/31
        grid_frames[name]=g
        summary={}
        for month in MONTHS:
            t=g.loc[g.month.eq(month)]
            summary[month]={'grids':len(t),'stations':int(t.station_count.sum()),'orders':int(t.orders.sum()),
                'energy_kwh':float(t.energy_kwh.sum()),'guns':float(t.guns.sum()),
                'pooled_utilization':float(t.duration_min.sum()/t.guns.sum()/31/1440),
                'pooled_sessions_per_gun_day':float(t.orders.sum()/t.guns.sum()/31)}
        metrics={}
        for metric,threshold in [('utilization','guns'),('sessions_per_gun_day','guns'),
                                 ('energy_per_gun_day','guns'),('mean_energy','orders')]:
            p=paired(g,metric,threshold);delta=p[MONTHS[1]]-p[MONTHS[0]]
            metrics[metric]={'paired_grids':len(p),'median_jan':float(p[MONTHS[0]].median()),
                'median_jul':float(p[MONTHS[1]].median()),'median_paired_change':float(delta.median()),
                'share_increased':float(delta.gt(0).mean()),'share_decreased':float(delta.lt(0).mean()),
                'q25_change':float(delta.quantile(.25)),'q75_change':float(delta.quantile(.75))}
        result['cohorts'][name]={'monthly':summary,'paired_metrics':metrics}
    base=aggregate(s);alt=aggregate(s.loc[~bad])
    for month in MONTHS:
        a=display_sample(base.loc[base.month.eq(month)],'utilization').set_index('grid_id')
        b=display_sample(alt.loc[alt.month.eq(month)],'utilization').set_index('grid_id')
        p=a[['utilization','guns','orders']].join(b[['utilization','guns','orders']],lsuffix='_base',rsuffix='_alt',how='inner')
        p['delta_pp']=(p.utilization_alt-p.utilization_base)*100
        top=p.loc[p.delta_pp.abs().nlargest(5).index].reset_index()
        entries=[]
        for row in top.to_dict('records'):
            flagged=s.loc[s.month.eq(month)&s.grid_id.eq(row['grid_id'])&bad]
            row['removed_station_ids']=flagged.station_id.tolist()
            row['removed_guns']=float(flagged.charging_gun_num.sum())
            row['removed_duration_min']=float(flagged.monthly_duration_min.sum())
            entries.append(row)
        result['large_local_changes'][month]=entries
    # Common equal-aspect axes preserve the identity-line interpretation. The
    # first row contains every point; the second is explicitly a viewport zoom.
    pair_names=['common_grids','common_stations','common_stations_consistent_facilities']
    pairs={name:paired(grid_frames[name],'utilization','guns')*100 for name in pair_names}
    maximum=max(float(p.to_numpy().max()) for p in pairs.values())
    full_limit=max(10.,float(np.ceil(maximum/10)*10))
    zoom_limit=25.
    result['scatter_display']={'full_axis_max_percent':full_limit,'zoom_axis_max_percent':zoom_limit,'cohorts':{}}
    fig,axes=plt.subplots(2,3,figsize=(13,9),layout='constrained')
    for col,(name,label) in enumerate(zip(pair_names,
                              ['Common grids','Common stations','Common stations, counts consistent'])):
        p=pairs[name]
        in_zoom=p[MONTHS[0]].le(zoom_limit)&p[MONTHS[1]].le(zoom_limit)
        result['scatter_display']['cohorts'][name]={'total':len(p),'inside_zoom':int(in_zoom.sum()),'outside_zoom':int((~in_zoom).sum())}
        for row,limit in enumerate([full_limit,zoom_limit]):
            ax=axes[row,col]
            shown=p if row==0 else p.loc[in_zoom]
            ax.scatter(shown[MONTHS[0]],shown[MONTHS[1]],s=7,alpha=.3,linewidths=0,rasterized=True)
            ax.plot([0,limit],[0,limit],color='gray',linewidth=1)
            caption=f'All {len(p):,} paired grids' if row==0 else f'Zoom: {int(in_zoom.sum()):,} inside / {int((~in_zoom).sum()):,} outside view'
            ax.set(xlim=(0,limit),ylim=(0,limit),xlabel='January utilization (%)',ylabel='July utilization (%)',title=f'{label}\n{caption}')
            ax.set_aspect('equal')
    fig.suptitle('Paired grid utilization: at least 5 observed guns in both months')
    fig.supxlabel('Top row: complete data range. Bottom row: 0-25% zoom; outside-view points remain in all statistics.\nObserved-active samples; static capacity, full-month availability and start-month attribution assumed. Not a seasonal causal estimate.',fontsize=8)
    fig.savefig(output/'01-paired-utilization.png',dpi=170);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4.5),layout='constrained')
    names=list(cohorts);labels=['All observed','Common grids','Common stations','Common stations\nconsistent counts']
    for ax,metric,title,factor in [(axes[0],'pooled_utilization','Pooled utilization (%)',100),(axes[1],'pooled_sessions_per_gun_day','Sessions per gun per day',1)]:
        x=np.arange(4)
        for j,month in enumerate(MONTHS):
            vals=[result['cohorts'][n]['monthly'][month][metric]*factor for n in names]
            ax.bar(x+(j-.5)*.35,vals,.35,label=month)
        ax.set(xticks=x,xticklabels=labels,title=title);ax.tick_params(axis='x',labelsize=8);ax.legend()
    fig.supxlabel('Ratios of sums, not unweighted averages. All-observed and common-grid cohorts can differ in station composition.',fontsize=8)
    fig.savefig(output/'02-coverage-comparison.png',dpi=170);plt.close(fig)
    (output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 冬夏共同网格比较与局部敏感网格核查','',f"数据运行：`{manifest['run_id']}`。全部指标按开始月整笔归属；仅比较已观测到保留订单的站点。",'',
           f'共同网格{len(grid_ids)}个；共同有订单的站点{len(station_ids)}个。“共同网格”不等于“站点构成相同”，故另做共同站点与计数一致共同站点两组对照。','',
           '| 样本 | 1月汇总利用率 | 7月汇总利用率 | 1月每枪日均订单 | 7月每枪日均订单 |',
           '| --- | ---: | ---: | ---: | ---: |']
    for name,r in result['cohorts'].items():
        a,b=[r['monthly'][m] for m in MONTHS]
        lines.append(f"| {name} | {a['pooled_utilization']:.3%} | {b['pooled_utilization']:.3%} | {a['pooled_sessions_per_gun_day']:.3f} | {b['pooled_sessions_per_gun_day']:.3f} |")
    lines+=['','## 配对网格利用率变化（两月均至少5把枪）','',
           '| 样本 | 配对网格数 | 配对变化中位数（百分点） | 利用率上升网格比例 |',
           '| --- | ---: | ---: | ---: |']
    for name,r in result['cohorts'].items():
        m=r['paired_metrics']['utilization'];lines.append(f"| {name} | {m['paired_grids']} | {m['median_paired_change']*100:.3f} | {m['share_increased']:.2%} |")
    lines+=['','## 设施计数处理最敏感的网格（各月前5）','',
           '| 月份 | 网格 | 基准利用率 | 排除后利用率 | 变化（百分点） | 移除枪数 | 移除站点 |',
           '| --- | --- | ---: | ---: | ---: | ---: | --- |']
    for month,rows in result['large_local_changes'].items():
        for r in rows:lines.append(f"| {month} | {r['grid_id']} | {r['utilization_base']:.3%} | {r['utilization_alt']:.3%} | {r['delta_pp']:.3f} | {r['removed_guns']:.0f} | {', '.join(r['removed_station_ids'])} |")
    lines+=['','差异由移除整个站点同时改变分子时长与分母枪数产生，不能据此认定总数或分项哪一个正确，也不能直接指定某网格为供给不足。达标样本消失的网格见上一轮敏感性清单，不补零。',
            '汇总利用率是总时长／总枪时，配对中位数则是逐网格变化的中位数，不能混称。共同站点是两月都有记录的活跃选择样本，并非两月全部真实在运设施。',
            '当前只能描述1月和7月观察样本的差异，不证明冬夏季节因果。春节、价格、车辆结构、站点开放时间与覆盖变化未被控制。',
            '本组仍采用开始月整笔归属，未校正静态容量与整月可用假设或会话重叠；独立的自然月占用时长对照见[自然月报告](calendar_month_review.md)。现有结果不是最终选址或供需缺口结论。',
            '', '## 配对散点图显示范围', '',
            f'上排统一使用0%—{full_limit:g}%坐标，覆盖全部配对点。下排统一放大0%—{zoom_limit:g}%区间，仅改变视窗，不删除原始或分析记录，每幅标明视窗内外数量。上下排均保持横纵同尺度和相同利用率对角线。',
            '旧0%—100%坐标造成不必要留白。标尺修订不改变配对样本、汇总利用率或变化统计。']
    (ROOT/'reports/winter_summer_comparison.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    assert digest(source)==before
    print('\n'.join(lines),flush=True)


if __name__=='__main__':main()
