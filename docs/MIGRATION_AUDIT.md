# 旧项目资产审计与迁移

审计日：2026-10-18。源：`D:\Python\py_projects\c1_pilot`；目标：`D:\Python\py_projects\wearable_knowledge_rec`。旧仓库 HEAD 为 `da23fff62e7e72dfbf3902421da889053dfc3e44`，迁移前后分支、HEAD、工作区状态和审计范围字节均一致。原本未跟踪的 `experiment_c0_audit/` 与 zip 没有修改，也没有用来覆盖已集成的 C0-A。

## 覆盖与决策

完整枚举用户指定的 P1、A、B0、C0、根 `data/`、`src/`、`docs/`。剔除依赖环境、模型权重、embedding、上游仓库和 Python 缓存后，共哈希 2,931 个文件。第三方上游另外逐仓库核验固定提交与跟踪源码未变。排除目录逐项列在机器清单，不把这些巨大依赖树算入“旧项目未变”的哈希证明。

初次完成 2,504 次原字节复制、4 个纯函数模块提取，随后沿 provenance 追踪补充 5 份语料编辑审计资产，共 2,509 次复制。补充包括最初七个目录之外的 `reports/CORPUS_AUDIT.md`，额外核验其 SHA，原 2,931 文件快照不回写。数量包含为了来源闭包保存的私有记录，以及同一 Silver 发布的归档和可用发布副本；不等于活跃源码文件。没有把旧运行器整体接入新项目。

逐文件清单：`docs/MIGRATION_ASSETS.json` 是首轮非 local 文件决策；`local/migration/asset_audit.json` 覆盖首轮全部 2,931 个文件，`manifest.json` 记录初次复制和纯函数提取；`source_before.json` 保存原范围快照。`docs/MIGRATION_SUPPLEMENT.json` 与私有 `supplement-corpus-v1.json` 补充 5 份文件的来源/目标/字节数/SHA，并将最初四份 data 编辑审查记录的“不复制”决定更新为“私有证据归档”。下表是保留的首轮计数，最终应加补充清单，不抹去审计过程。私有身份和健康记录不会公开。

| 分类 | 文件数 | 含义 |
|---|---:|---|
| `DIRECT_MIGRATE` | 164 | 原样迁移必要数据、来源及格式定义 |
| `REFACTOR_MIGRATE` | 4 | 提取 P1 导入、纵向视图、B0 契约、C0 盲审纯函数；去除项目耦合 |
| `RECORD_ONLY` | 2,327 | 私有归档，不成为运行依赖；包括每版成功、失败、无效、缓存和预算 |
| `RECORD_ONLY_NOT_COPIED` | 413 | 源项目保留，文件哈希和理由可追溯；非本轮必需的评审/展示/辅助输出 |
| `DISCARD_FROM_NEW_PROJECT` | 23 | 根合成案例/旧标签/耦合生成和运行代码不进入新项目；旧文件未删除 |

## 按资产说明

