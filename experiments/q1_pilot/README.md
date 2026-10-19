# Q1 Pilot 实际执行入口

本目录运行来源一致的排序解释诊断，不训练推荐器、不调用模型 API、不使用 Silver/Gold。实验政策、候选配对和 donor 规则冻结在 config.json 与 protocol.md；结果引用 canonical 配置 SHA 和运行前实现 SHA。最终结论见 ../../docs/Q1_PILOT_READOUT.md。

完整命令从项目根目录运行。独立依赖环境和官方源码都在 Git 忽略的 local 下，不使用旧项目环境或向旧项目写入。

```powershell
python experiments/q1_pilot/setup.py
local/q1-venv/Scripts/python.exe -m unittest discover -s tests -v
local/q1-venv/Scripts/python.exe experiments/q1_pilot/run.py --name smoke-new --smoke
local/q1-venv/Scripts/python.exe experiments/q1_pilot/run.py --name full-new
local/q1-venv/Scripts/python.exe -m src.validate --source-root D:/Python/py_projects/c1_pilot
```

运行名必须全新，拒绝覆盖。一次完整执行依次完成原生验证、全体合格窗口的行为门槛、精确枚举、官方方法、图切边与敏感性条件。网络 socket 在实验执行期间被禁止，安装/获取源码另在 setup 阶段完成。原始失败、逐例归因、评分和配置/源码快照仅存 local/experiments/q1_pilot/<name>/。

官方固定版本为 RankingShap 36e45975f34ee167261af56c69521d55c998b282、ShaRP 6543226b7c4952aab61a15a977964344cabbf929、Shapley-Flow 0d9063f81759d4317de6c33d7782e5ec4a4cde85。运行器检查 HEAD 和跟踪源码；不 vendor 第三方源码到 Git。依赖的实际版本在 requirements.lock.txt 与每次私有 manifest 中。这里记录当前 Python 3.12 环境；不声称恢复论文历史环境或完整指标。

RankingSHAP 保留官方共同遮蔽与 KernelSHAP；使用来源选择器映射完整个人管线，margin callback 是 TASK_ADAPTED。官方零占位背景的初始化问题由 adapter 以真实查询重建官方 KernelExplainer 解决；测试保留修复前偏移的重现。ShaRP 使用官方完整 coalition 求和与 diff QoI，margin、成对结果、负名次和 top2 分开评价。原生 ShaRP 的 item-row rank 例子另跑；健康 wrapper 不冒称原生 item-row 偏好。

Flow 运行官方 CreditFlow distributed edge game；来源组到统计特征、全部候选分数、margin 组成已知计算 DAG。只比较合法切边的守恒，不将所有层边贡献相加，不把节点来源 SHAP 当它的真值。官方 Graph 使用 set 存储节点，adapter 对传入的 graph.nodes 按名字排序以保证 seed 的可重放性，不修改官方算法。full-v1 的原实现/结果已原样保存，canonical Flow 补充运行单独记录，不能覆盖前次结果。

逐块删除诊断复用了精确 coalition 表，在 full enumeration 条件下**不是独立留出样本**；只能作描述统计。另有前置的人工机制变化控制，两者都不构成真实生活干预或外部效用验证。TimeSHAP 为本轮可选项，未实现、未运行；外部真实排序器保持 BLOCKED。
