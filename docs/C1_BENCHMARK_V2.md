# C1 Benchmark V2：真实数据、来源知识与证据探查

2026-10-19。本任务仅建立数据和评估基础设施，不实现 Knowledge-Unlocking Value、M1、RL 或大规模非贪心 AFA。分支 `codex/c1-benchmark-v2` 从 main 创建；旧 PMData、Silver、冻结哈希及实验结果保持原样。V2 使用 [自动 Silver 协议](C1_V2_SILVER_PROTOCOL.md)，不要求本阶段人工逐条审查，也不宣称人工 Gold 或医学验证。

最终实测、133 条活跃知识的目标缺口、有限 Silver 的质量限制和 CNY 3.6332 使用量估价见 [本轮结果](C1_V2_RESULTS.md)；[公开聚合工件](c1_v2_artifacts/aggregate_report.json) 不包含个人记录。

## 真实来源与粒度

WearableQA 官方 GitHub 固定提交为 `39fb7ab5f25127e290e6e7e09e38b4fb3d2d7df3`，实际文件通过 Git LFS media 下载，文件名虽然有 raw，其内容仍是**日级指标及上游统计**。真实结构含 `user_histories`、`mcqs`、`cohort_reference` 和描述性字段；完整文件 40,962,333 bytes、SHA256 `73dedd7290d80b1f0e78f1c51771ef3252a809da66e2484d2cc78cc844c140df`。实测 200 人、119,795 条日记录、16 个指标、4,084 道 MCQ、同人同日重复 0。不是从 README 推算的原始分钟级传感器数据。

Hugging Face 官方副本核验 revision `38ddf7fd0efbe9ce6da66e75b560a33c50dc6721`，实际包含 row/col/csv/markdown/structured 五组 test Parquet。本轮选 GitHub 完整结构化文件，避免按题重复拼接或解析扁平 prompt；没有下载五份冗余渲染数据。上游 MCQ 题目、答案、血检、人口学字段和全队列百分位都不作为 C1 适用性标签或探查基准，不把其答案称为推荐 Gold。

完整源文件、原参与者 ID 和源记录保存在忽略目录；规范观测保留源字段是否存在、原值/null、日期、指标、单位、源质量信息。HMAC 使用独立私有 key，原 ID 映射仅本机保存。缺失不是 0；异常/含义不明值保留并标为不可用于统计。上游没有设备质量、时区、佩戴时长信息时明确记为未知。

| 字段 | 处理与边界 |
|---|---|
| sleep_duration | 官方 renderer 标作 Sleep(h)，按小时保存；每日睡眠汇总，不是入睡事件 |
| steps | 每日步数，不能证明活动强度、姿势或连续久坐 |
| rhr / exercise_avg_hr | bpm；0 不作有效生理观测 |
| sleep_efficiency | 源值保留，观察到的比例尺度不擅自转换为百分比 |
| deep_percentage / rem_percentage | 上游百分比；不能诊断睡眠阶段异常 |
| bed_time_std | 上游已计算的分钟标准差，原始回看范围未说明；不能从中还原入睡时刻或严格的近 14 天作息波动 |
| exercise_count / exercise_hours | 日级次数/小时；小时不能直接等同指南要求的中高强度分钟；含义不明的 0 小时按不可用处理 |
| exercise_mets / vo2_max / hrv | 上游聚合或单位未完整说明，保留原单位状态，只做描述性计算，不推断医学适用性 |
| active_burn / calories_bmr / avg_stress_level | 源 calories/设备评分，未擅自赋予 kcal、症状或临床压力阈值 |

WearableQA 保留 CC BY-NC 4.0 和额外禁止重新识别、临床/诊断/治疗决策、有害/误导使用等条款。许可证、README、renderer、HF 元数据和来源哈希均保存；详见 NOTICE。Git 不包含原始或伪匿名个人数据、绝对日期、划分身份、模型请求/响应或逐条标签。

## 窗口与隔离划分

