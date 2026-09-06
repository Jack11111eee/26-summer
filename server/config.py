"""环境变量与可配置常量（05 文档 §8.4）。

仅用 os.environ 读取，不引第三方 dotenv；
.env 的加载由 main 入口（--env-file 或手动）负责。
"""

import os

# ---- LLM ----
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "mock")  # deepseek | mock
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")

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
# importance 聚合双比率阈值
REQ_THRESHOLD = 0.5
R_THRESHOLD = 0.5
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
# 滑窗 Token 上限（SSOT §31-2 开放参数：「参数待定，留接口」——
# 已裁决 8000（关口包 [03-007]，2026-09-05），mock 模式全量直通）
MAX_CONTEXT_TOKENS = 8000  # 已裁决值（关口包 [03-007]——不再 checkpoint 停车）

# ---- 模块四·Phase 6 评测收口（REF-5.11 bad case 双分背离）----
# |score_live - score_final| ≥ 阈值 → 自动 INSERT bad_case_candidate（status='pending'），
# 永不自动改分（D-031）。阈值 = SSOT §2.3「配置阈值」开放参数——None 占位，
# 实施期校准待用户裁决（禁止臆造默认值）；None 时 _detect_bad_case_divergence 直接跳过不检测。
BAD_CASE_DIVERGENCE_THRESHOLD = None  # 实施期校准 — 待用户裁决（双分背离阈值）

# ---- 模块四·Phase 6 安全收尾（REF-6.3 输入限额 + §31-5/§31-6 开放参数）----
# 输入限额按类型配置（REF-6.3/D-078）：各类型具体数值为开放参数——None 占位，
# 实施期校准待用户裁决（禁止臆造默认值）。已决值沿用：MAX_ANSWER_LEN=64*1024
# （services/scoring.py）、MAX_CONTEXT_TOKENS=8000（本文件上方）。
MAX_JD_LENGTH = None  # 实施期校准 — 待用户裁决（JD 文本长度上限）
MAX_JD_FILE_LINES = None  # 实施期校准 — 待用户裁决（JSONL 文件行数上限）
MAX_PAGINATION_LIMIT = None  # 实施期校准 — 待用户裁决（分页 limit 上限）
# trace 数据治理开放参数（SSOT §31-5）：保留期/脱敏开关——None 占位待裁决
TRACE_RETENTION_DAYS = None  # 实施期校准 — 待用户裁决（trace 保留期天数）
TRACE_DESENSITIZE = None  # 实施期校准 — 待用户裁决（trace 脱敏开关）
# 幂等清理开放参数（SSOT §31-6）：清理阈值——None 占位待裁决
IDEMPOTENCY_CLEANUP_THRESHOLD = None  # 实施期校准 — 待用户裁决（幂等清理阈值）

# ---- 模块一·消歧/归岗开放参数（SSOT §31-4）----
# 词典候选 top10 匹配阈值与清洗标题词表：开放参数——占位待裁决（禁止臆造默认值）。
# 只落占位不接线消费：DICT_MATCH_THRESHOLD=None（消歧候选阈值）、
# TITLE_CLEAN_WORDS=[]（归岗标题清洗词表），实施期校准后由用户裁决取值。
DICT_MATCH_THRESHOLD = None  # 实施期校准 — 待用户裁决（词典候选 top10 匹配阈值）
TITLE_CLEAN_WORDS: list[str] = []  # 实施期校准 — 待用户裁决（清洗标题词表）
