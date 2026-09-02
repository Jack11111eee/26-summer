# JD 语料获取记录（2026-09-02）

> 状态：**讨论稿 / 记录文档**，非 SSOT、非实施依据。目的：记录「大批量获取 JD 文本作为数据」的口径、许可核验结论、语料仓结构与本机执行步骤。
> 身份与治理：本文件归 `research/`，不构成对《总设计文档.md》（SSOT）的任何修改。若后续把该数据采集纳入正式范围（含建库/导入），须先走 SSOT 变更（正文 + §14 变更日志）并获授权，再动代码。

---

## 0. 一句话结论

在「禁止恶意爬取招聘网站」的硬约束下，本阶段 **只走现成公开数据集**（零抓取），先**广覆盖主流岗位铺底**、再尽量加深 **AI/大模型/Agent 方向**。数据集下载须在**本机**执行（本会话沙箱对 HuggingFace / GitHub 打包下载不通），本记录给出核验结论与逐源执行步骤。

## 1. 口径（来自 2026-09-02 讨论确认）

| 项 | 决定 |
|---|---|
| 目标域 | **广覆盖 + AI 岗补深**（几十类主流岗位打底；AI/大模型/Agent 方向单独加深） |
| 采集通道 | **仅现成数据集**（不走浏览器插件、不跑本地半自动站点工具、不抓官网） |
| 节奏 | **先核许可再下载** |
| 产出 | 独立语料仓（`data/jd_corpus/`，gitignored）＋本获取记录（`research/`，入库） |
| 阶段边界 | 只获取原文 + 保留来源已有结构（duty/require 若已拆分则保留），**不做任何 LLM/解析/能力抽取** |

## 2. 合规红线（上游约束，不可谈判）

- 需求文档与技术方案概述：**严禁恶意爬虫直接抓取招聘网站数据**。
- PRODUCT.md：数据来源受合规约束——手动粘贴 / JSONL 上传 / 浏览器插件推送；禁止恶意爬虫。
- 本项目本轮只取「已发布、可公开下载」的数据集，且逐份核 license；含个人简历字段的数据集（如 FairCV 类）一律排除。

## 3. 来源许可核验（截至 2026-09-02 实测）

> 实测方式：命令行直连 license / repo 结构 / 下载端点探测。沙箱无法访问 HuggingFace 与 GitHub 打包下载（codeload），故标「本机待核」。

| 来源 | License | 正文是否随包 | 实测结论 | 处置 |
|---|---|---|---|---|
| [SuitJOB](https://github.com/hscspring/SuitJOB)（hscspring） | MIT ✅ | ❌ **正文不在仓库** | 仓库仅含 `category.yml`、岗位 URL 清单、词频模型（`job_description_mark_sorted_dict.txt` 为词表非正文）；README 写明数据需自行运行其爬虫抓取（2019-05） | **不满足「数据集、零抓取」**，降为参考，不采用 |
| [bossJD](https://github.com/yinshaojun001/bossJD) | MIT ✅ | 需运行其本地爬虫 | 面向 BOSS 直聘 AI/Agent 岗的本地采集工具 | 属「本地半自动站点工具」，按本轮口径排除 |
| [RocXuLi AI 岗数据集（HF）](https://huggingface.co/datasets/RocXuLi/AI_Job_DataSet_1000_list) | 本机待核 ❓ | 需下载（1000 条中文 AI 岗） | HF API/resolve 在沙箱不可达，license 卡片未读到 | **首选待核**：本机打开数据卡片确认 license 是否允许下载/再分发 |
| [IEEE Dataport 招聘文本分类集](https://ieee-dataport.org/documents/recruitment-job-postings-text-classification-results-ai-environmental-protection-other) | 需注册 + 同意协议 ❓ | 是（含 JD 自由文本，2014–2023，22 字段含 label） | 页面可达（200），下载需账号走协议 | **待核**：注册后确认条款与字段可用性 |
| [jd_content_clean](https://gitcode.com/lvupclub/jd_content_clean) | 未知 ❓ | 少量已清洗文本 | gitcode 为 SPA，正文不直连；量小 | 补充参考，非主源 |
| [Chinese-SkillSpan](https://ar5iv.labs.arxiv.org/html/2604.23009) | 待核 ❓ | 学术标注集（span 级技能，对齐 ESCO） | arxiv 镜像沙箱不通 | 后期做能力抽取/校验的潜在资产，非本轮获取源 |

### 3.1 关键事实提示（影响判断）

1. GitHub 上一批名为「JD 数据集」的仓库，很多实际是**爬虫代码或 URL 清单**而非打包正文（SuitJOB 即典型）——核验时必须看仓库正文文件，不能只看 README 的宣称条数。
2. 真实「现成、零抓取、含正文、许可宽松」的中文 JD 语料**比搜索摘要窄**；当前确认可当正文来源的只有 IEEE（需注册协议）与 HF RocXuLi（需本机核 license）。
3. 数据集岗位体系普遍停在 2019–2023，**「AI Agent / 大模型应用工程师」这类 2024–2026 新角色几乎无对口真实样本**——「AI 补深」在数据集-only 口径下的现实含义是：把现成集中最接近的 AI/算法岗尽量抽出，而非拿到 2026 年的真实 AI Agent JD。

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

1. **核许可**（本机打开确认，倒查可再分发/署名要求）：
   - HuggingFace `RocXuLi/AI_Job_DataSet_1000_list` 数据卡片 license；
   - IEEE Dataport 注册 + 下载协议条款。
2. **下载**：分别落 `data/jd_corpus/raw/<source>/`，冻结原始件。
3. **归一化去重**（纯规则脚本，非 LLM）：
   - 按 `(规范化标题, 公司, 正文归一化 hash)` 去重；
   - 过滤 <30 字空壳 / 纯模板 / 乱码；
   - 产出 `normalized/` + `manifest.csv`。
4. **留档**：`manifest.csv` 每行含 来源/许可/下载日期/条数，构成答辩的合规证据链。

## 6. 待办 / 开放项

- [ ] 本机核 HF RocXuLi license → 通过则下载做 AI 岗补深主源
- [ ] 本机注册 IEEE Dataport → 核字段与协议 → 下载做广覆盖主源
- [ ] 复核 SuitJOB 是否存在仓库外正文镜像（若存在再纳入评估）
- [ ] 归一化脚本编写（数据就位后做，避免空跑）

## 7. 相关文档关系

- SSOT：《design/final-design/总设计文档.md》；本文件**不**与其冲突，也不构成其变更。
- 需求/合规：《design/需求文档…》《design/技术方案概述.md》——上游约束来源。
- checkpoint 12.4 将「真实 JD 数据集」列为 M4 保留不做；若本轮采集要转正式范围，属扩围，须 SSOT 授权流程。