V2.0 已冻结，后按用户要求新增 **V2.1 的 14 天冷启动**，未覆盖原 V2.0。V2.1 有 2,276 个窗口：14 天 600、42 天 593、90 天 573、180 天 510；124 个计划窗口因日历历史不足保留在排除清单。每人每种长度最多三个从最后观测日向前的非重叠块；不同长度之间允许重叠，不能当独立人样本。

窗口包含 start/end 在内的精确日历天数；只选择不晚于窗口结束日的观测，日历缺测补 null 行。当前期 14 天，此前基线最多 28 天，其他是历史。冷启动只有当前 14 天；基线比较返回不足信息，不调用窗口外观测。14/42/90/180 天还改变可执行长探查的数量，不应比较未经统一可执行性处理的标签准确率。

复用 `src/datasets/splits.py` 的按参与者 SHA256 排序划分与校验，配额 140/30/30，salt 固定。任何人的所有长度、所有窗口同属一个集合；不按标签、缺失、适用性或性能挑选 split。伪匿名 key 私有，复现相同身份/split 需要保留 key；全新 key 会得到不同但仍确定且隔离的划分，应报告新 release ID。公开基准可能进入模型训练，不宣称从未暴露队列。

## 知识构建

MedlinePlus 使用实际下载的 2026-10-17 全主题 XML，只提取白名单英文主题的 NLM `full-summary`，不抓取外链、药品或百科正文。MyHealthfinder v3 实测 HTTP 410，错误猜测的旧文档路径 404，随后按当前官方文档使用公开 v4 `topicsearch.json?Lang=en`；成功返回 104 篇完整文章，无密钥。保留完整 section 上下文、原文和 LastUpdate，按 Terms of Use 署名并保留 logo/链接信息。

固定范围为睡眠、身体活动、压力、健康老龄化和营养。后两类可作为缺乏个人观测支持的真实知识范围，不能假称可穿戴设备测到了饮食/症状。完整 p 或整组列表作为候选单位；列表不拆成失去前提的片段。规范化只解码 HTML/空白，不生成改写或同义句扩容。短片段、临床/药物/治疗内容及精确重复进入排除日志。

实际抽取 **402 条待审候选**：睡眠 40、身体活动 78、健康老龄化 64、压力 46、营养 174；另有 113 条排除。402 不是通过审查的独立知识数。两阶段 Qwen 审查后分别发布 reviewed、active、canonical duplicates、条件索引与质量报告。最终接受数不足 300 时必须报告目标短缺，不能补造重复或无依据条目。

每条记录含 knowledge_id、标题、标准文本、主题/子主题、原始 URL、访问时间、原文件 SHA256、锚点文本/hash、条件需求、角色和用途、ALL/ANY/UNKNOWN、Probe IDs、数据支持状态、不足信息及知识/条件审查状态。条件文本与探查统计分开；探查只是可执行计算，不是自动必要条件规则。

## Probe Schema 与计算

复用现有 `src/common.py` 的 SHA、containment、排他写入，`src/annotation/validation.py` 的 schema 校验和 `src/datasets/pmdata.py` 的 HMAC；V2 模块处于原 datasets/knowledge/annotation/evaluation 目录，不另建数据管理栈。原 PMData 入口及历史只读 SilverClient 保留。

`src/datasets/probes.py` 定义 JSON Schema：metric、window_days、offset_days、operation、comparison、required_fields、unit、min_coverage 和按语义配置哈希的 probe_id。固定 16 指标 × 7/14/28 天 × mean/median/sd/slope/adjacent_change/mean_difference = **288 个独立定义**。mean_difference 与紧邻前 28 天均值比较；其他无比较基准。单项需不少于 70% 有效日，比较的每个区间分别满足要求；不插值、不外推，趋势按真实日历间隔算，adjacent_change 不跨缺测连接。

