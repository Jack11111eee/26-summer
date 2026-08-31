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
# 类间权重配比 hard_skill:soft_skill:experience:qualification
CATEGORY_RATIO = {
    "hard_skill": 5.5,
    "soft_skill": 2.0,
    "experience": 2.0,
    "qualification": 0.5,
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
# 用户输入超过该 token 数（近似 len/2）才走 P-refine 精炼
REFINE_MIN_TOKENS = int(os.environ.get("REFINE_MIN_TOKENS", "500"))
# 单题追问上限（07 §7.2）
FOLLOWUP_MAX = int(os.environ.get("FOLLOWUP_MAX", "2"))
