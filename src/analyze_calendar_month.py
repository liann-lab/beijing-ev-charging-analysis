"""Split observed session intervals at calendar boundaries without allocating energy."""
import calendar
from datetime import datetime, timezone
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from audit_release_v2 import digest

ROOT = Path(__file__).resolve().parents[1]
MONTHS = ['2025-01', '2025-07']


def split_intervals(d):
    """Positive overlaps of half-open [start,end) intervals. No zero boundary rows."""
    start, end = d.charge_start_time, d.charge_end_time
    if start.isna().any() or end.isna().any() or end.le(start).any():
        raise ValueError('Invalid session interval')
    if start.dt.tz is not None or end.dt.tz is not None:
        raise ValueError('Expected published naive local timestamps, not silent TZ conversion')
    frames = []
    for month in pd.period_range(start.min().to_period('M'), end.max().to_period('M'), freq='M'):
        lo, hi = month.start_time, (month+1).start_time
        mask = start.lt(hi) & end.gt(lo)
        if not mask.any():
            continue
        q = d.loc[mask, ['station_id', 'source_file', 'source_row']].copy()
        elapsed = (end.loc[mask]-start.loc[mask]).dt.total_seconds()/60
        overlap = (end.loc[mask].clip(upper=hi)-start.loc[mask].clip(lower=lo)).dt.total_seconds()/60
        q['month'] = str(month)
        q['overlap_minutes'] = overlap
        q['session_duration_share'] = overlap/elapsed
        q['allocated_recorded_minutes'] = d.loc[mask, 'duration_min']*q.session_duration_share
        q['start_month'] = start.loc[mask].dt.strftime('%Y-%m')
        frames.append(q)
    return pd.concat(frames, ignore_index=True)


def lorenz(values):
    v = np.sort(np.asarray(values, dtype=float))
    if len(v) == 0 or (v < 0).any() or v.sum() <= 0:
        raise ValueError('Lorenz requires nonnegative values with positive total')
    x = np.arange(len(v)+1)/len(v)
    y = np.r_[0., np.cumsum(v)/v.sum()]
    # Equal-weight grid concentration, not population equity.
    gini = (2*np.sum(np.arange(1, len(v)+1)*v)/(len(v)*v.sum())-(len(v)+1)/len(v))
    return x, y, float(gini)


def grid_aggregate(station_month):
    cols = ['recorded_start_minutes', 'elapsed_start_minutes', 'overlap_minutes',
            'allocated_recorded_minutes', 'start_orders', 'overlap_sessions', 'start_energy_kwh', 'guns']
    g = station_month.groupby(['month', 'grid_id'], as_index=False)[cols].sum()
    days = g.month.map(lambda m: calendar.monthrange(*map(int, m.split('-')))[1])
    for c in cols[:4]:
        g[c.replace('_minutes', '_utilization')] = g[c]/(g.guns.replace(0, np.nan)*days*1440)
    return g


