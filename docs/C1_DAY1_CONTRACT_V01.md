# Day 1 统一实验合同 v0.1

项目：Longitudinal Evidence-Grounded Personalized Knowledge Ranking。
基础版本：C1 Benchmark V2.2-r1。2026-10-20 接收本合同。
状态：**待冻结；禁止启动正式 Baseline 比较**。
时间目标：7 天内完成 C1 创新性初步验证，C2 依标签进展开展最小实验。

本文件落实用户提供的合同，作为新一轮工作依据。历史 V2/V2.2 的标签、原始响应、失败、冻结数据及当前模型配置均保留；旧发布不自动成为本轮合格标签或条件。

## 1. 数据与评测边界

固定 WearableQA 200 人、2,276 个窗口；train/dev/test 按 140/30/30 人隔离。同一人的所有长度、所有窗口均在同一集合，重叠窗口不能当独立参与者。固定 204 条活跃知识，保留来源及条件审核状态；288 个 Probe 涉及 16 个指标、7/14/28 天及 6 种操作；655,488 项预计算结果包括有效值和不足信息状态。

第一轮任务为 **Topic-Conditioned Personal Knowledge Applicability Ranking**。Topic 不自动成为个人 Goal；未给健康目标时 `goal=null`。不评估临床治疗有效性，主题相关性不等于个人适用性。

输入发布身份在 [c1_day1_v01.json](../configs/c1_day1_v01.json) 中固定：

| 资产 | 本地输入 | Release ID |
|---|---|---|
| 数据、划分、注册表 | `data/releases/c1-benchmark-v2.1` | `d2f61a6c6634c0c713cdac76d8594c1ca30bca3d6b78ef4c235ad3eeff07de2e` |
| 修复后知识库 | `data/releases/c1-benchmark-v2.2-r1` | `072ad76eedf22a9bc49b6080e9c1e17006bbb4625e834893befba63615792c1e` |
| 全窗口结果池 | `local/c1-v2/evaluation-coldstart-v1` | `156163d639b9c74a9c2dcd5e0213625133d3f4ef1867245de6e55e026532dad7` |

## 2. 可核验知识条件

正式条件必须保存 `knowledge_id`、`condition_id`、`predicate_id`；原 URL、来源 SHA256、引用锚点及锚点哈希；变量、算子、阈值、单位、窗口长度、偏移、统计操作、比较区间；一个或多个合法 `probe_id`；条件的必要/充分或其他明确作用；AND/OR 及独立语义审核记录。

审核状态为 `VERIFIED / REVIEW_REQUIRED / REJECTED`。知识整体判据、条件连接关系、逐谓词都须完成审核；审核记录保存审核者身份/类型、理由及审核工件哈希。只有 `VERIFIED` 可以形成评价标签。引用文本存在及 hash 匹配只证明引用完整性，不证明医学语义。审核记录中写有 VERIFIED 也不是专家认证，必须保留实际审核来源与层级。

第一批目标为 **6–10 条真实可测知识**，优先睡眠、活动。旧版 22 条 Probe 映射、17 组联合条件不得自动升级。审核队列中的旧映射只用于查找候选；没有明确阈值、强度、时间或角色依据时继续待审，不能为了完成配额创造条件。设备活动小时不能等同中高强度分钟，步数不能等同活动类型或强度；上游 `bed_time_std` 不能视为已知近窗入睡时刻。

Day 1 Schema 对多个合法 Probe ID 的首版支持限定为同一语义的等价定义；不同变量、操作或窗口分别建谓词，并显式审核 ALL/ANY。逐条件记录 `role` 和 `role_rationale`；知识级 `role` 指完整条件表达式的作用。二者的关系也需要来源语义审核，不能把局部角色直接传播到整个表达式。谓词不能孤立当充分条件。必要条件成立不能推出适用，充分条件不成立不能推出不适用。

## 3. 四分类与独立 Annotation Status

| verdict | 严格语义 | reason_code |
|---|---|---|
| `applicable` | 完整有效证据满足已核验适用判据 | `VERIFIED_CONDITIONS_SATISFIED` |
| `not_applicable` | 完整有效证据明确否定已核验适用判据 | `VERIFIED_CONDITIONS_NEGATED` |
| `insufficient_information` | 条件可测，但完整允许记录仍缺有效证据 | `MISSING_VALID_MEASUREMENTS` |
| `not_assessable` | 超出允许测量范围，或没有可核验个人判据 | `UNMEASURABLE_HEALTH_CONTEXT` 或 `NO_PERSONAL_APPLICABILITY_CRITERION` |

未经审核的条件保持待审/未标注，不能直接转成 `not_assessable`。`not_yet_acquired` 仅为获取过程临时状态，不能成为 Gold/Silver verdict。完整条件作用不够决定正负时继续待审，不能冒称数据缺失。

