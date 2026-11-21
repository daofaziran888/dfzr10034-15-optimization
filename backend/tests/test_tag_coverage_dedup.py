"""标签覆盖去重回归：批量关联、标签合并、来源撤销与评分并集重算。

场景锚点（对应题干）：
- 金标覆盖商品甲、乙，银标覆盖乙、丙；乙处于两个标签交集。
- 合并前后分别以乙作一次「标签覆盖」维度评分，乙不能比甲多算一张表。
- 合并进行中旧银标又送来关联，评分人员撤销其中一个来源后乙仍有覆盖。
- 旧银标与丁关联后，能追出丁在哪一次确认后取得覆盖。
"""
from __future__ import annotations

import app.store as store_mod
from app.services.govern_score import GovernScoreService
from app.services.tag_registry import TagRegistryService


def _fresh():
    store_mod.store.reset()
    return TagRegistryService(), GovernScoreService()


def _new_tag(service: TagRegistryService, name: str) -> dict:
    return service.register_tag(name, "一级", "根", f"{name}说明", "admin")


class TestBatchCoverageDedup:

    def test_batch_associate_merges_by_asset_identity(self):
        tags, _ = _fresh()
        gold = _new_tag(tags, "金标")
        result = tags.batch_associate(
            gold["id"], ["商品甲", "商品甲", " 商品乙 "], source="金标导入"
        )
        assert result["ok"] is True
        assert result["submitted"] == 3
        assert result["created"] == 2
        assert result["duplicates"] == 1
        assert result["coverage_assets"] == ["商品乙", "商品甲"]
        assert tags.get_coverage_assets(gold["id"]) == ["商品乙", "商品甲"]

    def test_repeat_submit_counts_once(self):
        tags, _ = _fresh()
        gold = _new_tag(tags, "金标")
        for _ in range(3):
            tags.associate_with_asset(gold["id"], "商品甲", source="金标导入")
        assert tags.coverage_count(gold["id"]) == 1
        assert int(tags.get_entry(gold["id"])["关联资产数"]) == 1

    def test_different_sources_keep_both_evidences(self):
        tags, _ = _fresh()
        gold = _new_tag(tags, "金标")
        tags.associate_with_asset(gold["id"], "商品甲", source="来源A")
        result = tags.associate_with_asset(gold["id"], "商品甲", source="来源B")
        assert result["duplicate"] is False
        detail = tags.get_coverage_detail(gold["id"])
        assert detail["覆盖资产数"] == 1
        row = detail["明细"][0]
        assert row["确认凭据数"] == 2
        assert row["来源"] == ["来源A", "来源B"]

    def test_asset_identity_is_trimmed_and_stable(self):
        tags, _ = _fresh()
        gold = _new_tag(tags, "金标")
        tags.batch_associate(gold["id"], ["商品甲", " 商品甲 "], source="导入")
        assert tags.get_coverage_assets(gold["id"]) == ["商品甲"]
        assert len(store_mod.store.rows("tag_coverage")) == 1


class TestMergeCoverageUnion:

    def test_merge_uses_union_not_sum(self):
        tags, _ = _fresh()
        gold = _new_tag(tags, "金标")
        silver = _new_tag(tags, "银标")
        tags.batch_associate(gold["id"], ["商品甲", "商品乙"], source="金标导入")
        tags.batch_associate(silver["id"], ["商品乙", "商品丙"], source="银标导入")
        assert tags.coverage_count(gold["id"]) == 2
        assert tags.coverage_count(silver["id"]) == 2

        result = tags.merge_tags(gold["id"], silver["id"])

        assert result["coverage_assets"] == ["商品丙", "商品乙", "商品甲"]
        assert result["coverage_count"] == 3
        # 交集资产乙在合并后只有一条覆盖，不能比甲多算一张表。
        detail = tags.get_coverage_detail(silver["id"])
        assert detail["覆盖资产数"] == 3
        yi = next(row for row in detail["明细"] if row["资产编号"] == "商品乙")
        assert yi["确认凭据数"] == 2
        assert set(yi["来源"]) == {"金标导入", "银标导入"}
        active = [
            row for row in store_mod.store.rows("tag_coverage")
            if row["状态"] != "已并入"
        ]
        assert len(active) == 3
        # 源标签保留数值口径之外的历史：关联资产数按并集刷新。
        assert int(tags.get_entry(silver["id"])["关联资产数"]) == 3
        assert tags.get_entry(gold["id"])["合并至标签ID"] == silver["id"]
        assert "TAG-0002" in tags.get_entry(silver["id"])["历史标签编号"]

    def test_merge_count_repeat_is_idempotent(self):
        tags, _ = _fresh()
        gold = _new_tag(tags, "金标")
        silver = _new_tag(tags, "银标")
        tags.batch_associate(gold["id"], ["商品甲", "商品乙"], source="金标导入")
        tags.batch_associate(silver["id"], ["商品乙", "商品丙"], source="银标导入")
        tags.merge_tags(gold["id"], silver["id"])
        again = tags.merge_tags(gold["id"], silver["id"])
        assert again["ok"] is True
        assert again["coverage_count"] == 3
        assert tags.coverage_count(silver["id"]) == 3


