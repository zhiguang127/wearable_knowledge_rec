# Wearable Knowledge Recommendation

最新执行见 [Day 4 证据判别与机制报告](docs/C1_DAY4_DISCRIMINATIVE_REPORT_V01.md)：审计 3 人、12 个真实窗口、3,456 项结果，构建 8 对来源可追溯候选，完成 48 次隔离真实 Qwen 请求及 288 次合法获取步骤。数值有差异，但参考存在位置敏感和未测情境问题，0 对通过证据判别门槛；本轮 ΔU 保持 null，状态为 **INSUFFICIENT_EVIDENCE**。235/235 测试通过，未启动正式 Benchmark/Baseline/C2。[Day 3 原报告](docs/C1_DAY3_EVALUATION_REPORT_V01.md)、[Day 2 原报告](docs/C1_DAY2_FEASIBILITY_REPORT_V01.md)及所有原始响应、标签和失败均保留。

Day 1 诊断见 [原始知识构造与排序修订 v0.4](docs/C1_DAY1_CONSTRUCTION_AND_RANKING_V04.md)：已精确重放 402 条候选到 204 条活跃知识的来源链，并新增 204 次真实来源成分审查。原库是健康教育抽取库，含真实人群、行为和数值建议，**此前 0 条通过严格可测适用门槛不等于原文没有条件**。决定保留原语料，另建 C1 排序实验集，分别记录硬性适用、个体相关性和证据排序增益；设计与 Schema 已保存，正式实验继续待冻结。下方为历史阶段记录，不覆盖当前授权和诊断结果。

上一轮执行见 [Day 1 真实 Qwen v0.3](docs/C1_DAY1_REAL_QWEN_V03.md)：已按用户授权取消调用次数和金额上限，实际完成 214 次请求；真实 Evidence ID 链路通过，全 204 条知识经模型复核后仍无合格可测规则，实验合同保持待冻结。其配置为 [c1_day1_active_v03.json](configs/c1_day1_active_v03.json)。

本轮 [全 204 条知识审查与真实 Qwen 引用链路 v0.2](docs/C1_DAY1_CATALOG_AND_QWEN_V02.md)：全库已逐条审查，但合格可测规则仍为 0；真实 ID 烟测请求已准备，等待独立调用授权。正式标注和实验冻结仍受来源与标签门槛阻塞。

当前新一轮依据 [Day 1 统一实验合同 v0.1](docs/C1_DAY1_CONTRACT_V01.md)：四分类适用性、Evidence ID 确定性绑定、获取环境和冻结 Ranker 协议。**合同待冻结，正式 Baseline 仍禁止开始**；新增实现与验收状态见 [Day 1 验收记录](docs/C1_DAY1_ACCEPTANCE_V01.md)。历史 V2/V2.2 工件及其失败记录保留。

当前修复分支 **C1 V2 Audit & Repair / V2.2**：V2.1 的去重、证据输入和 AND 验证存在研究有效性缺陷，不能据此推断真实个人证据不足或联合依赖不存在。修复、原始轨迹归因及有限复核见 [V2.2 审计报告](docs/C1_V2_2_AUDIT_AND_REPAIR.md)。PR #1 和历史冻结工件保留。

新增独立任务 **C1 Benchmark V2**：真实 WearableQA 日级数据、带来源的健康教育知识、确定性 Probe 与两阶段 Qwen 自动 Silver 审查。历史 V2/V2.2 调用使用 `qwen-plus`；2026-10-20 起新标注入口默认使用 **`qwen3.8-max`**，独立模型配置为 [c1_day1_qwen3_8_max.json](configs/c1_day1_qwen3_8_max.json)。本次只切换模型与来源标记，未进行付费调用。包含 **14 天冷启动**及 42/90/180 天历史；原 PMData、历史标签与实验不回写。入口、复现命令、实测数量与限制见 [C1 Benchmark V2](docs/C1_BENCHMARK_V2.md) 和 [V2 自动审查协议](docs/C1_V2_SILVER_PROTOCOL.md)。下文迁移与旧实验的停止条件仅描述其原轮次，不覆盖这个新授权任务。

基于纵向可穿戴数据的可解释健康知识推荐。当前为 **离线迁移与工程校验完成**，不是医学验证、人工 Gold 数据集或新方法效果结论。旧项目 `D:\Python\py_projects\c1_pilot` 保持原样；本项目有独立 Git 仓库，后续工作通过独立分支与 Draft PR 交付。

## 已有资产

