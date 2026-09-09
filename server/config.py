"""环境变量与可配置常量（05 文档 §8.4）。

仅用 os.environ 读取，不引第三方 dotenv；
.env 的加载由 main 入口（--env-file 或手动）负责。
"""

import os

# ---- LLM ----
# provider 三态（2026-09-06）：deepseek=OpenAI 兼容 chat.completions；
# anthropic=Anthropic Messages 协议（中转上行 glm-5.3-flash 未开 chat，实测
# Messages 全量 prompt 可用）；mock=离线规则模拟
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "mock")  # deepseek | anthropic | mock
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
# LLM 并发上限（2026-09-06 实测 bingchanpro 免费池：同时错峰在途 >3 即
# 503 no_available_providers，前 3 个可并行——令牌桶容量≈3、回填慢）
LLM_MAX_CONCURRENT = int(os.environ.get("LLM_MAX_CONCURRENT", "3"))

# ---- JWT ----
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-.env")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 12

# ---- 数据库 ----
DB_PATH = os.environ.get("DB_PATH", "data/app.db")

# ---- 可配置常量（§8.4）----
# 类间权重配比（SSOT §8.2 v2.0 关键修正：普通题类目比例 7:3）
# hard 0.7 / soft 0.3 / experience 0.0 / qualification 0.0；
# gate 类（experience/qualification）走表单事实核验不占权重池（§8.2）。
# D-16：存量 confirmed 模型 weight 不重算——分数是历史事实（D-003），本常量只影响新聚合模型。
CATEGORY_RATIO = {
    "hard_skill": 0.7,
    "soft_skill": 0.3,
    "experience": 0.0,
    "qualification": 0.0,
}
# 类内重要性系数
IMPORTANCE_COEF = {"required": 1.0, "preferred": 0.6, "plus": 0.3}
# importance 混合口径（SSOT §8.1 工序⑤；required 2026-09-07 裁决、preferred 2026-09-08 裁决）
# required 三重判据：条件 req（req_jds/出现 jds）≥ REQ_THRESHOLD、
# r ≥ REQ_MIN_OCCURRENCE_RATIO、出现 JD 数 ≥ REQ_MIN_OCCURRENCE；
# 仅 hard_skill 可判 required（soft_skill 上限 preferred，2026-09-07）。
# preferred occ 基准（2026-09-08）：未达 required 且出现 JD 数 ≥ PREFERRED_MIN_OCCURRENCE；
# 绝对 r 阈值与样本量耦合（34 模型 15 个 preferred=0）已退役。
REQ_THRESHOLD = 0.5  # 条件口径阈值（语义 2026-09-07 变更：标 required 的 JD 数 ÷ 出现 JD 数）
REQ_MIN_OCCURRENCE_RATIO = 0.25
REQ_MIN_OCCURRENCE = 3
PREFERRED_MIN_OCCURRENCE = 3
# LLM 校验失败重试次数
LLM_RETRY = 2
# 清洗时要求块最小长度（低于则 low_confidence=1）
CLEAN_MIN_REQ_LEN = 30

# ---- 模块二：测评（07 文档 §8/§14-7）----
# 岗位级普通题计划数 N（SSOT §10.1/§31-1）：普通主问题配额的基数，
# 与 7:3 最大余数 + tier 公式共同决定每次会话的选题目标。
ORDINARY_PLAN_N = 10  # 生产默认值——2026-09-04 关口 A 用户裁决（02-DECISIONS [02-007]）
# 用户输入超过该 token 数（近似 len/2）才走 P-refine 精炼
REFINE_MIN_TOKENS = int(os.environ.get("REFINE_MIN_TOKENS", "500"))
# 单题追问上限（07 §7.2）
FOLLOWUP_MAX = int(os.environ.get("FOLLOWUP_MAX", "2"))

# ---- 模块二·Phase 3 计时（SSOT §15——40/20/6 硬编码非开放参数）----
SESSION_TOTAL_MINUTES = 40
QUESTION_TIMEOUT_MINUTES = 20
ABANDON_HOURS = 6