返回 status、value/unit、起止日期、n/分母/覆盖率、缺失/不可用计数、逐日来源引用、比较区间、result_sha256、elapsed_ns。时间或字段错误阻断；未来行或重复日期被拒绝。原始观测和上游统计不能混淆。**“最近 14 天入睡时间波动与此前 28 天比较”在当前数据缺乏入睡时刻及确定上游 lookback，因此不声称可以精确执行。**可执行描述性替代不等同这个原条件。

知识—探查索引支持多对多、条件 ID、角色/连接词和反向索引，分别报告知识引用总数与去重 Probe 数。多个知识共享一次统计，知识数增加不代表计算数量线性增加。Necessary/ALL 需要来源引用，替代条件用 ANY；没有引用的必要 AND 不编译。

## 实测评估及不利结论

实测完整 V2.1：2,276 窗 × 288 = **655,488 次探查**；372,147 次 COMPUTED，283,341 次 INSUFFICIENT_INFORMATION。全部 288 定义至少在一个窗口可计算。含结果序列化写盘约 **63.07 秒**，计算计时合计约 38.71 秒；单项中位 0.0519 ms、P95 0.1191 ms；单窗整批中位约 **26.24 ms**。Python 3.12.8、Windows 11、Intel Family 6 Model 183，28 logical CPUs；执行是单 Python 流，未使用缓存。这是单机探索性测量，受系统负载和文件缓存影响，不能宣称普遍性能常数。

此前不含冷启动的 V2.0 同样是廉价计算：1,676 窗、482,688 次，含写盘约 83.97 秒。两次耗时不作横向算法比较；负载/缓存不同。程序另存每窗/每人覆盖、缺失、批量耗时与统计分布；汇总只公开聚合值。原早期评估的规模切片采用主题前缀，保留原报告；最终 readout 另用与标签无关的 SHA256 嵌套顺序比较 26/100/300/500 请求规模与实际可达规模，不把不足 500 冒充 500。

这些成本**不支持“全量计算昂贵”作为当前研究前提**。知识出现多个条件/多个探查，也不说明存在联合必要证据或延迟发现收益。只有以后在未改造条件、可信对照下证实真实候选外适用知识及发现路径，才有理由检验新方法；本轮无此收益结论。营养/压力/年龄等大量上下文无法从当前可穿戴数据确认，需保留不足信息。

## 可复现命令与产物

从仓库根目录运行，Python 3.11+，全流程标准库，不需要开发者绝对路径。先构建、核验和执行确定性评估：

```powershell
python -m src.c1_benchmark_v2 fetch
python -m src.c1_benchmark_v2 build
python -m src.c1_benchmark_v2 verify
python -m src.c1_benchmark_v2 evaluate --output local/c1-v2/evaluation-coldstart-v1
python -m unittest discover -s tests -v
python -m src.validate --output local/validation/c1-v2-after.json
```

样例构建输出是 participants=200、source_daily_rows=119795、windows=2276、knowledge_candidates=402、probe_definitions=288。全部命令拒绝覆盖已存在发布/评估目录；重复下载只验证快照，不重抓或替换。`--config`、`--raw-dir`、`--release` 可用于新版本，配置与来源内容变化须新版本。远程 XML 会轮转，动态 v4 API 会更新；固定哈希不再匹配或原地址消失时显式 BLOCKED，必须使用已归档原快照或另建版本，不能静默用新数据冒充原发布。

全新克隆可以独立构建 V2 并运行 `python -m unittest tests.test_c1_v2 -v`。旧 35 项集成测试及 `src.validate` 仍需要 README 所述的私有迁移快照；不存在时明确报告缺失/BLOCKED，不随机补数据。本机完成了全部 66 项测试以及旧项目 2,931 文件、77 个冻结来源哈希复核，均通过；V2 的确定性和伪匿名划分复现还需保留本机私有 identity key。

Qwen 密钥放环境变量 `DASHSCOPE_API_KEY`，不提交密钥；预算文件是本轮授权记录，其他运行不能据此继承付费授权。先只估算，再做有限 smoke：

