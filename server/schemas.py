"""Pydantic v2 模型：鉴权请求/响应、JD 导入请求、LLM 输出强 Schema。"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---- 鉴权（§7.1）----
class RegisterRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenUser(BaseModel):
    username: str
    role: str


class TokenResponse(BaseModel):
    token: str
    user: TokenUser


# ---- JD 粘贴导入（§7.2）----
class JdImportRequest(BaseModel):
    jd_text: str = Field(min_length=1)
    company: Optional[str] = None


# ---- LLM#1 抽取输出强 Schema（§8.2 工序③）----
class ExtractItem(BaseModel):
    name: str
    category: Literal["hard_skill", "soft_skill", "experience", "qualification"]
    required_level: int = Field(ge=1, le=5)
    importance: Literal["required", "preferred", "plus"]
    evidence: list[str]
    years: Optional[float] = None


class ExtractResult(BaseModel):
    job_title: str
    items: list[ExtractItem]


# ---- LLM#2 消歧输出 Schema（§8.2 工序④）----
class MergePair(BaseModel):
    # from 的标准名并入 to
    from_: str = Field(alias="from")
    to: str

    model_config = {"populate_by_name": True}


class DisambiguateResult(BaseModel):
    merges: list[MergePair]


# ---- LLM#3 等级裁决输出 Schema（§8.2 工序⑤）----
class AggregateLevelResult(BaseModel):
    level: int = Field(ge=1, le=5)
    reason: str


# ---- LLM#4 面试官观察输出 Schema（SSOT §11.3/§11.4，D-22）----
# answer_state 11 态白名单（§11.4）；观察维度（§11.3 证据判定输入——
# required_points_covered/source_span_available 属 Phase 5 证据链强化，本期保留维度不消费）
ANSWER_STATES = Literal[
    "VALID_EVIDENCE", "NEED_CLARIFICATION", "OFF_TOPIC", "NO_RECALL", "DECLINED",
    "PROCESS_CHALLENGE", "CONDUCT_EVENT", "TECHNICAL_OR_ACCESS_BARRIER",
    "PROMPT_INJECTION", "MODEL_UNCERTAIN", "ITEM_INVALID",
]


class ObservationDims(BaseModel):
    relevance: bool = Field(description="与测量目标相关")
    specificity: int = Field(ge=0, le=3)
    attribution: bool = Field(description="有可归因事实（项目/数据/角色）")
    required_points_covered: Optional[bool] = None
    source_span_available: Optional[bool] = None
    contradiction_detected: Optional[bool] = None
    uncertainty: Optional[bool] = None


class InterviewObservation(BaseModel):
    answer_state: ANSWER_STATES
    observation: ObservationDims
    reply_suggestion: Optional[str] = None    # 可选话术建议，裁决层可弃用
    reason: str = ""
    # score_live 属观察层输出（REF-1.3——LLM 直产 1-5 分仅导航用途）
    score_live: Optional[int] = Field(None, ge=1, le=5)
    score_live_reason: Optional[str] = None
