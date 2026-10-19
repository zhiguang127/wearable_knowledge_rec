# Q1 Pilot 执行验收

日期 2026-10-19。分支 codex/q1-pilot；未推送、未合并。当前实验代码、版本化配置、实际运行及中文研究报告均已交付。研究判定 INCONCLUSIVE；测试范围内没有支持新算法的残余失败。

## 实际命令与退出状态

除改动前验收使用 bundled Python，以下 Python 均为项目独立 local/q1-venv/Scripts/python.exe，版本 3.12.14。

| 实际执行入口与参数 | 退出码 | 证据与结果 |
|---|---:|---|
| tools/check.py --name q1-preflight-v1 --source-root D:/Python/py_projects/c1_pilot | 0 | 原 35 测试通过，独立工程校验通过 |
| experiments/q1_pilot/run.py --name smoke-v1 --smoke | 0 | 首个合格真实窗口，90 条条件记录 |
| experiments/q1_pilot/run.py --name full-v1 | 0 | 14 人、38 窗、3,420 条条件记录，0 failed/blocked |
| experiments/q1_pilot/recheck.py --name flow-canonical-v1 | 0 | 76 条政策条件，各重复图构建，seed 重放一致；456 个额外数值探针 |
| experiments/q1_pilot/negative_controls.py --name negative-controls-v1 | 0 | 114 条官方 item-only 控制，归因全部为零 |
| experiments/q1_pilot/analyze.py --run full-v1 --supplement flow-canonical-v1 | 0 | 真实运行聚合、中文报告及预算图 |
| experiments/q1_pilot/setup.py | 0 | 已安装依赖与三个固定官方源码再次验证 |
| experiments/q1_pilot/run.py --name smoke-final-v2 --smoke | 0 | 最终版本的 release 契约检查、canonical Flow 与主闭环再次通过 |
| tools/check.py --name q1-final-v3 --source-root D:/Python/py_projects/c1_pilot | 0 | **69/69 测试通过**；完整校验 PASS_ENGINEERING_ONLY |

开发过程的 q1-tests-development-v1/v2 与 q1-final-v1/v2 结果均保留，没有覆盖。最新最终测试耗时 4.934 秒，工程校验耗时 5.687 秒。

## 原始证据与版本

- 私有逐例输出、命令参数、stdout/stderr、原生 smoke、配置和实现 SHA 在 local/experiments/q1_pilot 的独立版本目录。
- full-v1 的运行前 10 个实现/配置文件原字节快照在 full-v1/sources，source_snapshot.json 与 manifest 哈希逐项一致。之后的 Flow 输入节点排序修复在 canonical 补充运行中单独记录；没有回写 full-v1。
- 生成 summary-v1.json 的原分析源码保存在 full-v1/analysis-v1.py，其 SHA 等于聚合文件的 analysis_code_sha256。最终报告审阅修正了一处运行路径显示，并补充预算表和官方阴性控制；原数字结果不变。
- 公开聚合只在 experiments/q1_pilot/results；没有逐例健康记录或身份 ID。负对照单独保留 negative-controls-v1.json。
- 官方三个原生样例均 NATIVE_REPRODUCED，健康接口均 TASK_ADAPTED_AND_RUN；TimeSHAP 可选项未实现未运行；外部真实排序器 BLOCKED。
- 总运行记录 3,420 是预定条件记录，不能当独立人或都当方法比较；其中包含行为/背景/精确参考/诊断。额外 Flow 重放和 114 阴性控制不增加参与者数。
- 缓存键为 coalition mask，记录真实计算与重复请求，不按数值输入内容跨 coalition 去重；dummy 来源的不同 mask 可对应相同数值输入。每个方法/预算/种子独立冷缓存。

## 完整性与隐私

最终重新核验旧项目 2931 个文件、77 个旧冻结哈希、11 个原有官方源码 checkout；旧 HEAD/分支/工作区状态与迁移基准相同。P1、A1、Silver 发布校验通过。没有调用或读取 LLM API Key，没有付费 LLM 请求、训练、人工标签或新算法。

两个新官方仓库与新项目内 RankingShap 副本另由 setup.py 检查固定 HEAD 和跟踪源码未改。私有数据依然位于 Git 忽略目录。公开文本逐文件扫描实际 case_id/subject_id，聚合 JSON 的生成器也拒绝身份泄漏；聚合预算图已经人工视觉检查。

SHA 证据：最终工程验证 JSON `3c7f6aae9c3399c50221ab3364e31d1af3ef9ae3534bce8784c8b121b3af5c89`；最终测试 stderr `e45b308d00d80e99617962df752dcd670bac4a17a3d51dd496759934f2042177`。

## 实际修改与新增文件

- `README.md`
- `docs/Q1_PILOT_READOUT.md`
- `docs/STUDY_PROTOCOL.md`
- `docs/VALIDATION_Q1.md`
- `experiments/README.md`
- `experiments/q1_pilot/README.md`
- `experiments/q1_pilot/analyze.py`
- `experiments/q1_pilot/config.json`
- `experiments/q1_pilot/negative_controls.py`
- `experiments/q1_pilot/protocol.md`
- `experiments/q1_pilot/recheck.py`
- `experiments/q1_pilot/requirements.lock.txt`
- `experiments/q1_pilot/results/budget-error-v1.png`
- `experiments/q1_pilot/results/negative-controls-v1.json`
- `experiments/q1_pilot/results/summary-v1.json`
- `experiments/q1_pilot/run.py`
- `experiments/q1_pilot/setup.py`
- `src/q1_pilot/__init__.py`
- `src/q1_pilot/baseline_adapters.py`
- `src/q1_pilot/coalition_game.py`
- `src/q1_pilot/evaluation.py`
- `src/q1_pilot/exact_shapley.py`
- `src/q1_pilot/interventions.py`
- `src/q1_pilot/scorers.py`
- `tests/test_q1_pilot.py`
