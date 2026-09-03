# JD 语料获取记录（2026-09-02）

> 状态：**讨论稿 / 记录文档**，非 SSOT、非实施依据。目的：记录「大批量获取 JD 文本作为数据」的口径、许可核验结论、语料仓结构与本机执行步骤。
> 身份与治理：本文件归 `research/`，不构成对《总设计文档.md》（SSOT）的任何修改。若后续把该数据采集纳入正式范围（含建库/导入），须先走 SSOT 变更（正文 + §14 变更日志）并获授权，再动代码。

---

## 0. 一句话结论

在「禁止恶意爬取招聘网站」的硬约束下，本阶段**不购买付费数据集、不走站点自动采集**：AI 岗补深取免费的 HuggingFace RocXuLi 集，广覆盖由**自身合规渠道（粘贴 / JSONL 上传）**按几十类主流岗位补齐（每类 10–30 条，课程/演示档几百条量级）。数据集下载须在**本机**执行（本会话沙箱对 HuggingFace / GitHub 打包下载不通），本记录给出核验结论与执行步骤。

## 1. 口径（来自 2026-09-02 讨论确认）

| 项 | 决定 |
|---|---|
| 目标域 | 广覆盖收敛为**控制岗位数**（几十类主流岗位打底，每类 10–30 条即可）+ **AI 岗补深**（以免费数据集为主源） |
| 采集通道 | **仅现成/免付费数据集**（不走浏览器插件、不跑本地半自动站点工具、不抓官网） |
| 付费 | **IEEE Dataport 不购买**（用户 2026-09-02 确认：三分类 2014–2023 研究数据，对答辩性价比低）；广覆盖改由免付费源 + 自身合规渠道（粘贴/JSONL 上传）凑岗位覆盖 |
| 规模 | 课程/演示档：几百条量级即可，不追求研究级大语料 |
| 节奏 | 先核许可再下载 |
| 产出 | 独立语料仓（`data/jd_corpus/`，gitignored）＋本获取记录（`research/`，入库） |
| 阶段边界 | 只获取原文 + 保留来源已有结构（duty/require 若已拆分则保留），**不做任何 LLM/解析/能力抽取** |

## 2. 合规红线（上游约束，不可谈判）

- 需求文档与技术方案概述：**严禁恶意爬虫直接抓取招聘网站数据**。
- PRODUCT.md：数据来源受合规约束——手动粘贴 / JSONL 上传 / 浏览器插件推送；禁止恶意爬虫。
- 本项目本轮只取「已发布、可公开下载」的数据集，且逐份核 license；含个人简历字段的数据集（如 FairCV 类）一律排除。

## 3. 来源许可核验（首轮 2026-09-02 + 复扫 2026-09-03）

> 实测方式：命令行直连 license / repo 结构 / 下载端点探测。沙箱连通性（2026-09-03）：api.github.com / raw.githubusercontent.com / codeload / Kaggle 公开 API 均可达（可整包下载逐字节核验）；HuggingFace 官方域被沙箱 DNS 解析到黑洞 IP 不可达，实测改走 hf-mirror.com 与 us.aws.cdn.hf.co（与官方库同构）。本机下载一律用官方路径即可。