独立字段 `annotation_status=ACCEPTED / REVIEW_REQUIRED / REJECTED`，并保存 `evidence_ids`、`condition_ids`、`model_id`、Prompt/Schema 版本、请求/响应哈希。只有 ACCEPTED 进入主要评价。Qwen 输出统一为 **Silver / Pseudo-Gold**；同模型二次审核仍不是人工 Gold。自由文本 rationale 不在数值完整性验证的保证范围内，不能据此宣称临床有效性或解释忠实性。

## 4. Evidence ID 与完整性

规范 Evidence 为 `(probe_id, status, value, unit, start_time, end_time, missing_reason, source_ref, result_hash)`，另保存 `evidence_id`、`case_id` 与 `computation_hash`。日级 start/end 均为包含端点的 ISO 日期；原数据时区未知，不伪造时区或时刻。

Qwen 仅选择 Evidence ID 并判断含义。模型输入完整提供所有已核验谓词对应的 Probe 结果，包括可读数值、单位、时间与不足信息；后端保存完整来源和 hash，避免让模型复制这些字段。确定性 Provider 绑定值、单位、精确时间、来源、缺失原因及结果 hash。校验 ID 存在、窗口归属、与计算一致的数值/单位/区间、来源/计算哈希和条件语义。新标注要求全部判据所需证据都有引用，包括不足信息结果，不接受无关 Probe 替代。

预计算结果由已固定结果池提供；首次访问与确定性重算逐字段比较，计时字段另报。错误窗口、单位混淆、错误引用、数值矛盾、缺字段会待审或拒绝。不能编辑旧模型返回以获得通过；新 Prompt/Schema/输入必须生成新版本工件，并保留失败。

新离线入口为 `src/day1/annotation.py` 的 `prepare_messages` 和 `finalize`。历史 `src.annotation.c1_v2_pipeline` 仍是历史三分类链路，不能作为 Day 1 正式入口。新代码没有付费执行命令；当前新模型配置的授权额度及请求数均为零。

## 5. Acquisition Environment

统一接口：

```text
reset(query_id, budget) -> Observation
available_actions(state) -> probe_ids
step(probe_id) -> (Observation, cost, done)
rank(query, observed_evidence, candidate_knowledge) -> [(knowledge_id, score, rank)]
```

Observation 包括 Topic/Goal、已获证据及质量/缺失状态、候选允许公开信息及已核验条件、当前排序、剩余预算。Policy 仅接收序列化 Observation 和合法动作 ID，不接收原始 case、Provider、完整结果池、Qwen 标签、Teacher 或 Oracle 输出。后端对象不传入 Policy。当前模块实现此协议；它本身不提供抵抗任意同进程 Python 反射/文件访问的沙箱。运行不受信任 Policy 前须配置独立进程/文件权限隔离。

每次 step 只揭示一个真实预计算结果；不足信息动作也消耗 1 Probe；重复、非法、超预算动作明确拒绝。初态 `initial_probe_ids=[]`，预先定义的初始证据对全部策略一致。没有未来数据；14 天冷启动不能读取窗外 28 天历史。完整结果池只允许后端、离线 Teacher、诊断 Oracle 使用。

主预算是新获得 Probe 数量；实际计算/序列化延迟另报，Probe 数不能称为医疗检查成本。静态数据集上的便宜预计算不证明获取的实际临床价值。

## 6. 冻结 Ranker

首版 `day1-equal-condition-match-v1` 无拟合参数：每个已核验条件相同权重，满足 +1、否定 -1、未知/不足信息 0，再按该知识条件数取均值。分数仅为观测匹配分，不是概率或 Gold verdict。部分证据可输入，未知不当作不成立。条件作用与判据在标签层仍受必要/充分逻辑约束。

同输入稳定；同分保留相同名次，ID 仅用于稳定序列化。每次新证据后重跑同一个 Ranker。所有 C1 Policy 共用同一配置、条件、候选、初态、池、预算。若更换为 LTR，参数只能用 train 拟合、dev 调参，test 最终评价；任何条件或权重改变均需在测试前产生新版本。

## 7. 候选与评价

每个 Query 有固定 `candidate_ids`。首版预案限定 sleep / physical_activity，每主题选 6 条：先按旧映射提示的唯一 Probe 覆盖数降序，再按固定 salt 的 SHA256 排序，所有窗口使用同一主题列表。不读取个人数值、Qwen 标签或排序结果；旧映射不因此升级为条件。每主题前 5 条形成首批 10 条来源审核队列。全部 204 条知识及未选条目保留。

这个预案在来源审核前生成，仍属待冻结配置。若发现条目不能形成可测判据，应记录失败及另建预案版本，不能观察标签后更换候选。同一候选表内须先完成审核再形成正式标签。

