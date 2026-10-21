# Day 2 — C1-Ranking-Conditions 可行性先导协议 v0.1

状态：训练集内先导预登记；不是正式 Benchmark 冻结。以 `configs/c1_day2_pilot_v01.json` 和准备目录的 freeze.json 为机器依据。配置、来源选择、抽样、候选、rubric、诊断 Ranker、效用和判据在查看个人测量及相关性判断前固定。

本轮只研究 RQ1 相关性可判定性、RQ2 个人证据的判别贡献、RQ3 新增 Probe 的潜在排序价值。H、R、V 分开：建议目标不转为个体前提，不从 Topic 推断 Goal，不推断临床优先级。没有独立人工 Gold 时，正式相关性准确率、NDCG 与真实获取收益为 null。

## 输入核验和知识重建

核对 Day 1 v0.4 配置、Schema、5 项错误映射复核、来源抽取/历史接受代码、真实 QA 与发布哈希。实测输入回归为 163/163 通过。保留全部历史知识、模型原响应与失败；本轮新增文件在 src/day2、独立配置和 local/day2 中。

固定来源：MyHealthfinder 的 Get Enough Sleep、Get Active、Stay Active as You Get Older、Stay Active with a Disability，每个 API section 为完整单元；MedlinePlus 的 Healthy Sleep、Benefits of Exercise、Exercise and Physical Fitness、How Much Exercise Do I Need，各完整 full-summary 为一个单元。保留所有段落、短导语、列表、标题与全文上下文，不用 Day 1 活跃/待审标签决定纳入。预计且已由来源结构确认 21 单元（睡眠 9、活动 12），不按个人观测或新标签剔除不利单元。

新 ID 为 C1RC-内容/来源身份哈希，SP2- 为确定性来源块 ID；正文、原始 HTML 和来源文件分别保存哈希。Qwen 仅选择来源 Span ID，后端绑定原文，避免再次自由复制引用。来源审查与个人相关性为分离任务：前者不接触个人值或查询，不将模型意见自动升级为 VERIFIED。人群、硬动作触发、建议目标、行为/状态与时间分项登记，角色和 AND/OR 不明时保留未知。

源文完整不等于语义已获独立专家确认。年龄/症状/药物/残疾、夜间事件、活动类型/强度等仍未观测；逐日目标不等价于多日统计。21 单元的粒度不同且内容有重叠，是先导的已知限制。精确硬条件兼容率在独立审核前不可用；描述性相关联系另行报告。

## 查询、抽样和证据对照

按冻结 salt 对 train 的 subject_id 哈希排序，取前三人；每人只选一个 history_days=42 的窗口，再按 case_id 哈希选定。不存在对应窗口时失败，不按结果替补。dev/test 完全不使用；同一个人的全部先导上下文均属 train。

3 人 × Sleep/Physical Activity × Topic-only/明确合成 Goal = 12 个上下文；每个上下文纳入该主题的全部重建单元。Goal 是“理解最近记录的睡眠时长/活动变化并选择相关教育内容”，不是观察到的用户偏好。查询中明确禁止假定年龄、失眠、减重、诊断、活动强度或类型。

| 条件 | 对模型和诊断 Ranker 开放的信息 |
|---|---|
| A | Topic/Goal；没有个人证据 |
| B | A + 对应指标 14 日 mean |
| C | B + 同指标 14 日 mean_difference（对比之前 28 日），获取成本 1 |
| D | B + 无关 rhr 14 日 mean，获取成本 1；诊断负对照 |
| F | 离线参考判断，全 288 Probe；不交给模拟在线入口 |

Sleep 对应 sleep_duration，Activity 对应 steps。所有 Probe 均从冻结注册表按精确 metric/operation/window/offset 唯一查找。Provider 核验窗口、数值、单位、状态、来源与计算哈希；缺失/不足仍计成本。模型只选择 Evidence ID，不输出测量数值。相同 Topic/Goal 的 A 请求在三人间完全相同，只调用一次并复用：4 个 A + 36 个 B/C/D + 12 个 F = 52 个不同相关性请求，另有 21 个来源审查请求；这是固定任务数，不是新设的调用/金额额度。失败与不利结果保留，不为获得期望标签重采样或重试。

F 在后端独立构造，完整结果在模拟环境创建之前计算也不会加入在线请求；边界通过 payload 重建核验，而不是声称 Python 后端对象是安全沙箱。在线排序入口没有 Provider、完整池或标签参数。初始证据、候选与 Ranker 在 C/D 之间相同。

## R rubric 和标注

0 为对明确评价问题不相关；1 为相关背景；2 为直接相关；3 为尤其具体的相关性。2/3 可由明确 Topic/Goal 本身支持，不要求先存在异常。需要的个人证据或背景未知时可给 null；并列允许，null 不视为零或并列。是否满足来源建议目标不是排序的自动优先级规则。