class TestLegacyTagCode:

    def test_association_accepts_historical_tag_code(self):
        tags, _ = _fresh()
        gold = _new_tag(tags, "金标")
        silver = _new_tag(tags, "银标")
        tags.batch_associate(gold["id"], ["商品甲"], source="金标导入")
        tags.merge_tags(gold["id"], silver["id"])

        # 旧编号与旧名称都能落到合并后的目标标签。
        by_code = tags.associate_with_asset("TAG-0002", "商品乙", source="旧金标")
        by_name = tags.associate_with_asset("金标", "商品丙", source="旧金标")
        assert by_code["ok"] and by_name["ok"]
        assert by_code["tag"]["id"] == silver["id"]
        assert by_name["tag"]["id"] == silver["id"]
        assert by_code["evidence"]["原始标签编号"] == "TAG-0002"
        assert tags.get_coverage_assets(silver["id"]) == ["商品丙", "商品乙", "商品甲"]

    def test_confirm_association_accepts_historical_tag_code(self):
        tags, _ = _fresh()
        gold = _new_tag(tags, "金标")
        silver = _new_tag(tags, "银标")
        tags.associate_with_asset(gold["id"], "商品甲", source="旧金标", confirm=False)
        tags.merge_tags(gold["id"], silver["id"])

        result = tags.confirm_association("TAG-0002", asset_code="商品甲", source="旧金标")
        assert result["ok"] is True
        assert result["confirmed_count"] == 1
        assert result["confirmed"][0]["关联状态"] == "已确认"
        assert tags.get_coverage_assets(silver["id"]) == ["商品甲"]


class TestRevokeAndTrace:

    def _merged(self):
        tags, scores = _fresh()
        gold = _new_tag(tags, "金标")
        silver = _new_tag(tags, "银标")
        tags.batch_associate(gold["id"], ["商品甲", "商品乙"], source="金标导入")
        tags.batch_associate(silver["id"], ["商品乙", "商品丙"], source="银标导入")
        tags.merge_tags(gold["id"], silver["id"])
        return tags, scores, gold, silver

    def test_late_old_tag_associations_keep_both_evidences(self):
        tags, _, gold, silver = self._merged()
        first = tags.associate_with_asset("TAG-0002", "商品乙", source="旧银标-系统A")
        second = tags.associate_with_asset("银标", "商品乙", source="旧银标-系统B")
        assert first["ok"] and second["ok"]
        # 同一来源重复提交仍然只保留一份凭据，覆盖保持一次。
        repeat = tags.associate_with_asset("TAG-0002", "商品乙", source="旧银标-系统A")
        assert repeat["duplicate"] is True
        yi = next(
            row for row in tags.get_coverage_detail(silver["id"])["明细"]
            if row["资产编号"] == "商品乙"
        )
        assert yi["确认凭据数"] == 4
        assert tags.coverage_count(silver["id"]) == 3

    def test_revoke_one_source_keeps_other_evidence(self):
        tags, _, gold, silver = self._merged()
        tags.associate_with_asset("TAG-0002", "商品乙", source="旧银标-系统A")
        tags.associate_with_asset("银标", "商品乙", source="旧银标-系统B")

        result = tags.revoke_association(
            "TAG-0002", asset_code="商品乙", source="旧银标-系统A"
        )
        assert result["ok"] is True
        assert result["revoked_count"] == 1
        assert tags.asset_coverage("商品乙")["covered"] is True
        yi = next(
            row for row in tags.get_coverage_detail(silver["id"])["明细"]
            if row["资产编号"] == "商品乙"
        )
        assert yi["确认凭据数"] == 3
        assert "旧银标-系统A" not in yi["来源"]
        assert any(
            item["来源"] == "旧银标-系统A" and item["关联状态"] == "已撤销"
            for item in yi["凭据"]
        )

    def test_revoke_all_sources_deactivates_coverage_only(self):
        tags, _, gold, silver = self._merged()
        result = tags.revoke_association("银标", asset_code="商品丙", source="银标导入")
        assert result["ok"] is True
        assert tags.asset_coverage("商品丙")["covered"] is False
        assert tags.get_coverage_assets(silver["id"]) == ["商品乙", "商品甲"]
        # 乙仍由金标与银标两条凭据支撑。
        assert tags.asset_coverage("商品乙")["covered"] is True

    def test_trace_where_asset_gained_coverage(self):
        tags, _, gold, silver = self._merged()
        tags.associate_with_asset("TAG-0002", "商品丁", source="旧银标-系统A")
        traces = tags.find_coverage_confirmation("商品丁")
        assert len(traces) == 1
        trace = traces[0]
        assert trace["标签编号"] == silver["标签编号"]
        assert trace["来源"] == "旧银标-系统A"
        assert trace["确认凭据编号"].startswith("EVID-")
        assert trace["确认时间"]
        assert trace["覆盖状态"] == "生效"


