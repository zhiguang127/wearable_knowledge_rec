# Day 1 真实 Qwen 执行 v0.3

2026-10-20。用户明确授权“直接放开用，不设限制”，覆盖此前两次/一元的提案。当前调用配置使用 `budget_mode=UNLIMITED`，次数和金额上限均为 null；账本继续记录真实用量，不设置调用额度停止点。

当前入口配置为 [c1_day1_active_v03.json](../configs/c1_day1_active_v03.json)，实时调用授权为 [c1_day1_unrestricted_v03.json](../configs/c1_day1_unrestricted_v03.json)，来源复核配置为 [c1_day1_source_review_unrestricted_v03.json](../configs/c1_day1_source_review_unrestricted_v03.json)。旧 pending 配置、准备快照和失败记录保留为历史，不能据其再次要求本任务的调用授权。

## 已执行结果

**真实 Evidence ID 链路通过；全 204 条来源复核完成；合格可测规则仍为 0，合同保持待冻结。**

| 项目 | 实测 |
|---|---:|
| 新增真实请求 / 响应 | 214 / 214 |
| ID 链路真实请求 | 2 |
| 知识首轮来源审查 | 204 |
| 预先固定的近似候选第二次来源审查 | 8 |
| 模型未提出可纳入规则 | 203 条 |
| 保留待审 | 1 条 |
| 合格可测知识条件 | 0 |
| 真实引用检查 / 绑定 Evidence | 2 / 4 |
| 绑定中的有效测量 / 不足信息 | 3 / 1 |
| 新个人适用性标签 / 有正负差异的列表 | 0 / 0 |
| 输入 / 输出 tokens | 2,540,754 / 79,411 |
| 用量估价 | CNY 33.347844，非账单 |

214 次请求实际请求与返回模型均为 `qwen3.8-max`；没有把历史 qwen-plus 返回改名。按本次核对的 [官方北京标准档价格](https://help.aliyun.com/zh/model-studio/qwen3-8-max) 计算输入 12、输出 36 元/百万 tokens，未假设缓存折扣。账单金额不可见，保留 null。

## 真实协议修复及原始失败保留

第一次真实响应具有完整且合法的具名 `tool_calls` 参数，结束标记却为 `stop`。旧解码器仅接受 `tool_calls` 标记，造成程序误拒。原始首次失败工件 `local/day1/id-smoke-live-v03/` 和 ledger 原样保留。

新版本允许 `stop` 或 `tool_calls`，同时仍要求恰好一个预期函数、空自由文本、无拒绝、完整 JSON、合法 Schema/ID；`length`、未完成输出、缺少函数、错误函数及实质性引用错误仍拒绝。这是对已观测响应格式的兼容处理；[官方接口说明](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions) 通常将工具结束标记描述为 `tool_calls`，本轮记录了实际端点的不同表现，未改写原响应。

新版本对第一次原响应进行离线复核，确认两个 ID 的绑定正确；只为剩余第二项检查新增一次调用，没有重新付费生成第一次响应。新版结果在 `local/day1/id-smoke-live-v03-r1/`。四项 Evidence 的 Probe、窗口、状态、值/单位、来源及计算哈希均与确定性 Provider 重算一致；不足信息保留为不足信息。

## 全量真实来源复核

每条知识的第一次调用仅提供其冻结正文、完整来源锚点、全部 288 个 Probe 定义及已知测量边界。未提供上一轮 Codex 的排除结论、旧 Qwen 条件、个人数值或参考适用性标签。知识范围固定为原 204 条，未按输出替换候选。

预先固定八条最接近的来源条目进行第二次审查，覆盖分龄睡眠、夜间事件和活动量等；第二次会看到第一次模型输出，属于同模型审查，**不是独立人工 Gold**。所有结果只作为模型来源审查/Silver 证据，不证明医学有效性。

唯一提出数值候选的是 `K2-6c57d5516de8f75bce19`。原文成人睡眠时长建议被模型尝试映射到七日均值，但：

- 原响应给出的 Probe ID 与所述 sleep_duration 七日均值不一致。
- 模型自己列出了未测量的年龄、成人身份和个体睡眠需要等背景。
- 第二次审查明确承认七日均值不能验证“每晚”达标，并将 `measurement_equivalent`、`role_supported`、`source_roles_complete` 置为 false。
- 第二次根 verdict 虽写为支持，逐项检查却不支持；验证器以完整检查为准，保留矛盾与失败，不将其升级为 VERIFIED。

其余 203 条输出为未发现完整可测适用规则。这个结果限于当前来源、允许数据、288 项 Probe 和此次模型审查；不能外推为 C1 算法无效或个性化不可行。一般教育、资源入口、不可测健康背景仍不自动成为任何个人的 not_applicable 或 not_assessable 标签。

## QA、冻结状态与工件

离线 QA 已重新核对全部 214 条真实原始请求/响应哈希链、204 个知识输入及 288 Probe 的完整范围、首轮未泄漏旧判断、第二轮未编辑第一次结果，以及四项真实 Evidence 的确定性绑定。报告只标记 **PASS_RAW_CHAINS_AND_MECHANICAL_BINDING_ONLY**；临床有效性和决策准确率继续为 null。

全套测试 **153/153 通过**。新增回归验证不限额授权、兼容 `stop` 的完整函数输出、缺失/截断拒绝、旧轨迹只读复核及来源条件的逐项检查。

- [公开聚合及 QA](c1_day1_v03_artifacts/live_qa.json)
- [逐条模型来源复核摘要](c1_day1_v03_artifacts/source_review_summary.jsonl)
- [来源复核聚合](c1_day1_v03_artifacts/source_report.json)
- [当前冻结门槛](c1_day1_v03_artifacts/freeze_gate.json)

完整原始响应、个人聚合证据和身份相关内容仅保存在忽略的 local/ 下：`qwen-source-review-v03/`、`qwen-source-ledger-v03/`、`id-smoke-live-v03-r1/`、`id-smoke-ledger-v03*`，以及 `real-qwen-qa-v03.json`。原数据、历史发布与原失败工件均未回写。

调用授权问题已经解决。当前未满足的是来源条件与测量语义门槛：没有至少 6 条合格规则，因而无法形成所需的 20 个可信正负差异列表。**没有冻结正式实验，没有运行 Baseline 或 C2 训练**。若要继续突破这个数据前提，需要另行确定可测来源判据、允许的补充观测或新的任务版本；当前不能靠增加调用次数制造标签差异。

复验，不产生新请求，输出文件须不存在：

```powershell
python -m src.day1.live_qa --output local/day1/real-qwen-qa-new.json
python -m unittest discover -s tests -v
```

新的实时工作均显式使用上述不限额配置；历史 CLI 的旧预算默认值仅对应旧版本。示例来源复核命令需要全新目录，会实际调用模型：

```powershell
python -m src.day1.source_review --budget configs/c1_day1_source_review_unrestricted_v03.json --output local/day1/source-review-new --ledger local/day1/source-ledger-new
```