每条判断选择自身来源 Span IDs，使用个人证据时选择当前包中 COMPUTED 的 Evidence IDs；引用错误条目、未获取/跨窗口证据、其他来源块或不足结果作为肯定依据会被拒绝。只对四个预登记来源位置开放“描述性个人证据关联”：睡眠 Overview/Medline Healthy Sleep，活动 Track Progress/Medline Exercise and Physical Fitness。此保守边界可使模型丢失合法关系，其覆盖限制另报；它不是全部医学相关关系的定义。

来源单元、源事实审查、相关性 Silver、真实测量和程序诊断分开存储。ACCEPTED 在本先导只表示 Silver 的结构/引用/预登记关联检查通过，**不表示个人相关性语义已独立证实**。模型可能仍有推理错误；不计算模型自我一致性当人工一致性。

## 诊断 Ranker 和 V

采用 `day2-lexical-descriptive-context-v1`，不训练参数：查询/知识词集合 Jaccard，加 0.1 × 固定源联系 × 有效均值指示，再加变化联系 × `abs(delta)/(abs(current)+abs(previous))`，其中 previous=current−delta。缺失和全零分母贡献 0，表示无可用排序特征，不是条件不成立。变化联系仅给 Medline Healthy Sleep 和 Get Active/Track Progress，均为预登记研究假设；这些数值权重不是来源医学阈值。代码及 stopwords 与协议一并封存。

该 Ranker 是可查询的弱诊断工具。来源联系限制和词集合长度会影响结果，不能据它的零收益证明不存在获取价值。相同分数保留并列；仅分数变化不计排序变化。

效用为 graded judged-slate expected-tie NDCG@5，gain=`2^grade−1`。比较 B/C/D 时使用同一 F 参考掩码；未知不填零，仅评价已判定子集，另报覆盖。至少两条已判定且有两个不同等级，否则效用不可判定。没有人工参考时只保存 **Silver proxy**，正式 NDCG 和 Gold ΔU 保持 null。报告正/零/负/不可判定四类，不将排序变化等同收益。

`V(a)=E[U(rank(E∪result(a)))]−U(rank(E))` 的计算函数以合成测试验证；本轮没有可用训练 Gold 支持决策前分布估计，因此预期 V 不估计。获得真实结果后的 Silver proxy ΔU 另报。固定 C/D 不读取隐藏结果或测试标签，不进行模型训练、参数搜索或正式策略 Baseline。

## 人工包、统计及预登记判据

生成 RATER_A/B 两份匿名、顺序不同的完整判断包，52 个包/人；不显示 subject/case ID、arm、Silver、诊断排序或权重。原始证据仅保存在私有包；可供授权的两名独立人类评审。不同证据量本身可能透露实验条件，不能声称完全盲化。源事实另给独立审核包。

模板不算人工判断。导入要求真实身份和盲审声明、完整条目/合法引用；双人分歧必须由第三位不同身份的真实评审裁决。代码验证声明与引用，不能证明物理身份，不能自动填造人工记录。

统计包括来源完整性、条件类别/兼容性限制、H/R/V 覆盖、分级与 pairwise 分布、A/B/C/D/F matched 差异、跨个人变化、真实测量有效/缺失率、Silver proxy ΔU、成本和耗时。按人聚合并以 3 人为 bootstrap 单位（2000 次、固定 seed），明确仅探索性，不能用于总体结论。没有 Gold 不报告其准确率或人工一致性。

预先判据（机器配置为准）：

- 工程成立：历史哈希不变、来源闭包、12 个上下文全部保留、所有接受引用可绑定、在线无隐藏输入、回归通过。
- Silver 候选信号：至少两人、两个上下文存在 B→C 相对等级变化，明确引用新增 COMPUTED 证据和许可来源联系。这只决定是否存在探索线索。
- GO：工程成立，双人独立/裁决参考至少覆盖 8/12 个上下文，至少两人有独立支持的证据相关差异且参考效用非恒定。
- CONDITIONAL_GO：工程可运行，存在合法描述联系，但人工参考/来源裁决等缺失；Silver 可以没有变化。
- NO_GO：完整性/隔离障碍未解决、没有有效真实测量，或知识和允许观测之间没有任何合法描述联系。

GO 也不自动冻结正式 Benchmark。当前没有真实独立评审者，必须先完成其余可执行工作并交付空白评审包；不得假造 Gold 或偷偷调整成功标准。

模型继续使用已授权的不限额配置。Day 2 扩大的是单请求的技术字节上限，以完整传递 288 结果，未放宽任何引用/语义/时间检查；[阿里云官方页面](https://help.aliyun.com/zh/model-studio/qwen3-8-max) 所示上下文支持该规模，用量按北京输入 12、输出 36 元/百万 tokens 估价，账单未知，保留原始账本。

运行与复验命令及实际结果见 Day 2 报告；所有输出使用新目录，不覆盖旧版。