```powershell
python -m src.annotation.c1_v2_pipeline --budget configs/c1_v2_qwen_budget.json --smoke --plan-only --label-pairs 12 --output local/c1-v2/qwen-smoke-cold-v1
python -m src.annotation.c1_v2_pipeline --budget configs/c1_v2_qwen_budget.json --smoke --label-pairs 12 --output local/c1-v2/qwen-smoke-cold-v1
python -m src.annotation.c1_v2_pipeline --budget configs/c1_v2_qwen_budget.json --label-pairs 0 --output local/c1-v2/qwen-knowledge-v1 --workers 8
```

本次实际执行尾部分片以缩短等待，累计仍使用同一 CNY 200 授权。完整重放时保留两个 ledger，最终配对标注与独立 QA 命令为：

```powershell
python -m src.annotation.c1_v2_pipeline --budget configs/c1_v2_qwen_tail_budget.json --knowledge-start 202 --knowledge-limit 200 --label-pairs 0 --ledger local/c1-v2/qwen-ledger-tail-v1 --output local/c1-v2/qwen-tail-v1 --workers 24
python -m src.annotation.c1_v2_pipeline --budget configs/c1_v2_qwen_budget.json --extra-ledger local/c1-v2/qwen-ledger-tail-v1 --label-pairs 120 --output local/c1-v2/qwen-final-v2 --workers 24
python -m src.annotation.c1_v2_qa --run local/c1-v2/qwen-final-v2 --revalidate-to local/c1-v2/qwen-final-v3 --extra-ledger local/c1-v2/qwen-ledger-tail-v1 --output local/c1-v2/final-qa-v3.json
python -m src.evaluation.c1_v2_readout --evaluation local/c1-v2/evaluation-coldstart-v1 --annotation local/c1-v2/qwen-final-v3 --qa local/c1-v2/final-qa-v3.json --output local/c1-v2/readout-final-v3.json --public-dir docs/c1_v2_artifacts
```

配对样本固定为前 60 个训练参与者，每人最新 14/42 天窗口推荐同一条已审知识，共 120 对；知识按有可执行依赖优先、再 ID 排序。计划在请求前保存，案例、知识、缺失模式或标签结果不作事后选择。源审查原始记录目录不回写；最终发布按能力检查 v2 统一再校验，保留旧接受状态和新待审原因。两个 ledger 的成本合并后才代表本轮总费用。

缓存身份包含端点、模型、参数、提示版本、完整来源和输入。ledger/requests/cache/failures 逐请求保存，不支持自动重试；中断后仅精确缓存可重放，已预留但无完成响应的请求保持待审。费用估算与保守预留不同；最终报告提供实际 usage 定价与未知费用。Qwen 缺密钥、未授权预算或端点错误时 BLOCKED，不替换模型或制造标签。

原始数据/元数据在 `data/raw/c1-benchmark-v2/`；独立 V2.1 发布在 `data/releases/c1-benchmark-v2.1/`；探查 evidence/coverage/batch_times 在 `local/c1-v2/evaluation-coldstart-v1/`；Qwen 来源审查、知识版本、依赖索引、逐条证据与 Silver 标签在 `local/c1-v2/` 的冻结运行目录。每个发布都有文件清单 SHA256 和 release_id；旧版本与失败原样保留。公开 Git 只包含代码、配置、协议与非个人聚合报告。

工程测试检查缺测、异常值、源字段逐值保留、完整性、参与者隔离、14 天冷启动、窗口截止、统计边界、引用/数值/日期/哈希、错误 AND、缓存防篡改、悲观预算与失败恢复。旧 35 项测试继续通过。独立 artifact QA 重算每个已标注统计、复核两阶段引用并连接请求响应链，不把它当独立医学验证。

本轮只提交 Draft PR，不合并 main。完成后等待研究方向评估；研究结论允许目标知识数不足、全量便宜、联合依赖不足和不确定。