class TestScoreUsesCoverageUnion:

    def test_score_before_merge_counts_yi_once(self):
        tags, scores = _fresh()
        gold = _new_tag(tags, "金标")
        silver = _new_tag(tags, "银标")
        tags.batch_associate(gold["id"], ["商品甲", "商品乙"], source="金标导入")
        tags.batch_associate(silver["id"], ["商品乙", "商品丙"], source="银标导入")

        yi = scores.evaluate_asset("商品乙")
        jia = scores.evaluate_asset("商品甲")
        assert yi["标签覆盖"] == 100
        assert jia["标签覆盖"] == 100
        assert set(yi["covered_by"]) == {gold["标签编号"], silver["标签编号"]}

        # 同一个「标签覆盖」维度下，交集资产乙不比甲多算。
        yi_dim = next(
            row for row in store_mod.store.rows("govern_score")
            if row["评估对象"] == "商品乙" and row["评分维度"] == "综合评估"
        )
        jia_dim = next(
            row for row in store_mod.store.rows("govern_score")
            if row["评估对象"] == "商品甲" and row["评分维度"] == "综合评估"
        )
        assert yi_dim["dimensions"]["标签覆盖"] == jia_dim["dimensions"]["标签覆盖"]
        assert yi_dim["标签覆盖"] == jia_dim["标签覆盖"]

    def test_score_after_merge_and_recompute(self):
        tags, scores = _fresh()
        gold = _new_tag(tags, "金标")
        silver = _new_tag(tags, "银标")
        tags.batch_associate(gold["id"], ["商品甲", "商品乙"], source="金标导入")
        tags.batch_associate(silver["id"], ["商品乙", "商品丙"], source="银标导入")
        tags.merge_tags(gold["id"], silver["id"])
        tags.associate_with_asset("TAG-0002", "商品丁", source="旧银标-系统A")

        result = scores.recompute_after_tag_change()
        assert result["recomputed"] == 4
        assert set(result["assets"]) == {"商品甲", "商品乙", "商品丙", "商品丁"}
        for item in result["results"]:
            assert item["标签覆盖"] == 100
            assert item["covered_by"] == [silver["标签编号"]]

        detail = tags.get_coverage_detail(silver["id"])
        assert detail["覆盖资产集合"] == ["商品丁", "商品丙", "商品乙", "商品甲"]
        assert detail["覆盖资产数"] == 4

    def test_uncovered_asset_keeps_base_score(self):
        tags, scores = _fresh()
        gold = _new_tag(tags, "金标")
        tags.batch_associate(gold["id"], ["商品甲"], source="金标导入")
        result = scores.evaluate_asset("商品戊")
        assert result["标签覆盖"] == 50
        assert result["covered_by"] == []


class TestCoverageDetailChain:

    def test_detail_exposes_evidence_chain(self):
        tags, _ = _fresh()
        gold = _new_tag(tags, "金标")
        tags.associate_with_asset(gold["id"], "商品甲", source="来源A")
        tags.associate_with_asset(gold["id"], "商品甲", source="来源B")

        detail = tags.get_coverage_detail(gold["标签编号"])
        assert detail["覆盖资产集合"] == ["商品甲"]
        row = detail["明细"][0]
        assert row["凭据数"] == 2
        assert {item["来源"] for item in row["凭据"]} == {"来源A", "来源B"}
        assert row["首次确认凭据"].startswith("EVID-")
        assert row["首次确认时间"]
