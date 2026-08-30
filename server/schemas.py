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