# ---- 模块二·题库契约过渡开关（SSOT §9.4 契约第 1 条 / §13 旧题处理，2026-09-09）----
# 新题生成无条件写满五测量字段（measurement_target / evidence_requirement /
# observable_level_max / observable_level_min / rubric_version——代码侧强制）；
# 存量旧行五字段全 NULL（不迁移不回填——机械填值不能制造可靠锚点，修复文档 §十三
# 「旧题处理」）。默认 False：选题/开考检查不按字段过滤（现状行为，存量岗位可继续
# 开考）；True 时白名单只认五字段齐全的 active 题（任一 NULL 视为「待审核」，新
# 测评不选用）。打 True 须先确认存量岗位已用新契约重新生成题库。
QBANK_STRICT_FIELDS = os.environ.get("QBANK_STRICT_FIELDS", "").strip().lower() in ("1", "true", "yes")
# 滑窗 Token 上限（SSOT §31-2 开放参数：「参数待定，留接口」——
# 已裁决 8000（关口包 [03-007]，2026-09-05），mock 模式全量直通）
MAX_CONTEXT_TOKENS = 8000  # 已裁决值（关口包 [03-007]——不再 checkpoint 停车）

# ---- 模块四·Phase 6 评测收口（REF-5.11 bad case 双分背离）----
# |score_live - score_final| ≥ 阈值 → 自动 INSERT bad_case_candidate（status='pending'），
# 永不自动改分（D-031）。已裁决 2（2026-09-06 第十轮收口，SSOT §14；1–5 整数刻度下
# |diff|>=2 才构成"双分显著相反"信号，阈值 1 会把 mock 单点偏差灌成噪声队列）。
BAD_CASE_DIVERGENCE_THRESHOLD = 2

# ---- 模块四·Phase 6 安全收尾（REF-6.3 输入限额 + §31-5/§31-6 开放参数）----
# 输入限额按类型配置（REF-6.3/D-078）。已裁决（2026-09-06 第十轮收口，SSOT §14）：
# JD 文本上限 10000 字符（真实 JD 鲜超 5000，宽裕上限；控单请求输入成本）、
# JSONL 批量导入行数上限 500（防误传大文件的无上限后台成本）、
# 分页 limit 上限 100（超限钳到 100，下限 1）。
# 已决值沿用：MAX_ANSWER_LEN=64*1024（services/scoring.py）、MAX_CONTEXT_TOKENS=8000（上方）。
MAX_JD_LENGTH = 10000
MAX_JD_FILE_LINES = 500
MAX_PAGINATION_LIMIT = 100
# 意见反馈文本上限（SSOT §22.1，2026-09-08——对齐 MAX_JD_LENGTH 先例：真实建议鲜超
# 千字，宽裕上限控单请求输入成本）
MAX_SUGGESTION_LENGTH = 2000

# ---- 演示期不启用（SSOT §31-4/§31-5/§31-6，2026-09-06 裁决 by-design）----
# 曾经的开放参数占位已摘除：TRACE_RETENTION_DAYS / TRACE_DESENSITIZE（trace 全量保留
# 利于验收审计，脱敏妨碍 #40 观察层验证）、IDEMPOTENCY_CLEANUP_THRESHOLD（demo 量级
# 到不了阈值，无清理任务/接口）、TITLE_CLEAN_WORDS（清洗走 pipeline 内置
# NOISE_HEADERS/_SUFFIXES 硬编码表）。生产 PII 治理/清理策略随真实上线在 SSOT §31 重开。
# 重大冲突极差阈值（§19：观测等级极差 ≥ 阈值判冲突取低）——历史在 aggregation.py 模块级，
# 2026-09-06 转正集中到 config（值不变，SSOT §14）。
ADJUDICATE_CONFLICT_THRESHOLD = 2

# ---- 模块三·报告完整性门控（SSOT §20.1/§20.3/§31-3，U4 2026-09-09）----
# 未测量比例阈值：正式范围内未测量项占比 > 0.2 → 无完整综合分（total_score=None）+
# PROVISIONAL + HUMAN_REVIEW_REQUIRED（review_reason_code=UNMEASURED_RATIO_HIGH）。
# 值沿用 2026-09-05 关口 A 裁决 0.2；语义由 IMPUTED 补算比例改为未测量比例
# （§20.1 作废比例补算——旧 aggregation.py IMPUTE_RATIO_THRESHOLD 更名承接）。
UNMEASURED_RATIO_THRESHOLD = 0.2

# ---- 模块一·消歧/归岗（SSOT §31-4）----
# 词典候选 top10 匹配阈值：已裁决 0.5（difflib ratio + 子串包含，2026-09-06），
# 由 services/pipeline._dict_candidates 消费；清洗标题词表不启用（见上方摘除说明）。
DICT_MATCH_THRESHOLD = 0.5  # 词典候选 top10 匹配阈值（已裁决，difflib ratio）

# ---- Web 层（server/main.py CORS）----
# allow_credentials=True 下 CORS 不可为 *；env 化便于换机/局域网演示，
# 默认 Vite dev server，多来源逗号分隔（CORS_ORIGINS=http://a,http://b）。
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