| 原资产 | 决策与目标 | 原因和限制 |
|---|---|---|
| `p1/data/releases/p1-v2/*` | 原样迁移到 `data/releases/p1-v2/` | 48 个真实窗口、5 条固定候选、冻结协议/质量审计，不重采样 |
| `p1/local/pmdata/*` | 原样迁移到 `data/raw/pmdata/`，Git 忽略 | 保存 93 个源文件、3 个源端缺失、下载时间/URL/许可/SHA，不填补缺失 |
| `p1/local/pseudonym.key` 与 `mapping-p1-v2.json` | 只迁移到 `local/identity/` | 重现原 HMAC 和源日期；不重新生成身份；不进入 Git |
| P1 `dataset.py` | 纯解析/HMAC/构窗函数提取为 `src/datasets/pmdata.py` | 没有下载、自动造新发布或写旧路径入口；原冻结代码在私有归档核验 |
| P1 下载器/旧表单/评审包 | 实现仅私有归档或源端保留 | 本轮不下载、不开展人工评审；不复制浏览器表单和大量包作为活跃代码 |
| `experiment_a/data/releases/a1-v1/*` | 原样迁移到 `data/releases/a1-v1/` | 26 条知识/6 组/48 例全部保留；组重叠不重复计标签 |
| 根 `knowledge_items.jsonl`、`corpus_seed.json`、`source_manifest.json`、`input_freeze.json` | 原样迁移到忽略的 `data/processed/legacy_knowledge/` | 96 条完整语料只作 A1 来源哈希闭包；不把其余 70 条默认为活跃推荐面板或 Gold |
| 根 `data/source_snapshots/*` | 原样迁移到 `data/raw/knowledge_sources/` | 50 份文本/HTML；保留源获取失败和历史哈希差异，未重新联网获取 |
| A 的纵向 `representation` / statistics / evidence reference | 提取 `src/datasets/views.py` 与独立证据适配 | 保留 null、零 RHR 排除、圆周时钟/未知时区、全窗输入等语义 |
| A `silver/` | schemas 原样迁移；Client 重构为只读缓存；旧实现私有归档 | 保留结构化声明函数、精确请求哈希、失败输出和预算；移除 live SDK/凭据/花费入口，不继承旧授权 |
| A Silver `v1/release-v1`、底层标签/预算/源快照 | 原样迁移至私有发布及私有档案 | 160 条均为 `qwen-max` / `QWEN_MAX_SILVER`；119/41 原状态不改，不可改名为 Qwen3.8-Max 或 human Gold |
| A/B0 的原官方推理驱动/适配器/旧测试与锁文件 | 记录/原实现保留在私有归档；活跃部分仅移植输出契约、来源工具载荷、重放 | 不携带大型环境与权重；健康跨任务适配不冒充完整官方复现，下一轮再逐个接入推理 |
| B0 全部 `runs/`、`runs_v1/v2/v3`、cache、request、budget、protocol_history、原生 smoke/replay 和日志 | 私有归档，所有现存版本原样保留 | 成功和失败同时保留；不筛选对新方法有利案例，不重跑模型 |
| B0 公共结果、上游 SHA、全部版本配置/冻结 | 归档并生成 `configs/upstream_pins.json` 和 Baseline 清单 | 区分官方最小运行、健康适配、prompt-inspired、环境阻碍 |
| C0-A `pilot.py` | 提取 top-pair、盲审卡、身份扫描，作为 `src/evaluation/review.py` | 保留 ties、失败槽位和先案例后解释的审查语义；不导入旧 B0 runner |
| C0-A 现有卡片/模板/steward 映射与原执行汇总 | 只在 `local/archive/experiment_c0/` 原样保留 | 可精确重放 16/140 卡和 21 个失败槽位；人类评审仍为 0，不是解释忠实性结论 |
| 根 `data/wearable_cases.jsonl` 与 provisional 标签 | 不迁移 | 早期合成案例和 provisional 标签不能替代真实窗口 |
| 根 `src/` 生成器、旧整体 pipeline | 不迁移为新运行代码 | 假设与历史耦合，不应污染独立任务定义；逐文件排除理由已记录 |
| 根 `docs/` | 审计后不整包复制，按本任务重写研究协议 | 避免继承合成 C1 设计与未经支持的算法假设 |
| 依赖环境、checkpoint、embedding、`.git`、API 凭据 | 不迁移 | 大小/许可/平台耦合或秘密；官方代码只记录 pin 与证据，不在新仓库 vendor |

## 来源链中的真实差异

1. P1 目录名为 `p1-v2`，冻结 manifest 内 `revision` 仍为 `p1-v1`。原值原样保留，用完整 release ID 定位，不“修复”冻结版本字段。
2. 原下载计划 SHA 为 `adbfb854c183d153300ebbcba45b1d8d72909022b6adb4294886962ef571ff66`；冻结序列化计划 SHA 为 `71091791f1d0f071fb8e0fdb94e56c3ecaf2a7564262d3b7c43f8af0c69ce605`。验证两份 JSON 内容完全相同，均保存原字节。
3. 24 份知识文本的当前 SHA 与更早 source manifest 的 text SHA 不同。逐一验证 CRLF 转为 LF 后与历史 text SHA 完全相同，当前字节也与冻结清单完全相同。因此记录为 `VERIFIED_CRLF_LF_REPRESENTATION_DIFFERENCE`，不改写历史 manifest、当前源文本或任何标签。若未来出现无法由此解释的差异，验证器标记 `BLOCKED` 并返回非零。
4. 根来源清单中的 `nhlbi_diagnosis`、`aha_hr` 原获取失败，保留 `BLOCKED_SOURCE_UNAVAILABLE_NOT_IN_ACTIVE_PANELS`；它们不在当前 P1/A1 面板。当前 26 条 A1 的原文和字面锚点均可核验，字面匹配不构成医学正确性或条件必要性的证明。
5. 历史 qwen-max Silver 有 160 条 A/B 结果，但只有 80 个唯一案例—知识对、16 个窗口，不能当成 160 个独立案例或全 1,248 对 A1 标签。
6. 原语料 provenance 的 `CORPUS_AUDIT.md` 不在根目录，实际位于 `reports/`。沿旧 `src/assess_hypothesis.py` 的路径找到后，已补充原字节归档，并保留 `corpus_verification`、`independent_corpus_review`、`corpus_review_input`、`corpus_near_duplicate_candidates`。报告明确 reviewed 只是机器编辑审查，不能推断人工确认。

## 保持与未验证边界

48 个真实窗口、所有原标签/源审计/失败没有修改。迁移和验证没有 import 或执行旧项目模块，也没有写旧目录。来源核验从实际 raw、身份映射、日期重建 10,080 个数值和 14,112 个睡眠字段；独立 importer 还在测试中重建全部 48 例并逐对象比较。

`BLOCKED` 研究问题仍包括：来源条件的独立人工确认、优先级 Gold、从未接触的新参与者测试队列、未来 Qwen3.8-Max 标注、健康任务的 RankingSHAP/TRACE 评分与编辑语义、训练型方法所需监督/权重。没有将准备、schema 合格、论文链接或官方 import 当成这些问题已经解决。
