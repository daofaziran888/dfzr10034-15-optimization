"""关联凭据领域服务：每一次标签关联提交的来源留痕与确认/撤销。

凭据是覆盖的支撑材料：同一来源重复提交只保留一份凭据，不同来源各自保留；
撤销一个来源后，若仍有其他已确认凭据，覆盖保持生效。
"""
from __future__ import annotations

import time as _time
from typing import Any

from app.services.base import BaseModuleService
from app.services.tag_registry import TagRegistryService
from app.store import store

TAG_REGISTRY = TagRegistryService()


class TagAssociationService(BaseModuleService):
    MODULE = "tag_association"
    ENTITY = "关联凭据"
    OPERATION_TERM = "确认"
    LIST_FIELDS = [
        "凭据编号", "标签编号", "标签名称", "资产编号", "来源",
        "来源凭据", "关联状态", "确认时间",
    ]
    REQUIRED_FIELDS = ["标签编号", "资产编号"]
    STATUS_ORDER = ["待确认", "已确认", "已撤销"]
    ACTION_RULES = {"确认关联": "已确认", "撤销关联": "已撤销"}
    NEGATIVE_ACTIONS = ["撤销关联"]

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        evidence = self.get_entry(entry_id)
        if evidence is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        if action == "确认关联":
            result = TAG_REGISTRY.confirm_association(evidence_id=evidence["id"])
        elif action == "撤销关联":
            result = TAG_REGISTRY.revoke_association(evidence_id=evidence["id"])
        else:
            return None, f"动作「{action}」不属于{self.MODULE}可执行范围"
        if not result.get("ok"):
            return None, result.get("error", f"{self.ENTITY}动作未生效")
        evidence["updated_at"] = _time.strftime("%Y-%m-%d %H:%M:%S")
        return evidence, f"{self.ENTITY}已{action.replace('关联', '')}"

    def association_assets(self, tag_ref: Any) -> list[str]:
        """标签下已确认凭据覆盖的资产身份集合。"""
        return TAG_REGISTRY.get_coverage_assets(tag_ref)

    def evidence_of_asset(self, asset_code: str) -> list[dict[str, Any]]:
        identity = str(asset_code or "").strip()
        return [
            row for row in store.rows(self.MODULE)
            if row.get("资产编号") == identity
        ]
