# 数据与第三方来源

C1 Benchmark V2 另外使用 [WearableQA](https://github.com/facebookresearch/WearableQA)，固定提交 `39fb7ab5f25127e290e6e7e09e38b4fb3d2d7df3`，Lee et al., *WearableQA: A Benchmark for Health Reasoning over Real-World Wearable Data*, arXiv:2609.05405。原始结构化文件保留 CC BY-NC 4.0 以及上游 LICENSE 中禁止重新识别、禁止临床/诊断/治疗决策、禁止有害或误导使用等额外条款。仅研究与基准用途；伪匿名纵向记录、日期、身份映射和逐条标签不提交 Git。

V2 知识仅抽取 MedlinePlus 的 NLM health-topic full-summary（公共领域；署名 **Source: MedlinePlus, National Library of Medicine**）及 MyHealthfinder v4 API 的固定健康教育主题。未导入 A.D.A.M. 百科、药品专论、图片或外链正文。MyHealthfinder 按其 [API Terms of Use](https://odphp.health.gov/our-work/national-health-initiatives/health-literacy/consumer-health-content/free-web-content/apis-developers/terms-use) 保留原文、出处 URL、logo URL 及 LastUpdate；展示时须显示 MyHealthfinder logo/链接与更新时间。标准化只解码 HTML 与空白，不由模型改写来源内容。原文快照及模型记录均留在忽略目录，未重新授权第三方内容。所有下载 URL、时间和 SHA256 在版本化来源清单中保留。

本项目冻结健康窗口来自 **PMData: A Sports Logging Dataset**，Vajira Thambawita and colleagues，MMSys 2020，DOI: https://doi.org/10.1145/3339825.3394926 。原数据页：https://datasets.simula.no/pmdata/ ，原仓库：https://osf.io/vx4bk/ 。

PMData 及其派生测量数据保留 **Creative Commons Attribution-NonCommercial 4.0 International**：https://creativecommons.org/licenses/by-nc/4.0/ 。本项目未更改许可，没有推定商业使用许可。原许可和下载清单保存在忽略的 `data/raw/pmdata/`。

先前 P1 对预先指定的 Fitbit 文件选取字段，处理完全相同的主睡眠重复，保留 null 和质量标志，日期转换为相对日/星期，使用 HMAC 伪匿名身份，形成固定 42 日窗口。此次迁移没有进一步修改冻结数据或标签。伪匿名化不意味着公开纵向记录无法重识别。

知识是带原来源署名的短改写，不是 PMData 人工标注，网页不提供推荐优先级 Gold。网页快照只保留在本机来源闭包，许可不被重新授权；没有把完整网页或第三方模型/源码提交 Git。原语料引用的文档实际位于旧 `reports/CORPUS_AUDIT.md`，已和四份机器编辑审查记录补充归档；其中 reviewed 明确指来源抓取与 LLM 编辑，不是医学或人工确认。

官方方法固定提交与现存许可证哈希见 `configs/upstream_pins.json`；第三方源码没有迁移到公开代码树。新项目尚未选择自己的软件分发许可，不将数据或第三方许可替换成统一软件许可。
