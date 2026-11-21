"""通用接口契约；模块字段由领域服务持有，不再为每个模块复制一份模型类。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    action: str
    remark: str | None = None


class BatchAssociationPayload(BaseModel):
    """批量标签关联：逐条按资产身份归并，重复提交只算一次覆盖。"""

    tag_id: Any | None = None
    assets: list[str] = Field(default_factory=list)
    records: list[dict[str, Any]] = Field(default_factory=list)
    source: str = "批量关联"
    credential: str | None = None
    confirm: bool = True


class MergeTagsPayload(BaseModel):
    source_id: Any
    target_id: Any


class RevokeAssociationPayload(BaseModel):
    tag_id: Any | None = None
    asset_code: str | None = None
    source: str | None = None
    credential: str | None = None
    evidence_id: Any | None = None