| 来源 | License | 正文是否随包 | 实测结论 | 处置 |
|---|---|---|---|---|
| [SuitJOB](https://github.com/hscspring/SuitJOB)（hscspring） | MIT ✅ | ❌ **正文不在仓库** | 仓库仅含 `category.yml`、岗位 URL 清单、词频模型（`job_description_mark_sorted_dict.txt` 为词表非正文）；README 写明数据需自行运行其爬虫抓取（2019-05） | **不满足「数据集、零抓取」**，降为参考，不采用 |
| [bossJD](https://github.com/yinshaojun001/bossJD) | MIT ✅ | 需运行其本地爬虫 | 面向 BOSS 直聘 AI/Agent 岗的本地采集工具 | 属「本地半自动站点工具」，按本轮口径排除 |
| [RocXuLi AI 岗数据集（HF）](https://huggingface.co/datasets/RocXuLi/AI_Job_DataSet_1000_list) | 本机确认可下载 ✅ | 已下载（1000 条中文 AI 岗） | 实测（2026-09-02）：CSV 仅 `_c0`(岗位名) + `text` 两列；`text` 为「技能标签前缀 ＋ 小节粘合」混合体，含 TAB/`<p>`/引号噪声；**职责/要求非分列**，89 行无小节标记 | **AI 岗补深主源**（已落 `raw/rocxu-ai/res.csv`）；duty/require 不在此拆，原文保留 |
| ~~[IEEE Dataport 招聘文本分类集](https://ieee-dataport.org/documents/recruitment-job-postings-text-classification-results-ai-environmental-protection-other)~~ | 需注册 + 协议 + **$40** | 是（含 JD 自由文本，2014–2023） | 用户 2026-09-02 确认 **不购买**：三分类（AI/环保/其他）不算广覆盖、偏研究、性价比低 | **排除**（不买）。广覆盖改由免付费源 + 自身合规渠道完成 |
| [jd_content_clean](https://gitcode.com/lvupclub/jd_content_clean) | 未知 ❓ | 少量已清洗文本 | gitcode 为 SPA，正文不直连；量小 | 补充参考，非主源 |
| [Chinese-SkillSpan](https://sites.google.com/view/cn-skillspan-resources) | **未随包** ❓（Google Sites 资源页 SPA，沙箱抓不到声明） | **句子级** span 标注，非整条 JD | 已下载实测（2026-09-03）：3 json 共 6022 句、可还原 ~459 条广告（400 条带「岗位(公司)」名）；`train` 无任何标注（skill_spans 全空）；`dev/test` 为 LLM 指令格式（instruction/input/output，output 内嵌 `@@片段##[L/S/K/T]`，**非 gold**）；与论文宣称「2 万+实例、真标注、IID/OOD」不符 → 疑似第三方/部分再打包 | **不采用为 JD 文本语料**（句子级 off-schema、体量小、许可+出处未确证）；仅当拿到官方真标注版才可能作为能力抽取/校验资产 |
| [wunsir/big-data-project](https://github.com/wunsir/big-data-project)（BOSS 直聘 xlsx） | **未声明** ❌ | 是（表头含「职位描述」列） | 实测（2026-09-03）：`boss/joblist_1.xlsx` 2508 行 + `joblist_2.xlsx` ~1500，openpyxl 读正文真实（岗位职责/任职资格） | 内容确证但**无许可，不可直接采用**（须先获作者授权） |
| [Hopetree/Jobs-search](https://github.com/Hopetree/Jobs-search)（智联 xlsx） | **未声明** ❌ | 是（表头含「招聘简介」列） | 实测：`zhilian/201707221501_python_深圳.xlsx` 1891 行，正文真实 | 同上（智联侧最规整） |
| [offercontext/jobAggregation](https://github.com/offercontext/jobAggregation) | **未声明** ❌ | 是（`description` 列） | 实测：`data/test.csv` 500 行（正文非空 274），余量在 `js.7z` | 同上 |
| [JaapTeam/51job](https://github.com/JaapTeam/51job) | **未声明** ❌ | 是（非结构化拼接） | 实测：`data/post_require.txt` 570KB（51job python top650，无小节分隔） | 同上（非结构化，价值低） |
| [lang-uk 英文 JD（HF）](https://huggingface.co/datasets/lang-uk/recruitment-dataset-job-descriptions-english) | MIT ✅ | 是（`Long Description` 列） | 实测（2026-09-03，hf-mirror 通道）：`data/train-*.parquet` 141,897 行，首行即完整 JD 正文 | **英文兜底**（许可+正文双确证，唯一可直接下的大包） |
| [Kaggle sunixliu 川渝 IT 招聘](https://www.kaggle.com/datasets/sunixliu/cdcqxaitjobmarket) | CC0 ✅ | 待核（含「职位要求」类文本列） | Kaggle 公开 API 实测存在、license=CC0；单文件 ~137KB 量小 | 中文备选，**需登录后本机核正文完整度** |

### 3.1 关键事实提示（影响判断）

1. GitHub 上一批名为「JD 数据集」的仓库，很多实际是**爬虫代码或 URL 清单**而非打包正文（SuitJOB 即典型）——核验时必须看仓库正文文件，不能只看 README 的宣称条数。
2. 真实「现成、零抓取、含正文、许可宽松」的中文 JD 语料**比搜索摘要窄**；当前确认采用的主源为 HF RocXuLi（免费、AI 岗）；广覆盖不依赖第三方大语料，由自身合规渠道补齐。
3. 数据集岗位体系普遍停在 2019–2023，**「AI Agent / 大模型应用工程师」这类 2024–2026 新角色几乎无对口真实样本**——「AI 补深」在数据集-only 口径下的现实含义是：把现成集中最接近的 AI/算法岗尽量抽出，而非拿到 2026 年的真实 AI Agent JD。
4. **实测警示（2026-09-02）**：HF 数据卡片预览 ≠ 实际下载文件。RocXuLi 卡片显示「职位描述/职位要求」两列，但 `res.csv` 实为 `_c0`(岗位名)+`text` 两列，`text` 内嵌「技能标签前缀 + 岗位职责/任职要求等小节粘合」且含 TAB/`<p>`/引号噪声。**下载后必须以文件实际结构为准，不能照卡片 schema 写归一化。**
5. **三路复扫结论（2026-09-03，HF/GitHub/Kaggle 并行逐字节实测）**：许可干净 + 正文随包 + **中文** 的第三方大语料**没有第二家**——中文免费现成集仍只有 RocXuLi（AI 岗）。HF 侧「中文 JD」全是陷阱：以 `jd`/`JD_` 命名的是「京东」电商评论（`jd21`、`JD_review`），拉勾抓取样例正文列为空（`lagou-*` 实测 jobDescription=None），其余是含个人简历的匹配对（`resume-job-description-fit` 系列）或 LLM 合成文本（`job_description_7k`）。
6. GitHub 上正文确证随包的中文仓库（wunsir/Hopetree/offercontext/JaapTeam，共 ~4k+ 条 BOSS + 1891 智联 + 若干）**全部未声明许可**，按硬约束不可直接采用——再次复证结论 1/2：不能只看 README 宣称与仓库名，须看实际文件与 LICENSE。
7. 许可干净的可下大包全部落在**英文**侧（lang-uk 141,897 条 MIT；Kaggle 多处 CC0/MIT 真实招聘全文）——只能作方法论/跨语言备份，不覆盖中文岗位内容。
8. 中文学术级唯一线索 = **Chinese-SkillSpan**（arXiv 2604.23009：中文招聘广告 span 级技能标注、2014–2025、4 平台，宣称含 IID/OOD 划分与 scorer、2 万+实例）。用户 2026-09-03 下载、实测后判定：下到的是**句子级 LLM 标注再打包**（6022 句 / 459 广告、dev/test 指令格式 output 非 gold、train 零标注），**与官方宣称的 gold 版不符**，且文件无 license、资源页许可声明沙箱无法抓取 → **不构成 JD 文本语料**，对「获取原文备用」的目标无效。其真正价值（若有）在官方真标注版用于后期能力抽取校验，需本机核资源页两点：**许可、gold 版是否含正文全文**。

## 4. 语料仓设计（`data/jd_corpus/`，gitignored）

```
data/jd_corpus/
  raw/          每个来源一个子目录，保留原始下载物（zip/json/gz），不改动
  normalized/   去重、统一字段后的 jsonl 或 parquet
  manifest.csv  来源 / 许可 / 下载日期 / 条数 / 字段说明
```

### 4.1 统一记录 schema（不做能力解析，只保留来源已有结构）

```
job_title       原文岗位名（不归一）
company         公司（可为空）
city?           来源含则保留
text_raw        正文全文（原始）——永远保留一份
duty?          来源已拆「职责」段则保留，否则空
require?       来源已拆「要求」段则保留，否则空
source          数据集标识（如 ieee / rocxu-ai）
license         该份数据许可结论
collected_at    下载日期
dedup_key       规则计算的去重键
```

要点：原文 `text_raw` 永不丢弃；来源已拆好的 `duty/require` 结构保留不丢——为后续「能力/岗位分块归档」留接口。本阶段不新增任何解析字段。

## 5. 本机执行步骤（沙箱不可代跑）

1. **下载主源**：HuggingFace `RocXuLi/AI_Job_DataSet_1000_list`，原始件落 `data/jd_corpus/raw/rocxu-ai/`（本机可访问 HF，沙箱不可）。
2. **广覆盖补齐**（不依赖第三方）：用系统现有合规接入（模块一粘贴 / JSONL 文件上传，或直接向语料仓追加），覆盖目标主流岗位每类 10–30 条。
3. **归一化去重**（纯规则脚本，非 LLM）：
   - 按 `(规范化标题, 公司, 正文归一化 hash)` 去重；
   - 过滤 <30 字空壳 / 纯模板 / 乱码；
   - 产出 `normalized/` + `manifest.csv`。
4. **留档**：`manifest.csv` 每行含 来源/许可/下载日期/条数，构成答辩的合规证据链。

## 6. 待办 / 开放项

- [x] 本机下载 HF RocXuLi AI 岗数据集 → 落 `raw/rocxu-ai/` → 确认正文结构（2026-09-02 已确认为 `_c0`+`text` 两列、非分列）
- [x] 归一化脚本编写（`scripts/jd_corpus_normalize.py`，2026-09-02 已提交；1000→1000，0 短 0 重）
- [ ] 广覆盖岗位清单（目标几十类主流岗位的名称/别名清单）——供自身渠道逐类补齐（用户 2026-09-02 暂缓，需要时再做）
- [ ]（可选 · 中文学术线索）本机核 Chinese-SkillSpan 官方 gold 版：许可 + 是否随包含正文全文——**本次下载的句子级 LLM 再打包版不可用**（见 §3），仅当 gold 版可取时才作为「中文 JD + 能力」校验资产
- [ ]（可选 · 英文兜底）如要跨语言/方法论大包：本机下 lang-uk（MIT 141,897 条）或 Kaggle Job_Postings_US（CC0 1,000 条）
- [ ]（非推荐）GitHub 无许可中文仓库（wunsir BOSS ~4k 等）：仅当先取得作者授权后方可入库，否则不进语料仓/答辩链

## 7. 相关文档关系

- SSOT：《design/final-design/总设计文档.md》；本文件**不**与其冲突，也不构成其变更。
- 需求/合规：《design/需求文档…》《design/技术方案概述.md》——上游约束来源。
- checkpoint 12.4 将「真实 JD 数据集」列为 M4 保留不做；若本轮采集要转正式范围，属扩围，须 SSOT 授权流程。