def main():
    manifests = sorted((ROOT/'data/processed').glob('source_release2_clean1_*/cleaning_manifest.json'))
    clean = manifests[-1].parent
    run = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = ROOT/'data/processed'/f'calendar_month_{run}'
    out.mkdir(parents=True, exist_ok=False)
    figs = ROOT/'reports/figures/source_release2'/clean.name.removeprefix('source_release2_clean1_')/'calendar_month'/run
    figs.mkdir(parents=True)
    stations = pd.read_parquet(clean/'stations_clean.parquet').set_index('station_id')
    baseline = pd.read_parquet(clean/'stations_monthly_clean.parquet')
    common = set(baseline.loc[baseline.month.eq(MONTHS[0]), 'station_id']) & set(baseline.loc[baseline.month.eq(MONTHS[1]), 'station_id'])
    sources = [clean/f'orders_{m}_clean.parquet' for m in MONTHS]
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources+[clean/'stations_clean.parquet', clean/'stations_monthly_clean.parquet']}
    aggregates, borders = [], []
    hourly = np.zeros((2, 7, 24), dtype=np.int64)
    totals = dict(sessions=0, cross_month_sessions=0, recorded_minutes=0., elapsed_minutes=0., overlap_minutes=0., allocated_recorded_minutes=0., max_duration_discrepancy_minutes=0.)
    source_ranges = {}
    for source in sources:
        bounds = dict(start_min=None, start_max=None, end_max=None)
        for batch in pq.ParquetFile(source).iter_batches(batch_size=200000, columns=['station_id','source_file','source_row','charge_start_time','charge_end_time','duration_min','total_elec_kwh']):
            d = batch.to_pandas()
            for key, value in [('start_min', d.charge_start_time.min()), ('start_max', d.charge_start_time.max()), ('end_max', d.charge_end_time.max())]:
                if bounds[key] is None or (value < bounds[key] if key == 'start_min' else value > bounds[key]): bounds[key] = value
            d['month'] = d.charge_start_time.dt.strftime('%Y-%m')
            d['elapsed'] = (d.charge_end_time-d.charge_start_time).dt.total_seconds()/60
            cross = d.month.ne((d.charge_end_time-pd.Timedelta(1, 'ns')).dt.strftime('%Y-%m'))
            q = split_intervals(d)
            totals['sessions'] += len(d)
            totals['cross_month_sessions'] += int(cross.sum())
            totals['recorded_minutes'] += float(d.duration_min.sum())
            totals['elapsed_minutes'] += float(d.elapsed.sum())
            totals['overlap_minutes'] += float(q.overlap_minutes.sum())
            totals['allocated_recorded_minutes'] += float(q.allocated_recorded_minutes.sum())
            totals['max_duration_discrepancy_minutes'] = max(totals['max_duration_discrepancy_minutes'], float((d.elapsed-d.duration_min).abs().max()))
            a = d.groupby(['month','station_id']).agg(recorded_start_minutes=('duration_min','sum'), elapsed_start_minutes=('elapsed','sum'), start_orders=('station_id','size'), start_energy_kwh=('total_elec_kwh','sum'))
            b = q.groupby(['month','station_id']).agg(overlap_minutes=('overlap_minutes','sum'), allocated_recorded_minutes=('allocated_recorded_minutes','sum'), overlap_sessions=('station_id','size'))
            aggregates.append(a.join(b, how='outer').fillna(0))
            if cross.any():
                ids = pd.MultiIndex.from_frame(d.loc[cross, ['source_file','source_row']])
                border = q.loc[pd.MultiIndex.from_frame(q[['source_file','source_row']]).isin(ids)].copy()
                border = border.merge(d[['source_file','source_row','charge_start_time','charge_end_time','duration_min']], on=['source_file','source_row'], validate='many_to_one')
                borders.append(border)
            for j, month in enumerate(MONTHS):
                t = d.loc[d.month.eq(month)&d.station_id.isin(common)]
                h = t.groupby([t.charge_start_time.dt.dayofweek, t.charge_start_time.dt.hour]).size()
                for (dow, hour), count in h.items(): hourly[j,dow,hour] += count
        source_ranges[source.name] = {k:str(v) for k,v in bounds.items()}
        print(source.name, 'scanned', flush=True)
    assert np.isclose(totals['elapsed_minutes'], totals['overlap_minutes'], rtol=1e-12)
    assert np.isclose(totals['recorded_minutes'], totals['allocated_recorded_minutes'], rtol=1e-12)
    sm = pd.concat(aggregates).groupby(level=['month','station_id']).sum().reset_index()
    sm = sm.merge(stations[['geocoding','charging_gun_num']], left_on='station_id',right_index=True,validate='many_to_one').rename(columns={'geocoding':'grid_id','charging_gun_num':'guns'})
    sm.to_parquet(out/'station_calendar_month.parquet', index=False)
    grid = grid_aggregate(sm)
    grid.to_parquet(out/'grid_calendar_month.parquet', index=False)
    border = pd.concat(borders, ignore_index=True) if borders else pd.DataFrame()
    border.to_parquet(out/'cross_month_segments.parquet', index=False)
    # Primary comparison fixes the same observed-active stations and hence capacity.
    index = pd.MultiIndex.from_product([MONTHS, sorted(common)], names=['month','station_id'])
    fixed = sm.set_index(['month','station_id']).reindex(index)
    if fixed.grid_id.isna().any(): raise ValueError('Common cohort unexpectedly missing in month')
    fixed = fixed.reset_index()
    fg = grid_aggregate(fixed)
    fg.to_parquet(out/'common_station_grid_calendar_month.parquet', index=False)
    fields = ['recorded_start_minutes', 'elapsed_start_minutes', 'overlap_minutes', 'allocated_recorded_minutes']
    result = dict(run_id=run, clean_run=clean.name, source_sha256=hashes, input_ranges=source_ranges, totals=totals, common_stations=len(common), months={}, boundary_months={}, figures=str(figs.relative_to(ROOT)))
    for month in MONTHS:
        t = fixed.loc[fixed.month.eq(month)]
        denom = t.guns.sum()*31*1440
        entry = {c:float(t[c].sum()) for c in fields}
        entry.update({c.replace('_minutes','_utilization'):float(t[c].sum()/denom) for c in fields})
        entry['guns'] = float(t.guns.sum())
        entry['boundary_delta_minutes'] = entry['overlap_minutes']-entry['elapsed_start_minutes']
        entry['boundary_delta_pp'] = (entry['overlap_utilization']-entry['elapsed_start_utilization'])*100
        tgrid = fg.loc[fg.month.eq(month)&fg.guns.ge(5)]
        delta = (tgrid.overlap_utilization-tgrid.elapsed_start_utilization)*100
        entry['eligible_grids'] = len(tgrid)
        entry['grid_max_abs_delta_pp'] = float(delta.abs().max())
        entry['top_5_grid_boundary_changes'] = tgrid.assign(delta_pp=delta).loc[delta.abs().nlargest(5).index,['grid_id','delta_pp','guns']].to_dict('records')
        result['months'][month] = entry
    for month, t in sm.groupby('month'):
        z = border.loc[border.month.eq(month)] if len(border) else border
        carry_in = float(z.loc[z.start_month.ne(month),'overlap_minutes'].sum()) if len(z) else 0.
        carry_out = float(border.loc[border.start_month.eq(month)&border.month.ne(month),'overlap_minutes'].sum()) if len(border) else 0.
        elapsed_start = float(t.elapsed_start_minutes.sum())
        natural = float(t.overlap_minutes.sum())
        assert np.isclose(natural,elapsed_start+carry_in-carry_out,atol=1e-5)
        result['boundary_months'][month] = dict(observed_overlap_minutes=natural, elapsed_start_minutes=elapsed_start, observed_carry_in_minutes=carry_in, observed_carry_out_minutes=carry_out)
    # Absolute changes are usually small: display direct values and a zero reference.
    fig, axes = plt.subplots(1,2,figsize=(11,4.5),layout='constrained')
    names = ['Recorded, start month','Elapsed, start month','Elapsed, calendar split']
    for j,month in enumerate(MONTHS):
        values = [result['months'][month][f] * 100 for f in ['recorded_start_utilization','elapsed_start_utilization','overlap_utilization']]
        bars = axes[0].bar(np.arange(3)+(j-.5)*.35, values,.35,label=month)
        axes[0].bar_label(bars,fmt='%.4f',fontsize=8)
        t = fg.loc[fg.month.eq(month)&fg.guns.ge(5)]
        delta = np.sort((t.overlap_utilization-t.elapsed_start_utilization)*100)
        axes[1].plot(delta,np.arange(1,len(delta)+1)/len(delta),label=month)
    axes[0].set(xticks=np.arange(3),xticklabels=names,ylabel='Utilization (%)',title='Fixed common stations: same capacity')
    axes[0].tick_params(axis='x',labelsize=8); axes[0].set_ylim(0,11); axes[0].legend()
    axes[1].axvline(0,c='gray',lw=1)
    axes[1].set(xlabel='Calendar split - elapsed start-month (percentage points)',ylabel='Cumulative fraction of grids',title='Boundary effect, grids with at least 5 guns'); axes[1].legend()
    fig.supxlabel('Observed intervals only. Unknown prior-month carry-in is unavailable; no energy allocation or overlap correction.',fontsize=8)
    fig.savefig(figs/'01-calendar-month-comparison.png',dpi=180);plt.close(fig)
    # Every retained crossing session is inspectable in the derived parquet.
    fig,ax=plt.subplots(figsize=(9,4),layout='constrained')
    ms = list(result['boundary_months'])
    ax.bar(ms,[result['boundary_months'][m]['observed_carry_in_minutes']/60 for m in ms],label='Observed carry-in')
    ax.bar(ms,[-result['boundary_months'][m]['observed_carry_out_minutes']/60 for m in ms],label='Observed carry-out')
    ax.axhline(0,c='gray',lw=1);ax.set(ylabel='Session-hours',title='Boundary redistribution in all retained observed sessions');ax.legend()
    fig.supxlabel('Month-boundary transfers only, not complete monthly coverage. Half-open [start,end) intervals.',fontsize=8)
    fig.savefig(figs/'02-boundary-transfers.png',dpi=180);plt.close(fig)
    # Extra descriptive view: calendar weekday and start hour, normalized for day counts.
    days = [pd.date_range(m+'-01',periods=31,freq='D') for m in MONTHS]
    rates = np.array([hourly[j]/np.bincount(days[j].dayofweek,minlength=7)[:,None]/fixed.loc[fixed.month.eq(MONTHS[j]),'guns'].sum()*100 for j in range(2)])
    fig,axes=plt.subplots(1,2,figsize=(12,4),layout='constrained')
    for j,ax in enumerate(axes):
        artist=ax.imshow(rates[j],aspect='auto',vmin=0,vmax=rates.max(),cmap='YlOrRd')
        ax.set(yticks=np.arange(7),yticklabels=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'],xticks=np.arange(0,24,3),xlabel='Session start hour',title=MONTHS[j])
    fig.colorbar(artist,ax=axes,label='Starts / 100 guns / calendar weekday-day / hour')
    fig.supxlabel('Common stations; daily normalization per day-of-week. Holidays and make-up workdays not reclassified. Arrival counts, not charging load.',fontsize=8)
    fig.savefig(figs/'03-weekday-hour-arrivals.png',dpi=180);plt.close(fig)
    result['weekday_hour']={'arrival_counts':hourly.tolist(),'rates_per_100_guns_day_hour':rates.tolist(),'calendar_weekday_counts':[np.bincount(d.dayofweek,minlength=7).tolist() for d in days]}
    # Concentration across a fixed set of grid cells, not demographic fairness.
    fig,axes=plt.subplots(1,2,figsize=(11,4.5),layout='constrained'); result['concentration']={}
    for j,month in enumerate(MONTHS):
        t=fg.loc[fg.month.eq(month)]
        result['concentration'][month]={}
        for field,label in [('guns','Guns'),('start_orders','Session starts'),('start_energy_kwh','Start-month energy')]:
            x,y,gini=lorenz(t[field]); axes[j].plot(x,y,label=f'{label}, Gini={gini:.3f}')
            result['concentration'][month][field]=gini
        axes[j].plot([0,1],[0,1],c='gray',lw=1);axes[j].set(title=month,xlabel='Cumulative share of grids (sorted separately)',ylabel='Cumulative share of quantity');axes[j].legend(fontsize=8)
    fig.supxlabel('Common-station grids, equal grid weights. Each variable sorted independently. Concentration, not accessibility or unmet-demand evidence.',fontsize=8)
    fig.savefig(figs/'04-grid-concentration.png',dpi=180);plt.close(fig)
    for p,h in hashes.items(): assert digest(ROOT/p)==h
    (out/'analysis_manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (figs/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    report = ['# 自然月占用时长对照','',f'运行：{run}。共同活跃站点{len(common)}个。原始文件和基准清洗文件均未修改。','',
        '计算：把会话视作左闭右开的[start,end)区间，取其与每个自然月的交集。23:30开始、次月00:30结束的会话，两个自然月各计30分钟、各占会话时长50%。恰在月初00:00结束，不在新月生成零分钟记录。',
        '主指标使用时间戳实际间隔。额外保留“记录duration_min按交集比例分摊”列用于时长字段口径对照，分摊后总分钟数守恒。未分摊电量、费用或整笔订单数。重叠会话尚未合并，该指标为会话区间时长之和，不是去重后的物理枪占用。','',
        '| 月份 | 原记录时长整笔归开始月 | 时间戳间隔整笔归开始月 | 可观测自然月拆分 | 月界影响（百分点） |',
        '| --- | ---: | ---: | ---: | ---: |']
    for month,r in result['months'].items(): report.append(f"| {month} | {r['recorded_start_utilization']:.6%} | {r['elapsed_start_utilization']:.6%} | {r['overlap_utilization']:.6%} | {r['boundary_delta_pp']:+.6f} |")
    report += ['',f"全样本识别{totals['cross_month_sessions']:,}笔跨月会话。起止间隔与记录时长最大差异为{totals['max_duration_discrepancy_minutes']:.6f}分钟。交集时长与完整时间戳间隔总和一致，按比例分配的记录时长与原记录时长总和一致。",'',
        '## 解释边界','', '比较固定共同站点和静态枪数，使月界影响与容量样本变化分离。全部站点的派生表中，每月容量来自当月有开始或区间重叠的站点并集，不宜直接与旧活跃站点口径相减。',
        '只有1月和7月来源文件，不能保证提供全部12月底开始延续进1月的会话，也不能保证提供全部6月底开始延续进7月的会话。6月30日已观测记录可带入7月，但缺失的边界会话无法补造。实际派生出1月、2月、6月、7月，2月和6月只有片段，不代表完整月份。自然月拆分不会恢复未观测数据。',
        f"窗口端点核查：1月文件最晚结束于{source_ranges[sources[0].name]['end_max']}；7月文件最晚结束于{source_ranges[sources[1].name]['end_max']}。各文件起止范围见完成清单；未观察到的跨月会话不能视为实际不存在，也不能仅据此断言截断或筛选的具体原因。严格两月比较仍需核实发布文件的入样及结束时间处理规则。",
        '因此这里只是现有样本的自然月时长敏感性对照。若要求严格自然月利用率，需要相邻月完整订单或至少完整边界会话，以及设施开放时间。', '',
        '## 新文件','',f'- 派生数据：`{out.relative_to(ROOT)}`，含站点月表、网格月表、固定共同站点网格表、跨月分段核对表和完成清单。',f'- 图表与数值：`{figs.relative_to(ROOT)}`。',
        '- 新增自然月对照、月界流入流出、星期×小时到达热图、网格集中度曲线。热图仅按自然星期分类，未把周一至周五称为法定工作日。集中度只描述网格数量分布，不代表人口公平性或供给缺口。']
    (ROOT/'reports/calendar_month_review.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    print(json.dumps({'out':str(out),'figures':str(figs),'months':result['months'],'totals':totals},ensure_ascii=False,indent=2),flush=True)


if __name__ == '__main__': main()
