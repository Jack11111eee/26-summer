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
