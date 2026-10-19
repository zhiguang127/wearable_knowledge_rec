"""Publish privacy-checked aggregates and a Chinese readout after real execution."""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
from statistics import mean
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from src.common import read,rows,sha,write,digest
from src.q1_pilot.evaluation import clustered

def fmt(x):return '—' if x is None else f'{x:.3g}'

def main(name,supplement):
    run=ROOT/'local/experiments/q1_pilot'/name;flowrun=ROOT/'local/experiments/q1_pilot'/supplement
    summary=read(run/'summary.json');rs=rows(run/'records.jsonl');flow=read(flowrun/'summary.json');excluded=read(run/'excluded.json')
    config=read(ROOT/'experiments/q1_pilot/config.json');cid=digest(config)
    if summary['config_id']!=cid or flow['config_id']!=cid:raise ValueError('configuration changed')
    selected={r['case_id'] for r in rs};n=len(selected)
    per_case=Counter(r['case_id'] for r in rs)
    if not all(v==90 for v in per_case.values()):raise ValueError('incomplete per-case conditions; do not publish a partial run as complete')
    errors=[r for r in rs if r['status']!='TASK_ADAPTED_AND_RUN']
    same_game=[]
    for method in ('RankingSHAP','ShaRP','RankingSHAP_listwise','ShaRP_outcome'):
        a=[r for r in rs if r['method']==method and r['status']=='TASK_ADAPTED_AND_RUN' and
           (method!='RankingSHAP' or r['kernel_nsamples']==2**r['n_groups']-2)]
        z=[{'subject_id':r['subject_id'],**r['metrics']} for r in a]
        same_game.append({'method':method,'records':len(a),'participant_mae':clustered(z,'mae'),
          'max_absolute_error':max((r['metrics']['max_abs_error'] for r in a),default=None),
          'max_efficiency_residual':max((r['metrics']['efficiency_residual'] for r in a),default=None),
          'failed_records':sum(r['status']!='TASK_ADAPTED_AND_RUN' for r in rs if r['method']==method)})
    primary=[]
    for policy in ('additive','interaction'):
        a=[r for r in rs if r['method']=='exact_source' and r['panel']=='p1' and r['donor_strategy']=='latest' and r['n_groups']==6 and r['policy']==policy]
        flip=top1=top2=0;deltas=[]
        for r in a:
            s0,s1=r['all_scores']['0'],r['all_scores']['63'];deltas.append(r['values'][-1]-r['values'][0])
            key=lambda s:sorted(s,key=lambda k:(-s[k],k))
            margin=lambda s:s['K006']-s['K017']
            sign=lambda x:1 if x>1e-12 else -1 if x<-1e-12 else 0
            flip+=sign(margin(s0))!=sign(margin(s1));top1+=key(s0)[0]!=key(s1)[0];top2+=set(key(s0)[:2])!=set(key(s1)[:2])
        primary.append({'policy':policy,'windows':len(a),'margin_change_min':min(deltas),'margin_change_max':max(deltas),
          'pair_order_changed':flip,'canonical_top1_changed':top1,'canonical_top2_changed':top2,
          'max_exact_efficiency':max(r['metrics']['efficiency_residual'] for r in a)})
    diagnostics=[r['diagnostics'] for r in rs if r['method']=='donor_diagnostics']
    derived=[r['derived'] for r in rs if r['method']=='derived_negative_control']
    coverage={'participants_screened':16,'windows_screened':48,'eligible_participants':summary['eligible_participants'],'eligible_windows':n,
      'excluded_windows':len(excluded),'exclusion_reasons':dict(Counter(r['reason'] for r in excluded)),
      'donor_window_strategy_assignments':summary['donor_window_counts'],'distinct_real_donor_blocks':summary['unique_donor_blocks'],
      'background_samples_per_condition':1,'donor_interpretation':'one selected real week per strategy, reused across all source groups; NOT six independent backgrounds',
      'max_one_sided_seam_jump_minutes':max(d['one_sided_seam_sleep_jump_max_minutes'] for d in diagnostics if d['one_sided_seam_sleep_jump_max_minutes'] is not None),
      'coverage_delta_min':min(d['usable_sleep_coverage_delta'] for d in diagnostics),'coverage_delta_max':max(d['usable_sleep_coverage_delta'] for d in diagnostics)}
    decision={'overall':'INCONCLUSIVE','gate1':'NOT_OBSERVED_IN_TESTED_POLICIES','gate2':'NO_NEW_ALGORITHM_JUSTIFICATION',
      'scoped_action':'NO-GO for developing a new algorithm motivated by this tested same-source masking phenomenon',
      'reason':'No independent real ranker or untouched cohort. On tested policies aligned official methods match exact references; finite-budget noise and interface fixes explain observed discrepancies.'}
    result={**summary,'coverage':coverage,'full_budget_same_game':same_game,'primary_raw_behavior':primary,'canonical_flow':flow,'decision_detail':decision,
      'exact_reference_records':sum(r['method']=='exact_source' for r in rs),
      'derived_control':{'records':len(derived),'coalitions_per_record':512,'max_own_game_efficiency_residual':max(d['efficiency_residual'] for d in derived),
        'independent_derived_score_evaluations':len(derived)*512,'cross_game_mae':None},
      'failure_denominator':{'planned_condition_records':n*90,'actual_condition_records':len(rs),'failed_or_blocked_records':len(errors),'excluded_before_conditions':len(excluded)},
      'additional_resources':{'derived_score_feature_calls':len(derived)*512,'behavior_raw_pipeline_scorer_calls':n*3*6,
        'native_smokes_not_query_budget_comparisons':True,'canonical_flow':flow['total_raw_scorer_calls'],'noncoalition_probe_calls':flow['probe_scorer_calls']},
      'provenance':{'full_manifest_sha256':sha(run/'manifest.json'),'full_records_sha256':sha(run/'records.jsonl'),
         'source_snapshot_sha256':sha(run/'source_snapshot.json'),'canonical_flow_manifest_sha256':sha(flowrun/'manifest.json'),
         'config_file_sha256':sha(ROOT/'experiments/q1_pilot/config.json'),'analysis_code_sha256':sha(Path(__file__))}}
    # Never publish a partial execution or an identity-bearing aggregate.
    text=json.dumps(result,ensure_ascii=False)
    all_cases=rows(ROOT/'data/releases/p1-v2/cases.jsonl')
    for c in all_cases:
        if c['case_id'] in text or c['subject_id'] in text:raise ValueError('private identity leaked')
    public=ROOT/'experiments/q1_pilot/results';public.mkdir(exist_ok=True)
    write(public/'summary-v1.json',result)
    # Static research figure, only participant aggregates, no personal trajectories.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(10,3.7),layout='constrained')
    for ax,ng in zip(axes,(6,8)):
        for policy,color in [('additive','#2563eb'),('interaction','#d97706')]:
            a=[r for r in summary['aggregate_metrics'] if r['method']=='RankingSHAP' and r['panel']=='p1' and r['donor_strategy']=='latest' and r['policy']==policy and r['n_groups']==ng]
            a.sort(key=lambda r:r['kernel_nsamples']);x=[r['unique_coalitions']['mean'] for r in a];y=[max(1e-16,r['mae']['mean']) for r in a]
            ax.plot(x,y,'o-',label=policy,color=color)
            lo=[max(1e-16,r['mae']['ci95'][0]) for r in a];hi=[max(1e-16,r['mae']['ci95'][1]) for r in a]
            ax.fill_between(x,lo,hi,color=color,alpha=.12)
        ax.set_title(f'{ng} source groups / {2**ng} possible coalitions',fontsize=10)
        ax.set_xlabel('Actual unique scorer evaluations');ax.set_ylabel('Participant mean attribution MAE')
        ax.set_yscale('log');ax.grid(alpha=.18);ax.spines[['top','right']].set_visible(False);ax.legend(frameon=False,fontsize=8)
    fig.savefig(public/'budget-error-v1.png',dpi=180);plt.close(fig)
    md=[]
    def line(s=''):md.append(s)
    line('# Q1 Pilot 排序解释问题验证结果')
    line();line('本轮已实际实现并执行。总体判断为 **INCONCLUSIVE**：外部真实排序器与独立参与者验证缺失；在已测试的透明政策范围内，**没有观察到支持新算法的强方法残余失败**。因此不推进由该现象驱动的新算法开发。')
    line();line('## 研究问题与解释范围');line();line('检验原始来源一致、目标明确和预算可追溯时，现有解释方法能否计算影响知识相对选择的纵向证据。主目标为 K006−K017 的连续评分差；margin、成对结果、名次、top2 与列表 Kendall 目标分别评价。Shapley Flow 的边游戏单独验证。没有使用 Silver/人工 Gold、付费 API 或训练。')
    line();line(f'冻结配置 ID：`{cid}`。原始配置文件 SHA：`{result["provenance"]["config_file_sha256"]}`。完整输入发布 ID、权重、阈值、种子、来源分组与 donor 规则见 ../experiments/q1_pilot/config.json 和 protocol.md。')
    line();line('## 样本与完整分母');line();line(f'筛查 16 人、48 窗；纳入 **{summary["eligible_participants"]} 人、{n} 窗**，排除 {len(excluded)} 窗。条件记录计划 {n*90}、实得 {len(rs)}、失败/阻碍 {len(errors)}；未因方法结果筛选窗口。')
    line();line('| 排除原因 | 窗口数 |');line('|---|---:|')
    for reason,count in coverage['exclusion_reasons'].items():line(f'| {reason} | {count} |')
    line();line(f'固定候选对 1 个。P1 保留 5 候选，A1 duration_and_timing 保留 4 候选；A1 26 条知识没有全部跑遍。两策略各 {n} 次 donor 分配，共 {coverage["distinct_real_donor_blocks"]} 个不同真实七日块；每条件只有一个背景周，重复映射至 42 日，不能当六个独立 donor。')
    line();line(f'拼接诊断：一侧接缝睡眠跳变最大 {fmt(coverage["max_one_sided_seam_jump_minutes"])} 分钟；可用睡眠覆盖差范围 [{coverage["coverage_delta_min"]}, {coverage["coverage_delta_max"]}] 日。所有模态/缺测/质量随整块替换，目标日号、星期和 phase 保留。真实周的周期性复用与接缝自然性未获生理验证，这些结果不能视为真实生活干预。')
    line();line('## 评分器行为先验收后解释');line();line('F-Additive 只在声明的统计特征上加权；F-Interaction 增加 short×gap、clock×adjacent 与有序趋势项。两者都是手写实验政策，不是两个独立真实模型；420 分钟等常数只是实验政策参数。原 null 保持 null；统计缺失映射到显式中性政策特征并另保留覆盖。零 RHR 排除，非零/未知 sleep infoCode 的睡眠不进入生理特征。')
    line();line('| 政策 | 控制 | 有响应窗 / 纳入窗 | 成对顺序变化 | Top1 变化 | Top2 变化 |');line('|---|---|---:|---:|---:|---:|')
    for b in summary['behavior']:line(f'| {b["policy"]} | {b["control"]} | {b["responsive_windows"]}/{b["windows"]} | {b["pair_changed"]} | {b["top1_changed"]} | {b["top2_changed"]} |')
    line();line('上述人工变化是机制检查，不保证生理可行。reverse_current 保留当前期值的集合及均值/波动，改变顺序；加性 margin 应不变，交互政策可以响应趋势。未使用 context 字段和 item-only 全部检查不变性。行为表 top-k 采用分数后候选 ID 确定性打破 ties；独立 top2 QoI 则采用竞争名次、边界 ties 全纳入，二者没有混算。')
    line();line('## 方法的真实运行状态');line();line('| 方法 | 官方固定提交 | 原生验证 | 任务执行与偏离 |');line('|---|---|---|---|')
    descriptions={'RankingShap':'TASK_ADAPTED_AND_RUN：官方共同遮蔽与 KernelSHAP；来源选择器和 margin callback；列表 Kendall 另报',
      'ShaRP':'TASK_ADAPTED_AND_RUN：官方 _shapley 与 diff QoI；完整个人管线 margin/结果/名次/top2 wrapper，不冒称原生 item-row 偏好',
      'Shapley-Flow':'TASK_ADAPTED_AND_RUN：官方 CreditFlow；已知计算 DAG，三条合法切边与节点守恒；不与节点 SHAP 做误差排名'}
    for method_name,native in summary['native_smokes'].items():line(f'| {method_name} | `{native["commit"]}` | {native["status"]} | {descriptions[method_name]} |')
    line('| TimeSHAP | 未获取 | BLOCKED | 可选项本轮未实现、未运行，不能视为已完成强基线覆盖 |')
    line('| 外部真实排序器 | 无 | BLOCKED_EXTERNAL_RANKER_VALIDATION | 两种手写政策不能补足此项 |')
    line();line('原生验证分别执行作者 talent-search notebook、ShaRP plot_basic_usage 的数值工作流及 Flow sample_build_graph。只证明最小原生实现执行，不等于完整论文数据/指标复现。第三方源码跟踪文件未改；依赖 lock 与每次 manifest 保存实际环境。')
    line();line('## 同一游戏上的数值结果');line();line('| 方法与目标 | 完整预算记录数 | 参与者平均 MAE | 最大单项归因误差 | 最大效率残差 |');line('|---|---:|---:|---:|---:|')
    for a in same_game:line(f'| {a["method"]} | {a["records"]} | {fmt(a["participant_mae"]["mean"])} | {fmt(a["max_absolute_error"])} | {fmt(a["max_efficiency_residual"])} |')
    line();line('这些行分别使用各自目标的精确参考，**不构成跨目标方法排名**。margin 为主评价；pair/negative_rank/top2/Kendall 的参考与 margin 的参考不能互换。完整逐条件、按人 bootstrap 的 95% 区间、参与者范围见公开 summary-v1.json 的 aggregate_metrics。')
    line();line('| 政策 | 主 donor 来源替换窗 | 成对顺序改变 | Top1 改变 | Top2 改变 | Margin 变化范围 |');line('|---|---:|---:|---:|---:|---|')
    for a in primary:line(f'| {a["policy"]} | {a["windows"]} | {a["pair_order_changed"]} | {a["canonical_top1_changed"]} | {a["canonical_top2_changed"]} | [{fmt(a["margin_change_min"])}, {fmt(a["margin_change_max"])}] |')
    line();line(f'共 {result["exact_reference_records"]} 个来源游戏精确枚举；6 组 64 coalition、8 组 256 coalition。主 donor 周在 foreground 的对应 baseline 块上可能完全相同，因而该来源可以是 dummy；不能把名义维度当有效独立因素数。')
    line();line('## 预算与敏感性');line();line('RankingSHAP 的 nsamples 不含背景/前景；图横轴使用实际唯一端到端 scorer 调用，冷缓存按方法/种子/预算独立重建。6 组预算 16/32/62，8 组 16/32/64/128/254；满枚举以后没有伪称更高预算带来更精细近似。曲线阴影是参与者 bootstrap 区间，低预算种子为 0/1/2。')
    line();line('![同游戏预算误差曲线](../experiments/q1_pilot/results/budget-error-v1.png)')
    line();line('已运行最早/最近两个本人基线 donor 策略、6/8 组粒度和 A1 面板扩展。它们共享参与者，不增加独立样本数。A1 主 margin 的权重不依赖候选全集，所以此扩展不能证明候选集合依赖机制已被检验。多背景期望、条件分布和跨参与者 donor 都未执行。')
    line();line(f'主运行端到端 scorer 实际计算 {summary["total_resources"]["raw_pipeline_scorer_calls"]} 次，查询请求 {summary["total_resources"]["query_requests"]} 次；方法计算累计 {fmt(summary["total_resources"]["method_seconds"])} 秒，运行约 {fmt(summary["seconds"])} 秒。独立派生坐标政策评估另有 {len(derived)*512} 次；前置行为控制另有 {n*18} 次。官方原生 smoke 的时间单独记录，未把其调用混入健康预算曲线。')
    line();line('## 图归因与独立诊断');line();line(f'canonical Flow 覆盖 {flow["participants"]} 人、{flow["windows"]} 窗、{flow["records"]} 个政策条件，每条件 64 次 timeline，另独立重建图重复一次；固定 seed 边归因一致：{flow["canonical_seed_replay_identical"]}。最大切边守恒残差 {fmt(flow["max_cut_residual"])}，节点守恒残差 {fmt(flow["max_node_conservation_residual"])}。')
    line();line(f'该补充运行含 {flow["total_raw_scorer_calls"]} 次端到端 raw pipeline 计算、{flow["total_all_candidate_score_node_evaluations"]} 次全候选评分节点评估。节点内重算和解释器调用不同，不能把它与 KernelSHAP 按同一函数调用数量直接排效率。原生小 DAG 另用官方精确 divide_and_conquer 与 boundary_graph 检查切边一致性：x、z 贡献分别为 3、2，折叠边界后保持一致。真实图本轮主要验证守恒，不据此声称全部边分配具有外部正确性。')
    line();line(f'新增 {flow["noncoalition_probes"]} 个逐块 +30 分钟数值探针，{flow["responsive_probes"]} 个 margin 响应、{flow["pair_changed_probes"]} 个成对顺序改变。它们独立于二元 Merge 游戏，属于额外软件诊断而非预注册确认性证据，不要求另一种 game 的 Shapley 值预测其影响。')
    line();line('原逐块删除诊断复用了精确枚举中的 coalition，故**不是独立留出评价**；只报告描述统计，不能用于泛化主张。派生坐标负对照则在自己的 9 特征/512 coalition 游戏中检验效率，不计算它相对原始来源归因的 MAE；差异首先属于估计对象不同。')
    line();line('## 正反例与失败归因');line();line('阳性控制：仅改变历史或近期观测均能改变政策 margin，部分变化跨越真实政策排序边界；因此解释对象确实利用纵向输入。阴性控制：item-only 的来源归因全零；未使用字段改变不影响输出。加性/交互解析性质、dummy、对称性、效率、来源置换、未来 donor 拒绝与联合重算均有数值测试。')
    line();line('发现并排除的接口问题：RankingSHAP 官方 constructor 以零占位预测器建立 fnull，随后才换 query 模型。测试中真实背景值 2、前景值 3，未修复会把归因总和算成 3；适配器按真实 query 重新初始化官方 KernelExplainer 后，正确解释差值 1。属于第 2 类接口问题。原始官方源码未修改，修复前测试与日志保留。')
    line();line('另一个可重放性问题：Flow Graph 将节点放入 set，有限 Monte Carlo 的抽样顺序会依赖对象遍历。adapter 只规范输入节点次序；full-v1 旧实现与结果有独立源码快照，canonical 补充运行没有覆盖它。')
    line();line('低预算与精确参考的差异归为第 5 类采样/预算；独立派生列与原始来源的差异归为第 4 类 estimand 不同；周块平铺的自然性风险归为第 6 类背景限制。没有在排除前述因素后建立第 7 类算法/结构残余失败。来源字节与历史资产校验不能代替医学来源语义确认。')
    line();line('## 不确定性与边界');line();line('统计按参与者先求均值再 bootstrap，重复 1000 次；没有把窗口、候选或 coalition 当独立人。仅 14 位纳入参与者且都曾暴露于历史研究，不能作新队列确认。没有学习/LLM 排序器、多样外部背景、时间模态扩展、真实优先级标签或临床结果。精确参考是本研究声明游戏的程序真值，不是医学最优推荐。')
    line();line('## Gate 1 与 Gate 2 决策');line();line('**Gate 1：测试范围内未观察到强方法残余失败。** 同游戏满预算结果达到浮点精度；低预算误差、接口背景偏移、跨游戏差异与 donor 自然性不能作为算法失效证据。Flow 守恒通过也不等于证明所有边归因外部有效。')
    line();line('**Gate 2：没有支持新算法必要性的证据。** 联合重算和现有官方方法已经解决本轮可测的数值解释问题。当前结论不足以提出新算法或 SIGIR 创新。整体仍为 **INCONCLUSIVE**，因为本轮只有透明政策，外部真实排序器未验证。下一轮不推进新算法开发；只有要检验外部有效性时，才有理由另行扩展到独立真实排序器、未接触参与者和更自然的背景分布。')
    line();line('## 执行记录与复现');line();line(f'主运行：`local/experiments/q1_pilot/{name}/`；补充运行：`local/experiments/q1_pilot/{supplement}/`。两处私有 records、manifest 和 stdout/stderr 均保留；公开目录只有配置、源码、依赖锁、聚合 JSON 和聚合图。来源：官方 [RankingSHAP](https://github.com/MariaHeuss/RankingShap)、[ShaRP](https://github.com/DataResponsibly/ShaRP)、[Shapley Flow](https://github.com/nathanwang000/Shapley-Flow)。')
    line();line('改动前检查为 q1-preflight-v1；最终测试与含旧项目的校验记录由本次 final 检查独立保存。检查数量与退出码见 VALIDATION_Q1.md。旧迁移报告未回写。')
    doc='\n'.join(md)+'\n'
    for c in all_cases:
        if c['case_id'] in doc or c['subject_id'] in doc:raise ValueError('identity in readout')
    dest=ROOT/'docs/Q1_PILOT_READOUT.md'
    with dest.open('x',encoding='utf-8',newline='\n') as f:f.write(doc)
    print(json.dumps({'readout':str(dest),'summary':str(public/'summary-v1.json'),'decision':decision,'coverage':coverage,'same_game':same_game},ensure_ascii=False,indent=2))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--run',required=True);ap.add_argument('--supplement',required=True);a=ap.parse_args();main(a.run,a.supplement)
