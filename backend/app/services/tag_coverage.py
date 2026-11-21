"""标签覆盖领域服务：按资产身份归并的标签覆盖集合与覆盖明细查询。

覆盖是「标签 + 资产身份」的唯一记录，重复关联和标签合并都只做并集，不做计数累加。
"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.tag_registry import TagRegistryService

TAG_REGISTRY = TagRegistryService()


class TagCoverageService(BaseModuleService):
    MODULE = "tag_coverage"
    ENTITY = "标签覆盖"
    OPERATION_TERM = "归并"
    LIST_FIELDS = [
        "覆盖编号", "标签编号", "标签名称", "资产编号", "状态",
        "首次确认时间", "最近确认时间", "确认凭据数", "来源集合",
    ]
    REQUIRED_FIELDS = ["标签编号", "资产编号"]
    STATUS_ORDER = ["待生效", "生效", "已失效", "已并入"]
    ACTION_RULES = {}
    NEGATIVE_ACTIONS = []

    def get_coverage_detail(self, tag_ref: Any) -> dict[str, Any]:
        return TAG_REGISTRY.get_coverage_detail(tag_ref)

    def get_coverage_assets(self, tag_ref: Any) -> list[str]:
        return TAG_REGISTRY.get_coverage_assets(tag_ref)

    def coverage_union(self, tag_refs: list[Any]) -> list[str]:
        return TAG_REGISTRY.coverage_union(tag_refs)
