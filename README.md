# Wearable Knowledge Recommendation

基于纵向可穿戴数据的可解释健康知识推荐。当前为 **离线迁移与工程校验完成**，不是医学验证、人工 Gold 数据集或新方法效果结论。旧项目 `D:\Python\py_projects\c1_pilot` 保持原样；本项目有独立 Git 仓库，无远程推送。

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

Python 3.11+；当前验证使用 Python 3.12。运行及测试仅依赖标准库，不需要安装 SDK、GPU 包或 API Key。从本项目根目录执行：

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
