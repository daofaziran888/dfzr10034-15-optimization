"""治理评分领域服务：多维度治理健康评分、改进跟踪和整改闭环。

接收血缘追踪、标签传播、变更捕获等各上游模块的数据作为评分维度。
"""
from __future__ import annotations

import time as _time
from typing import Any

from app.services.base import BaseModuleService
from app.services.tag_registry import TagRegistryService, asset_identity
from app.store import store

tag_registry_service = TagRegistryService()


class GovernScoreService(BaseModuleService):
    MODULE = "govern_score"
    ENTITY = "评分任务"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["任务编号", "评估对象", "评分维度", "当前分数", "改进基线", "评估周期", "预警级别", "整改状态"]
    REQUIRED_FIELDS = ["任务编号", "评估对象", "评分维度"]
    STATUS_ORDER = ["待评估", "评估中", "已出分", "整改中"]
    ACTION_RULES = {"发起评估": "评估中", "确认评分": "已出分", "指派整改": "整改中"}
    NEGATIVE_ACTIONS = ["指派整改"]

    SCORE_DIMENSIONS = {
        "元数据完备性": {"base": 100, "field": "metadata", "weight": 0.15},
        "质量监控覆盖": {"base": 80, "field": "quality", "weight": 0.20},
        "分级标签准确度": {"base": 70, "field": "classification", "weight": 0.15},
        "血缘完备性": {"base": 60, "field": "lineage", "weight": 0.20},
        "标签覆盖": {"base": 50, "field": "tag", "weight": 0.10},
        "契约合规": {"base": 40, "field": "contract", "weight": 0.10},
        "负责人到位": {"base": 30, "field": "owner", "weight": 0.10},
    }

    def evaluate_asset(self, asset_code: str) -> dict[str, Any]:
        """对资产进行多维度治理评分（Pipeline 7 汇总输出）。"""
        dimensions = {}

        # 元数据完备性
        metadata = store.find_by_field("metadata_index", "所属资产", asset_code)
        meta_score = min(100, len(metadata) * 20)
        dimensions["元数据完备性"] = meta_score

        # 质量监控覆盖
        quality = store.find_by_field("quality_rule", "目标资产", asset_code)
        quality_score = min(100, len(quality) * 33)
        dimensions["质量监控覆盖"] = quality_score

        # 分级标签准确度
        classifications = [
            c for c in store.rows("classification")
            if str(c.get("目标字段", "")).startswith(f"{asset_code}.")
        ]
        class_score = min(100, len([c for c in classifications if c.get("status") == "已确认"]) * 25)
        dimensions["分级标签准确度"] = class_score

        # 血缘完备性
        lineage = [
            l for l in store.rows("lineage_track")
            if l.get("上游资产") == asset_code or l.get("下游资产") == asset_code
        ]
        lineage_score = min(100, len(lineage) * 25)
        dimensions["血缘完备性"] = lineage_score

        # 标签覆盖：按资产身份取覆盖并集，同一张表只算一次，不累加各标签计数。
        cov = tag_registry_service.asset_coverage(asset_code)
        covered_by = cov["tag_codes"]
        dimensions["标签覆盖"] = 100 if cov["covered"] else self.SCORE_DIMENSIONS["标签覆盖"]["base"]

        # 契约合规
        contracts = store.find_by_field("data_contract", "数据资产", asset_code)
        contract_score = min(100, len([c for c in contracts if c.get("status") == "已签署"]) * 50)
        dimensions["契约合规"] = contract_score

        # 负责人到位
        owners = store.find_by_field("owner_mgr", "目标资产", asset_code)
        owner_score = min(100, len([o for o in owners if o.get("status") == "已生效"]) * 50)
        dimensions["负责人到位"] = owner_score

        # 加权总分
        total = 0
        weight_sum = 0
        for dim, cfg in self.SCORE_DIMENSIONS.items():
            score = dimensions.get(dim, cfg["base"])
            total += score * cfg["weight"]
            weight_sum += cfg["weight"]
        overall = round(total / max(weight_sum, 0.01), 1)

        # 保存评分记录
        score_id = store.next_id(self.MODULE)
        score_entry = {
            "id": score_id,
            "任务编号": f"GOVE-{score_id:04d}",
            "评估对象": asset_code,
            "评分维度": "综合评估",
            "当前分数": str(overall),
            "改进基线": self._compute_baseline(dimensions, overall),
            "评估周期": "按需",
            "预警级别": self._severity_label(overall),
            "整改状态": "已出分",
            "status": "已出分",
            "pending": overall < 60,
            "abnormal": overall < 40,
            "dimensions": dimensions,
            "标签覆盖": dimensions["标签覆盖"],
            "covered_by": covered_by,
            "created_at": _time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        store.rows(self.MODULE).append(score_entry)

        self.emit_event("governance_scored", {
            "score_id": score_id,
            "asset_code": asset_code,
            "overall": overall,
            "dimensions": dimensions,
        })

        return {
            "score_id": score_id,
            "asset": asset_code,
            "overall": overall,
            "dimensions": dimensions,
            "标签覆盖": dimensions["标签覆盖"],
            "covered_by": covered_by,
            "pipeline": "lineage_track->impact_analysis->govern_score",
        }

    def recompute_after_tag_change(self, asset_codes: list[str] | None = None) -> dict[str, Any]:
        """标签覆盖变化后重算受影响资产的评分（评分汇总跟随并集更新）。

        ``asset_codes`` 为空时重算所有出现过标签覆盖的资产。
        """
        targets = {
            asset_identity(code) for code in (asset_codes or []) if asset_identity(code)
        }
        if not targets:
            targets = {
                row.get("资产编号", "")
                for row in store.rows("tag_coverage")
                if row.get("资产编号") and row.get("状态") == "生效"
            }
        results = [self.evaluate_asset(code) for code in sorted(targets)]
        return {
            "recomputed": len(results),
            "assets": [item["asset"] for item in results],
            "results": results,
        }

    recompute_scores_for_tags = recompute_after_tag_change

    def _compute_baseline(self, dims: dict[str, int], overall: float) -> str:
        """计算改进基线。"""
        weaknesses = [(d, s) for d, s in dims.items() if s < 60]
        if weaknesses:
            weakest = min(weaknesses, key=lambda x: x[1])
            return f"加强{weakest[0]}（当前{weakest[1]}分）"
        if overall < 80:
            return "各维度持续改进以达到优良水平"
        return "维持当前水平"

    def _severity_label(self, score: float) -> str:
        if score >= 80:
            return "正常"
        elif score >= 60:
            return "需关注"
        elif score >= 40:
            return "严重"
        return "危急"

    def get_scores_by_asset(self, asset_code: str) -> list[dict[str, Any]]:
        """获取资产的所有治理评分记录。"""
        return store.find_by_field(self.MODULE, "评估对象", asset_code)