| 资产 | 实际数量与边界 |
|---|---|
| PMData / P1 | 16 人，48 个冻结真实窗口；每窗 28 日基线 + 14 日当前期，共 2,016 日；93 个下载文件、3 个源端缺失 |
| P1 候选 | 每窗相同 5 条知识，适用性和优先级没有人工确认 |
| A1 | 26 条知识、6 组候选、每窗 27 次组成员关系但仅 26 个唯一候选；1,248 个唯一案例—知识对 |
| 历史 Silver | `qwen-max` 的 `QWEN_MAX_SILVER`，160 条 A/B 记录，80 个唯一案例—知识对；119 条通过旧引用结构校验，41 条未通过，全部保留 |
| 历史 B0 / C0-A | 200 条 B0 输出及旧失败版本；C0-A 的 16 张案例卡、140 张解释卡、21 个失败/无效槽位可离线精确重放；尚无人工评审 |
| 划分 | train/dev/test = 10/3/3 人、30/9/9 窗口；同一人的全部窗口归属同一集合 |

所有人曾进入历史 B0，因此新划分只是防止后续同人跨集合泄漏的回顾性划分，**不是从未被接触的测试队列**。既有 Silver 不能改称 Qwen3.8-Max 结果；后续目标模型记录为 `qwen3.8-max`，本轮没有验证端点或生成新标签。

## 结构

```text
configs/                  研究边界、历史采样计划、官方仓库 SHA
data/raw/                 PMData 和知识来源原文（本机私有、Git 忽略）
data/processed/           来源闭包和参与者划分（Git 忽略）
data/releases/            原样冻结 P1 / A1 / Silver（Git 忽略）
src/datasets/             导入纯函数、发布校验、逐字段来源核验、划分
src/knowledge/            知识来源/锚点/条件哈希审计
src/annotation/           结构化输出、只读 Silver 缓存、历史预算审计
src/baselines/            原输出契约、来源工具载荷、历史重放；新执行禁用
src/evaluation/           精确证据引用、C0-A 盲审卡纯函数
src/methods/              未来方法预留；没有 M1/M2
experiments/              实验记录规范
tests/                    单元测试和真实迁移数据集成测试
docs/                     迁移审计、研究协议、Baseline 清单、验证报告
tools/migrate.py          单向、禁止覆盖的迁移/本机恢复工具
local/                    身份密钥/映射、完整历史轨迹、迁移账本、验证日志；Git 忽略
```

## 可执行命令

Python 3.11+；当前验证使用 Python 3.12。原有运行流程依赖标准库；v0.4 Schema 测试与 Day 2 离线 Schema QA 需要 `pip install -e ".[test]"`。离线验证不需要 SDK、GPU 包或 API Key。从本项目根目录执行：

```powershell
python -m unittest discover -s tests -v
python -m src.validate
python -m src.validate --source-root D:\Python\py_projects\c1_pilot
python -m src.validate --source-root D:\Python\py_projects\c1_pilot --output local/validation/recheck-001.json
python tools/check.py --name recheck-001 --source-root D:\Python\py_projects\c1_pilot
```

校验错误返回非零退出码并逐阶段标记 `BLOCKED`；没有本机私有数据时不会随机造案例或跳过检查。`--output` 必须使用新文件名，已有报告不覆盖。`--source-root` 额外核验旧项目 2,931 个研究文件和 77 个旧冻结哈希；不传该参数时只验证迁移后的独立资产。

仅在**全新克隆、尚无私有资产**时，从同一完整旧项目恢复：

```powershell
python tools/migrate.py --source-root D:\Python\py_projects\c1_pilot
python -m src.validate --source-root D:\Python\py_projects\c1_pilot
```

当前工作目录已完成迁移，无需再次运行。恢复需要原 raw 文件和身份映射；仅从 OSF 重新下载不能恢复原 HMAC 身份。迁移工具不覆盖已存在的数据、发布或账本。

独立恢复演练已通过同一套 35 项测试与完整校验。Windows 下应使用较短的目标路径：原历史缓存文件名很长，当前最长路径 244 字符，过深目录曾实际触发 `MAX_PATH`；该失败记录和短路径重跑结果均保留。

## 验证与阅读顺序

已执行的数量、SHA 和来源链检查见 [验证报告](docs/VALIDATION_REPORT.md)。资产逐文件决策在 [迁移审计](docs/MIGRATION_AUDIT.md) 和 [机器清单](docs/MIGRATION_ASSETS.json)；研究阶段和停止门槛在 [研究协议](docs/STUDY_PROTOCOL.md)；官方固定 SHA、适配和阻碍在 [Baseline 清单](docs/BASELINE_INVENTORY.md)。

Git 只保存代码、配置和非个人审计信息。原始/伪匿名健康记录、逐条 Silver、划分身份清单、模型请求/响应、盲审映射及身份密钥不进入 Git；API Key 没有迁移。PMData 保留原 CC BY-NC 4.0 许可和原始下载清单；知识网页、模型权重及第三方源码不被重新授权或打包公开。

本轮到此停止：没有新付费调用、大规模 Baseline、SFT/DPO/RL、新算法或人工标注。后续应先解决来源争议和独立评审，再讨论方法。
