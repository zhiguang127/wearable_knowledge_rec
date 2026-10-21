# Day 4 参考 Schema 修订 v0.1-r1

本修订在部分原始 AI 响应返回后、参考判别与效用评价前记录，**不是执行前预登记**。原 v01 协议、代码、Schema、所有原请求/响应和失败记录保持不变。

发现原 Schema 的 `goal_left` / `goal_right` 只允许 DIRECT/BACKGROUND/OFF_TOPIC，却遗漏个人比较不可判断时的 UNKNOWN/null。这会将诚实未知的响应整包拒收。修订只让这两个维度保留 UNKNOWN/null，且必须同时满足 preference=UNKNOWN、两项 grade=null；原 basis、偏好/等级一致性、来源、证据与窗口验证继续执行。

不改变任何原响应内容、偏好、grade、候选、Goal、抽样、Ranker、参数、语义排除或信号门槛。不重新请求模型。原失败不冒充原版通过：r1 输出独立标签层并记录原状态及 Schema 修订的来源。若仍有其他结构错误，继续保留失败。

只使用修订后的独立目录 `local/day4/reference-revalidated-v01r1/`；相同冻结评价实现通过明确的输入/输出路径绑定运行至 `local/day4/analysis-v01r1/`。源实现和执行前哈希不修改。同行应能同时查看 v01 失败层与 r1 重验层，而非只看到修复结果。

机器配置：[c1_day4_reference_revalidation_v01r1.json](../configs/c1_day4_reference_revalidation_v01r1.json)。此变更修复未知的表示，不是证据判别规则或结果优化。