**Judged-Slate Ranking**：二值相关性 applicable=1、not_applicable=0。insufficient_information、not_assessable、未标注、待审/拒绝均不作 0；报告其覆盖率。首版 NDCG 将原排序投影到 ACCEPTED 的二值已判断条目，再算 @3/@5；此处 K 是投影后位置。报告 binary coverage，不能外推到全候选。IDCG=0 返回 null，不制造 0。相同分数采用组内排列期望 DCG；Pairwise 只比较正负对，同分记 0.5，没有可比对返回 null。

**Full-Catalog Retrieval**：可以从 204 条重新召回，但只有获得足够全库相关判断后才可声称检验了全库 Recall/NDCG；首轮不具备此资格。

报告 NDCG@K–Budget、Pairwise Accuracy、Valid Measurement Rate、Missing-Evidence Rate、Label Coverage、Acquisition Cost/Latency。测量有效/缺失率分母为已获取 Probe，预算零时为 null；全记录缺失另报。各预算/策略分别先平均同一参与者的 Query，再用户宏平均；95% CI 按参与者进行 2,000 次 percentile bootstrap，seed=20261020。未定义指标报告排除人数和覆盖率；不把多个窗口视为独立用户。用户级区间仍非临床或因果结论。

## 8. Baselines 与 C2

六种方法为 No Acquisition、Random Acquisition、Static Condition Coverage、SHAP-guided AFA、RankingSHAP-guided AFA，以及 Greedy Ranking Gain。预算网格 0/1/2/4/8/16/32，随机 seed 0–4。方法必须共用冻结输入和 Ranker。SHAP/RankingSHAP 名称在此为计划，未实施或复现时保持 BLOCKED，不能改写成论文复现。

Greedy 使用完整池或测试相关标签时只作**不可部署的离线诊断上界**，不加入公平在线策略 Baseline 均值。第一周至少比较三种实际可部署策略，须先通过下述门槛。

C2 只在可靠候选相对排序标签出现后开展。Applicability 正负只能构成有限偏好代理，不是真实知识优先级 Gold。没有目标或偏好时不强制优先级。未满足门槛不启动复杂 Value Predictor 或 C2 联合训练。

## 9. 冻结与开跑门槛

五项全部完成才可将合同置为 FROZEN：

- [ ] 至少 6–10 条知识完成实际条件与 Probe 的来源语义审核。
- [ ] 四分类及独立 Annotation Status 的 Schema 与单元测试通过。
- [ ] Qwen ID 选择、确定性绑定及完整性测试通过。
- [ ] Environment 与 Ranker 输入输出协议固定并验收。
- [ ] 候选抽样、参与者隔离、评价口径、全部配置/实现版本冻结。

当前实现与测试的验收结果另见 [Day 1 验收记录](C1_DAY1_ACCEPTANCE_V01.md)。准备快照的 freeze.json 只封存工程预案字节，**不表示上述五项或实验合同已经冻结**。

正式 Baseline 还有独立门槛：可信 ACCEPTED 正负结果，且同一窗口的候选表出现正负差异；本轮预登记至少 **20 个可判别 Query 列表**作为探索性准入阈值，不把该规模作为统计充分性结论。`readiness` 只计已核验知识、已接受且无验证错误的标签；拒绝重复 Query 或重复标注。

若小批仍全部不足信息，停止算法对比，检查条件与数据测量语义是否匹配；通用教育、超范围背景和未审核条件各自保留状态，不强行制造负标签。

## 10. 七天完成标准与复现

一周目标依次是：标签与证据引用链路可重复审计；真实新增测量能区分候选；三种以上可部署策略公平比较；有效 NDCG–Budget 曲线及离线 Oracle 上界；判断是否出现超出传统 SHAP/AFA 的 Ranking Acquisition Signal。没有这些结果就保留否定/不确定结论，不以完整复现四篇论文为本周目标。

建议顺序：Day 1 合同和来源审核；Day 2 可信小批标签及 20 表门槛；Day 3 固定 Ranker 与三种基础策略；Day 4 SHAP/AFA 可行性；Day 5 RankingSHAP/Oracle；Day 6 用户级曲线及消融；Day 7 判定 C1，按标签决定是否做 C2。后续日期以门槛通过为前提，不能为赶时间越过标注问题。

从仓库根目录执行，仅标准库，不联网、不调用模型，输出目录必须全新且在忽略的 local/ 下：

```powershell
python -m unittest tests.test_day1 -v
python -m src.day1.prepare prepare --output local/day1/prepared-v01-r2
python -m src.day1.prepare verify --output local/day1/prepared-v01-r2
python -m unittest discover -s tests -v
```

prepare 核对三个输入发布的完整文件清单/SHA256、655,488 项结果内容哈希与窗口/Probe 唯一键、200 人隔离、注册表维度和数量；写入候选预案、来源审核队列、Schema、实现哈希和明确 BLOCKED 报告。verify 重验快照、实现与输入发布；失败返回非零。不重新计算全部个人统计、不写回历史资产，不把这些完整性检查当作来源语义或医学验证。
