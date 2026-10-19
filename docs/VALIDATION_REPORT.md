# 迁移验收记录

日期：2026-10-18；Python 3.12.8；本机离线执行。结论：**`PASS_ENGINEERING_ONLY`**。没有新增模型调用、人工标注、训练或方法实现。科研上的来源条件、优先级 Gold 和从未接触测试队列仍然 `BLOCKED`。

执行命令：

```powershell
python tools/check.py --name final-v2 --source-root D:\Python\py_projects\c1_pilot
```

单元/真实数据集成测试 **35/35 通过**，退出码 0；完整迁移校验退出码 0。原 stdout/stderr、命令、时间和机器结果保存在忽略的 `local/validation/final-v2/`；公开聚合结果与日志 SHA 在 `docs/VALIDATION_RESULTS.json`。完整命令用新版本名可重跑，已有日志不覆盖。

| 检查 | 实测结果 |
|---|---|
| 新旧原字节一致 | 初次 2,504 次复制 + 补充 5 份语料编辑审计资产，共 2,509 次复制字节数/SHA 全相同；4 个纯函数提取模块的来源和产物 SHA 固定 |
| 旧项目保持 | 2,931 个源文件重新哈希完全一致；旧 HEAD/分支/工作区状态一致；77 个旧冻结哈希一致 |
| P1 发布 | 7 个文件原样保存；release ID `872d04eb05394b3f3ac37c05dcefe320181e9375a674ba7c4fb57c8853742604` |
| A1 发布 | 5 个文件原样保存；release ID `6e92073cf3bfe0cb12ae63f7a281490ab54bf21a44a0ad5cad56e6885512d523` |
| Silver 发布 | 4 个文件原样保存；release ID `2bd7232e05fa9bc02c53490430abd8c2bcb889a6174b1f1e7ecde9e9dd50804e` |
| Raw 来源 | 16 人、96 个预定文件槽位；93 份下载文件 SHA/字节数正确、3 份源端缺失仍缺失；原始许可/URL/清单链一致 |
| 原始数据→窗口 | 48 个 HMAC 身份/日期/块一致；2,016 日、10,080 个数值、14,112 个睡眠字段逐项核验，无同人窗口重叠 |
| 独立导入回放 | 测试用迁移后的纯导入函数重建所有 48 例，逐对象等于冻结窗口；没有写新案例或旧文件 |
| 质量标志 | RHR=0 共 90 日；相同主睡眠重复 50 日；非零 sleep infoCode 28 日，均与原审计一致 |
| 参与者隔离 | train/dev/test = 10/3/3 人、30/9/9 窗口；重复、遗漏、跨集合泄漏均被拒绝；不是 pristine test |
| 知识来源 | 50 份冻结文本/HTML 哈希正确；A1 26 套来源锚点、6 组/27 次组成员关系/1,248 个唯一对一致 |
| 旧 source manifest 差异 | 24 份文本 CRLF→LF 后恰等于历史 text SHA；当前冻结字节保留；两份采样计划字节不同、JSON 完全等价 |
| Silver | 160 条/80 个唯一对；119 条旧引用 schema 接受、41 条未接受；88 份含 malformed 的缓存、91 个请求和 8 份 primary source snapshots 哈希链通过 |
| Silver 预算 | 原 ledger 的 91 次历史尝试可审计；旧金额/授权不转移，新调用为 0，不读 API Key |
| Baseline pin | 11 个本机官方固定 SHA 和跟踪源码一致，已有许可文件哈希一致；本轮原生新运行 0 |
| B0 / C0-A | 16 个冻结 payload SHA 一致；200 条输出含 24 failed、13 invalid；原 16/140 卡、156 行 crosswalk、21 个失败槽位逐对象精确回放 |
| Git 私有边界 | raw/processed/releases、身份密钥/映射、逐条 Silver、轨迹和拆分身份清单均被忽略；索引无私有记录 |

测试覆盖了冻结字节/manifest 被篡改、额外文件、路径越界、覆盖写入、同人泄漏/遗漏、重复睡眠与冲突、bool/NaN/负数测量、未知证据引用、零 RHR 生理排除、缓存篡改/模型身份隔离/截断输出、禁用网络/重试/新 Baseline，以及失败槽位/全 ties 的保留。真实集成校验期间 mock socket 禁止网络访问；所有验证逻辑无需 API SDK。

另做了独立恢复演练：仅复制 Git 索引中的 52 个公共文件到忽略的短路径工作区，再从旧项目恢复私有资产，随后运行全部 35 项测试和含旧源哈希/11 个官方 SHA 的完整验证，均通过。日志在 `local/validation/restore-v2/`，恢复工作区在 `local/r/`。没有从主新项目复制私有数据来使恢复通过。

首次把恢复工作区放在较深目录时，历史长缓存文件名触发 Windows `MAX_PATH`，失败和部分副本保留在 `local/validation/restore-v1/`，未改名或覆盖冻结文件。换短路径后原样恢复通过。当前正式项目最长迁移路径为 244 字符；迁移到更深路径仍有此限制，不能把失败演练隐去。

## 仍然 BLOCKED

- `BLOCKED_INDEPENDENT_HUMAN_SOURCE_REVIEW`：字面来源锚点不等于医学和必要条件确认。
- `BLOCKED_HUMAN_PRIORITY_GOLD`：无真实独立双评/裁决，准确率、解释忠实性、改进率仍为 null。
- `BLOCKED_PRISTINE_HELDOUT_COHORT`：原 16 人都曾进入历史实验，新划分不能抹去接触史。
- `BLOCKED_QWEN3_8_MAX_NEW_SILVER_NOT_RUN`：旧标签来自 qwen-max；新目标模型未调用、未标注。
- `BLOCKED_SOURCE_UNAVAILABLE_NOT_IN_ACTIVE_PANELS`：旧根来源 `nhlbi_diagnosis`、`aha_hr` 无原快照；不在当前 P1/A1 面板。
- 部分方法的健康 scorer/交互模型/训练监督/权重缺失，及六个上游的再分发许可未确立，详见 Baseline 清单。

所有中间验证输出仍保留。首次验证只在 Windows Git 忽略检查中遇到文本管道 CRLF 路径差异，已改为 Git 的 NUL 分隔二进制输入，随后全项通过。语料 provenance 的审计文档后来定位在旧 `reports/`，已补充归档，撤销早期“根目录缺失”等于文档丢失的暂定判断。没有为使验证通过而改动任何源数据、标签或历史输出。验证不能证明医学正确、论文效果复现或未来方法必要性。
