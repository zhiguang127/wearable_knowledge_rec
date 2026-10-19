# Baseline 清单与真实复现边界

2026-10-18：本轮核验 11 个本机官方 checkout 的 HEAD 与固定 SHA 一致，跟踪源码未修改；本轮没有重新联网审计、克隆、下载权重或执行模型。机器 pin 与已有许可文件 SHA 在 `configs/upstream_pins.json`。以下运行状态来自原始历史记录，迁移校验核对了记录字节；不是此次新运行结果。

`NATIVE_REPRODUCED` 仅表示官方最小原任务算法真实运行过，**不表示论文全数据集/历史环境/指标已复现**。`TASK_ADAPTED` 表示后端或健康任务改变。`PAPER_INSPIRED` 只表示提示组织借鉴。`BLOCKED` 保留具体阻碍，不以普通 prompt 代替训练/模型或算法。

## 官方实现与 SHA

| 方法与官方仓库 | 固定完整 SHA | 原任务实际状态 | 健康任务状态 |
|---|---|---|---|
| [MedCPT](https://github.com/ncbi/MedCPT) | `11e129be74102c98d16a11c310b0b5ce74c1db5e` | `NATIVE_REPRODUCED`：官方 README 最小推理/官方权重成功；历史环境/全指标未复现 | `TASK_ADAPTED`：官方 DenseRetriever/CrossEncoder + P1 查询表示/知识库；语义是检索相关性，不是优先级 |
| [TrialGPT](https://github.com/ncbi-nlp/TrialGPT) | `1b3242cd50c153a9c324661d4a0bd94fc68a4226` | `TASK_ADAPTED`：后续官方匹配函数真实运行，Qwen3.8-Max 替代论文后端 | `TASK_ADAPTED`：TrialGPT-style applicability，不是完整临床试验检索/匹配/排序结果 |
| [Google PHA / PHIA / Parallel / Orchestrator / DataScienceAgent](https://github.com/Google-Health/consumer-health-research) | `3e9d1e4877a54cf81ce8ef34085006952dd19601` | `TASK_ADAPTED`：原架构、计算工具和调度有真实推理；Qwen3.8-Max 后端和兼容环境 | `TASK_ADAPTED`：真实 P1 / 固定来源 / 三分类输出；任务与路由不天然等价 |
| [Self-Refine](https://github.com/madaan/self-refine) | `9a206d41e5d2d0c241bb441f41eeadb945afaa55` | `TASK_ADAPTED`：官方缩写任务三个类 Init/Feedback/Iterate，3 次 Qwen-Max 调用；原论文模型未复现 | `TASK_ADAPTED`：共同 B1 初始结果 + 一次反馈/修正 |
| [CRITIC](https://github.com/ZethWang/CRITIC) | `5e865ed78cd1b325cf53b15c7209227760131abf` | `BLOCKED`：原入口依赖/旧响应契约等环境阻碍；不能把 CLI 检查当算法成功 | `TASK_ADAPTED`：官方 critique/revision 控制循环 + 完整纵向确定性工具 |
| [RARR](https://github.com/anthonywchen/RARR) | `51a1a10fe5bada837a368f98cb55288ac5168c9e` | `BLOCKED`：原入口依赖/原搜索后端未原样复现 | `TASK_ADAPTED`：原 generation/gate/editor 定义 + 固定来源/后端适配；仅解释修复、排序锁定 |
| [RE2](https://github.com/zhiyuanc2001/RE2) | `c317f196e34f1a3fbb06d61b48ca924feefbc374` | `BLOCKED`：SFT/GRPO/checkpoint 和原训练任务没有复现 | `PAPER_INSPIRED`：只能称 RE2-style Reason-then-Recommend Prompting |
| [ReRec](https://github.com/jiani-huang/ReRec) | `65b78c5129617a3dcceb2739342e8b5915011dcf` | `BLOCKED`：vLLM/Linux/CUDA、训练后 checkpoint 缺失 | `BLOCKED`：缺可信健康优先关系、属性图/reward 与训练 |
| [RankingSHAP](https://github.com/MariaHeuss/RankingShap) | `36e45975f34ee167261af56c69521d55c998b282` | `NATIVE_REPRODUCED`：作者 talent-search notebook 评分器与官方解释器最小运行，seed=0 | `BLOCKED`：没有预先冻结、可重复查询的可信健康优先级 scorer；不能从 Silver 临时拟合假 Gold |
| [TRACE](https://github.com/devUuung/TRACE) | `ab14d963e231f789316a929ae7497f3d1acc674f` | `NATIVE_REPRODUCED`：MovieLens-100K、官方 SASRec checkpoint，3 用户/1 seed/CPU 最小运行 | `BLOCKED`：没有知识交互序列模型和有效健康编辑语义；生理每日行不能随意包装成用户点击 item |
| [PEX-DPO](https://github.com/lingjunzhao/PEX_consistency) | `33f6b73590cf2f4a67235329db4b712420bc9156` | `BLOCKED`：原依赖/训练后模型/完整 SFT→PEX→DPO 未复现 | `BLOCKED`：缺部分序概率语义、可信解释偏好和独立决策 Gold |

RecPIE 仅作为相关工作/未来训练基线候选：旧审计未定位可信官方实现，因此官方 SHA 与复现状态为 `BLOCKED_OFFICIAL_CODE_NOT_LOCATED`；本轮没有重新搜索。BM25、BGE-M3、Direct 和 A 中简单组合也有历史记录，但不是以上可解释方法的完整论文 SOTA 覆盖。内部 Grounding / Claim / Candidate-relative 等消融不能充当独立论文基线。

## 历史运行分母和失败

B0 是 16 人各一个最早窗口、5 个固定候选的探索性比较。200 条包括 160 条 main（10 个 arm × 16 窗口）和 40 条 candidate_reverse。全部原记录共 163 条结构接受、24 条失败、13 条无效输出。`EXECUTED` 仅表示输出结构被接受；不能转换为 81.5% 推荐准确率。

| 健康 arm | 计划窗口 | 结构接受 | 失败 | 无效 |
|---|---:|---:|---:|---:|
| Self-Refine adapted | 16 | 15 | 1 | 0 |
| CRITIC adapted | 16 | 11 | 3 | 2 |
| RARR explanation-only | 16 | 15 | 1 | 0 |
| RE2-style prompt | 16 | 12 | 2 | 2 |

C0-A 选取原 6 arm 的 96 个槽位，其中 75 条结构接受、12 条失败、9 条无效，生成 16 张阶段一案例卡与 140 张阶段二解释卡。21 个失败/无效槽位全部保留，原空白模板未被当成人类提交。本轮逐对象重放案例、解释、crosswalk、失败清单，内容与迁移原件完全一致；优先级准确性和解释忠实性仍为 null。

TRACE 在相同三用户上，100 query/2 edits 预算为 0/3 有解；作者式 10,000 query/5 edits 预算为 3/3 有解。两个运行和中间错误均保留。低预算零结果不证明算法无效，后者也不是健康推荐收益或完整论文效果。

A 的早期 `reproduction_status.json` 仍写缺凭据，不能作为最终状态。有效索引是归档的 `configs/active_baselines.json`，包括 TrialGPT、PHIA v2、Parallel v3、Orchestrator v4、DS v1。`CONTINUATION_READOUT.md` 和 `results/reproduction_corrections.json` 保留真实 Qwen3.8-Max 推理及以下纠正：早期 PHIA Responses 路由漏计、Parallel 组件失败后仍合成、Orchestrator 预算错误被旧成功判据漏掉。原错误报告未删除，也未把漏计解释为零调用/零费用。

## 新项目实际移植范围

活跃代码只包含 B0 结构化 schema、历史 prompt 规范、输出契约、确定性完整来源/纵向载荷与证据引用适配、C0-A 纯审查函数及历史重放。16 个原 B0 payload 的 SHA、B0 冻结代码和全部候选集可验证。旧运行器/官方函数抽取器/LLM transports/模型依赖保存在私有历史档案，不从新项目导入；没有宣称已完成所有 Baseline 的新项目 live port。

下一轮若要执行某个 Baseline，应先按本表逐个建立独立依赖与适配测试、记录固定官方源码/模型/环境/输入输出和偏离，再冻结公平比较协议。新 `src/baselines/adapter.run()` 明确抛出 `BLOCKED_NEW_BASELINE_EXECUTION`。`src/annotation/SilverClient` 只读精确缓存，旧 budget 不授权新调用。

官方源码未 vendor 到新 Git：Self-Refine/TRACE 与 A 三仓库的现存许可文件哈希已记录；CRITIC、RARR、RE2、ReRec、RankingSHAP、PEX-DPO 在旧固定树的审计没有顶层许可文件，重新分发许可保持 `BLOCKED_LICENSE_NOT_ESTABLISHED`。不得因能公开下载就推定允许重新授权。

所有状态是原任务/健康任务分别记录的工程证据。没有 independent human priority Gold、稳定的 S4 优势、解释机制必要性、临床正确性或新方法贡献结论。本轮没有新模型运行或训练。
