"""标签体系领域服务：业务标签分类体系、层级结构和标签传播规则。

Pipeline 9: Tag registration → asset association → tag propagation

标签关联采用「凭据 + 覆盖」两层模型：

* ``tag_association`` 保存每一次关联提交（来源、来源凭据、确认状态）。
  同一来源的重复提交只保留一份凭据；不同来源支持同一张表时各自保留凭据。
* ``tag_coverage`` 按「标签 + 资产身份」归并，同一张表在一个标签下只有一条
  有效覆盖。重复提交、两个标签合并都不会让覆盖数膨胀。

标签合并时源标签的凭据和覆盖会迁移到目标标签，源标签保留为历史别名；
之后再用旧标签编号或旧标签名称提交关联，仍会落到合并后的目标标签上。
"""
from __future__ import annotations

import time as _time
from typing import Any, Iterable

from app.services.base import BaseModuleService
from app.store import store

TAG_ASSOCIATION_MODULE = "tag_association"
TAG_COVERAGE_MODULE = "tag_coverage"

EVIDENCE_PENDING = "待确认"
EVIDENCE_CONFIRMED = "已确认"
EVIDENCE_REVOKED = "已撤销"

COVERAGE_PENDING = "待生效"
COVERAGE_ACTIVE = "生效"
COVERAGE_INACTIVE = "已失效"
COVERAGE_MERGED = "已并入"

ACTIVE_COVERAGE_STATUSES = (COVERAGE_ACTIVE,)


def _now() -> str:
    return _time.strftime("%Y-%m-%d %H:%M:%S")


def asset_identity(asset_code: Any) -> str:
    """资产身份：去掉首尾空白后的稳定标识，用于跨来源归并同一张表。"""
    return str(asset_code or "").strip()


def normalize_tag_code(code: Any) -> str:
    """标签编号归一化：大小写、``_``/``-`` 分隔和重复分隔符都不影响匹配。"""
    text = str(code or "").strip().upper().replace("_", "-")
    while "--" in text:
        text = text.replace("--", "-")
    return text


def _code_digits(code: Any) -> int | None:
    text = normalize_tag_code(code)
    tail = ""
    for char in reversed(text):
        if char.isdigit():
            tail = char + tail
        else:
            break
    return int(tail) if tail else None


def _evidence_rows() -> list[dict[str, Any]]:
    return store.rows(TAG_ASSOCIATION_MODULE)


def _coverage_rows() -> list[dict[str, Any]]:
    return store.rows(TAG_COVERAGE_MODULE)


def _raw_find_tag(reference: Any) -> dict[str, Any] | None:
    """按内部 ID、标签编号、标签名称或历史标签编号找标签，不跟随合并。"""
    if reference is None:
        return None
    if isinstance(reference, dict):
        reference = (
            reference.get("id")
            or reference.get("标签ID")
            or reference.get("tag_id")
            or reference.get("标签编号")
            or reference.get("标签名称")
        )
    if reference is None:
        return None

    rows = store.rows("tag_registry")
    if isinstance(reference, int) or (
        isinstance(reference, str) and reference.strip().isdigit()
    ):
        tag_id = int(reference)
        for row in rows:
            if int(row.get("id", 0)) == tag_id:
                return row

    text = str(reference).strip()
    normalized = normalize_tag_code(text)
    for row in rows:
        if normalize_tag_code(row.get("标签编号")) == normalized:
            return row
    for row in rows:
        if str(row.get("标签名称", "")).strip() == text:
            return row
    for row in rows:
        aliases = [normalize_tag_code(item) for item in row.get("历史标签编号") or []]
        if normalized in aliases:
            return row

    # 历史凭据里出现过的旧编号同样能追溯回标签。
    for evidence in _evidence_rows():
        if normalize_tag_code(evidence.get("原始标签编号")) == normalized:
            candidate = _raw_find_tag(evidence.get("标签ID"))
            if candidate is not None:
                return candidate
    return None


def resolve_tag(reference: Any) -> dict[str, Any] | None:
    """解析标签引用，并沿合并链落到最终目标标签（兼容历史标签编号）。"""
    tag = _raw_find_tag(reference)
    visited: set[int] = set()
    while tag is not None:
        tag_id = int(tag.get("id", 0))
        if tag_id in visited:
            return tag
        visited.add(tag_id)
        if not tag.get("合并去向") and not tag.get("合并至标签ID"):
            return tag
        next_tag = None
        if tag.get("合并至标签ID"):
            next_tag = _raw_find_tag(tag.get("合并至标签ID"))
        if next_tag is None and tag.get("合并去向"):
            next_tag = _raw_find_tag(tag.get("合并去向"))
        if next_tag is None:
            return tag
        tag = next_tag
    return None


def resolve_evidence(reference: Any) -> dict[str, Any] | None:
    """按内部 ID 或凭据编号解析一次关联凭据。"""
    if reference is None:
        return None
    rows = _evidence_rows()
    if isinstance(reference, dict):
        reference = (
            reference.get("id")
            or reference.get("凭据编号")
            or reference.get("evidence_id")
        )
        if reference is None:
            return None
    if isinstance(reference, int) or (
        isinstance(reference, str) and reference.strip().isdigit()
    ):
        evidence_id = int(reference)
        for row in rows:
            if int(row.get("id", 0)) == evidence_id:
                return row
    text = str(reference).strip().upper()
    for row in rows:
        if str(row.get("凭据编号", "")).upper() == text:
            return row
    return None


class TagRegistryService(BaseModuleService):
    MODULE = "tag_registry"
    ENTITY = "业务标签"
    OPERATION_TERM = "关联"
    LIST_FIELDS = ["标签编号", "标签名称", "标签层级", "父标签", "关联资产数", "标签说明", "创建人", "最后更新"]
    REQUIRED_FIELDS = ["标签编号", "标签名称", "标签层级"]
    STATUS_ORDER = ["草稿", "已发布", "已合并", "已废弃"]
    ACTION_RULES = {"发布标签": "已发布", "合并标签": "已合并", "废弃标签": "已废弃"}
    NEGATIVE_ACTIONS = ["废弃标签"]

    # ── 标签注册与查询 ────────────────────────────────────────

    def register_tag(self, name: str, level: str, parent: str, description: str, creator: str) -> dict[str, Any]:
        """注册业务标签（Pipeline 9 入口）。"""
        tag_id = store.next_id(self.MODULE)
        tag = {
            "id": tag_id,
            "标签编号": f"TAG-{tag_id:04d}",
            "标签名称": name,
            "标签层级": level,
            "父标签": parent,
            "关联资产数": "0",
            "标签说明": description,
            "创建人": creator,
            "最后更新": _now(),
            "status": "已发布",
            "pending": False,
            "abnormal": False,
            "历史标签编号": [],
            "created_at": _now(),
        }
        store.rows(self.MODULE).append(tag)
        return tag

    def get_tags_by_level(self, level: str) -> list[dict[str, Any]]:
        """按层级获取标签。"""
        return store.find_by_field(self.MODULE, "标签层级", level)

    def get_tags_by_asset(self, asset_code: str) -> list[dict[str, Any]]:
        """获取资产关联的所有标签（按覆盖归并，不重复计数）。"""
        identity = asset_identity(asset_code)
        tags: list[dict[str, Any]] = []
        seen: set[int] = set()
        for coverage in _coverage_rows():
            if coverage.get("资产编号") != identity:
                continue
            if coverage.get("状态") not in ACTIVE_COVERAGE_STATUSES:
                continue
            tag = self.get_entry(int(coverage.get("标签ID", 0)))
            if tag is None or int(tag["id"]) in seen:
                continue
            if tag.get("status") == "已废弃":
                continue
            seen.add(int(tag["id"]))
            tags.append(tag)
        # 兼容历史数据：标签上直接以文本保存的资产清单。
        for tag in store.rows(self.MODULE):
            legacy = str(tag.get("关联资产列表") or "")
            if identity and identity in legacy and int(tag["id"]) not in seen:
                seen.add(int(tag["id"]))
                tags.append(tag)
        return tags

    # ── 关联凭据与覆盖 ────────────────────────────────────────

    def associate_with_asset(
        self,
        tag_id: Any,
        asset_code: str,
        *,
        source: str = "手工关联",
        credential: str | None = None,
        confirm: bool = True,
    ) -> dict[str, Any]:
        """将标签关联到资产（Pipeline 9 核心方法）。

        同一来源、同一凭据重复提交只保留一份凭据；覆盖按资产身份归并，
        重复提交不会让关联资产数增加。
        """
        result = self._record_association(
            tag_id, asset_code,
            source=source, credential=credential, confirm=confirm,
        )
        if not result.get("ok"):
            return result

        canonical = result["tag"]
        propagated = self._propagate_tags(asset_code, canonical)

        self.emit_event("tag_associated", {
            "tag_id": canonical["id"],
            "tag_code": canonical["标签编号"],
            "tag_name": canonical["标签名称"],
            "asset_code": asset_identity(asset_code),
            "source": source,
            "duplicate": result["duplicate"],
            "propagated_count": len(propagated),
        })

        return {
            "ok": True,
            "association": result["evidence"],
            "evidence": result["evidence"],
            "tag": canonical,
            "coverage": result["coverage"],
            "coverage_count": self.coverage_count(canonical),
            "duplicate": result["duplicate"],
            "propagated_to": propagated,
            "pipeline": "tag_registry->asset_registry->lineage_track",
        }

    def batch_associate(
        self,
        tag_id: Any = None,
        asset_codes: Iterable[str] | None = None,
        *,
        records: Iterable[dict[str, Any]] | None = None,
        source: str = "批量关联",
        credential: str | None = None,
        confirm: bool = True,
    ) -> dict[str, Any]:
        """批量提交标签关联，逐条按资产身份归并出覆盖集合。

        支持两种入参：

        * ``batch_associate(records=[{"标签": ..., "资产": ..., "来源": ...}, ...])``
        * ``batch_associate(tag_id, ["商品甲", "商品乙"], source="csv导入")``

        同一批次里重复出现的同一张表只算一次覆盖；不同来源各自保留凭据。
        """
        if records is None and isinstance(tag_id, (list, tuple)) and tag_id \
                and isinstance(tag_id[0], dict):
            records = list(tag_id)
            tag_id = None
        if records is None:
            records = [
                {"标签": tag_id, "资产": asset}
                for asset in (asset_codes or [])
            ]

        results: list[dict[str, Any]] = []
        for record in records:
            if isinstance(record, str):
                record = {"标签": tag_id, "资产": record}
            tag_ref = (
                record.get("标签") or record.get("标签编号") or record.get("标签ID")
                or record.get("tag") or record.get("tag_id") or record.get("tag_code")
                or tag_id
            )
            asset = (
                record.get("资产") or record.get("资产编号") or record.get("表")
                or record.get("asset") or record.get("asset_code")
            )
            entry_source = record.get("来源") or record.get("source") or source
            entry_credential = (
                record.get("来源凭据") or record.get("凭据") or record.get("credential")
                or credential
            )
            entry_confirm = record.get("确认", record.get("confirm", confirm))
            result = self._record_association(
                tag_ref, asset,
                source=entry_source, credential=entry_credential,
                confirm=bool(entry_confirm),
            )
            results.append(result)

        accepted = [item for item in results if item.get("ok")]
        created = [item for item in accepted if not item.get("duplicate")]
        duplicates = [item for item in accepted if item.get("duplicate")]
        covered = {
            item["coverage"]["资产编号"]
            for item in accepted
            if item.get("coverage")
        }
        canonical = accepted[0]["tag"] if accepted else None
        return {
            "ok": all(item.get("ok") for item in results) if results else False,
            "results": results,
            "submitted": len(results),
            "accepted": len(accepted),
            "created": len(created),
            "duplicates": len(duplicates),
            "coverage_assets": sorted(covered),
            "coverage_count": len(covered),
            "tag": canonical,
            "tag_coverage_assets": self.get_coverage_assets(canonical) if canonical else [],
            "tag_coverage_count": self.coverage_count(canonical) if canonical else 0,
            "pipeline": "tag_registry->tag_coverage",
        }

    associate_batch = batch_associate
    batch_associate_assets = batch_associate

    def _record_association(
        self,
        tag_ref: Any,
        asset_code: Any,
        *,
        source: str = "手工关联",
        credential: str | None = None,
        confirm: bool = True,
    ) -> dict[str, Any]:
        raw_tag = _raw_find_tag(tag_ref)
        canonical = resolve_tag(tag_ref)
        if canonical is None:
            return {"ok": False, "error": "标签不存在"}
        if raw_tag is not None and raw_tag.get("status") == "已废弃" \
                and not raw_tag.get("合并去向") and not raw_tag.get("合并至标签ID"):
            return {"ok": False, "error": "标签已废弃，不能继续关联"}

        identity = asset_identity(asset_code)
        if not identity:
            return {"ok": False, "error": "资产编号不能为空"}

        submitted_code = str(
            raw_tag.get("标签编号") if raw_tag else (canonical.get("标签编号") or "")
        )
        source = str(source or "手工关联").strip() or "手工关联"
        credential = str(
            credential
            or f"{source}:{normalize_tag_code(submitted_code)}:{identity}"
        ).strip()

        # 去重口径：同一标签下，同一资产身份 + 同一来源只保留一份凭据；
        # 不同来源支持同一张表时各自保留凭据，覆盖仍然只算一次。
        duplicate = False
        evidence = None
        for row in _evidence_rows():
            if (
                int(row.get("标签ID", 0)) == int(canonical["id"])
                and row.get("资产编号") == identity
                and row.get("来源") == source
            ):
                evidence = row
                duplicate = True
                break

        if evidence is None:
            evidence_id = store.next_id(TAG_ASSOCIATION_MODULE)
            evidence = {
                "id": evidence_id,
                "凭据编号": f"EVID-{evidence_id:04d}",
                "标签ID": int(canonical["id"]),
                "标签编号": canonical["标签编号"],
                "标签名称": canonical["标签名称"],
                "原始标签编号": submitted_code,
                "资产编号": identity,
                "来源": source,
                "来源凭据": credential,
                "关联状态": EVIDENCE_PENDING,
                "status": EVIDENCE_PENDING,
                "pending": True,
                "abnormal": False,
                "提交时间": _now(),
                "确认时间": "",
                "撤销时间": "",
                "覆盖编号": "",
                "合并去向": "",
            }
            _evidence_rows().append(evidence)
        else:
            evidence["原始标签编号"] = submitted_code
            evidence["标签编号"] = canonical["标签编号"]
            evidence["标签名称"] = canonical["标签名称"]

        coverage = self._ensure_coverage(canonical, identity)
        evidence["覆盖编号"] = coverage["覆盖编号"]

        if evidence.get("关联状态") == EVIDENCE_REVOKED and confirm:
            # 重新提交即重新认可该来源，保留原凭据编号便于审计。
            evidence["关联状态"] = EVIDENCE_PENDING
            evidence["撤销时间"] = ""

        if confirm:
            self._confirm_evidence(evidence, coverage)

        self._recompute_coverage(coverage)
        self._refresh_tag_count(canonical)

        return {
            "ok": True,
            "tag": canonical,
            "evidence": evidence,
            "coverage": coverage,
            "duplicate": duplicate,
            "submitted_tag_code": submitted_code,
        }

    def _ensure_coverage(self, tag: dict[str, Any], identity: str) -> dict[str, Any]:
        for coverage in _coverage_rows():
            if (
                int(coverage.get("标签ID", 0)) == int(tag["id"])
                and coverage.get("资产编号") == identity
                and coverage.get("状态") != COVERAGE_MERGED
            ):
                coverage["标签编号"] = tag["标签编号"]
                coverage["标签名称"] = tag["标签名称"]
                return coverage

        coverage_id = store.next_id(TAG_COVERAGE_MODULE)
        coverage = {
            "id": coverage_id,
            "覆盖编号": f"COVE-{coverage_id:04d}",
            "标签ID": int(tag["id"]),
            "标签编号": tag["标签编号"],
            "标签名称": tag["标签名称"],
            "资产编号": identity,
            "状态": COVERAGE_PENDING,
            "status": COVERAGE_PENDING,
            "pending": True,
            "abnormal": False,
            "首次确认时间": "",
            "首次确认凭据": "",
            "最近确认时间": "",
            "确认凭据数": 0,
            "凭据编号列表": "",
            "来源集合": "",
            "并入覆盖编号": "",
            "创建时间": _now(),
            "更新时间": _now(),
        }
        _coverage_rows().append(coverage)
        return coverage

    def _confirm_evidence(self, evidence: dict[str, Any], coverage: dict[str, Any] | None = None) -> dict[str, Any]:
        if evidence.get("关联状态") != EVIDENCE_CONFIRMED:
            first_confirmation = not evidence.get("确认时间")
            evidence["关联状态"] = EVIDENCE_CONFIRMED
            if first_confirmation:
                evidence["确认时间"] = _now()
            evidence["撤销时间"] = ""
            if coverage is not None:
                evidence["覆盖编号"] = coverage["覆盖编号"]
        evidence["status"] = EVIDENCE_CONFIRMED
        evidence["pending"] = False
        evidence["abnormal"] = False
        return evidence

    def _recompute_coverage(self, coverage: dict[str, Any]) -> None:
        if coverage.get("状态") == COVERAGE_MERGED:
            return
        evidences = [
            row for row in _evidence_rows()
            if row.get("覆盖编号") == coverage.get("覆盖编号")
        ]
        confirmed = [
            row for row in evidences
            if row.get("关联状态") == EVIDENCE_CONFIRMED
        ]
        coverage["更新时间"] = _now()
        if not confirmed:
            had_confirmation = bool(coverage.get("首次确认时间")) or bool(int(coverage.get("确认凭据数") or 0))
            coverage["状态"] = COVERAGE_INACTIVE if had_confirmation else COVERAGE_PENDING
            coverage["status"] = coverage["状态"]
            coverage["pending"] = coverage["状态"] == COVERAGE_PENDING
            coverage["确认凭据数"] = 0
            coverage["凭据编号列表"] = ""
            coverage["来源集合"] = ""
            return

        confirmed.sort(key=lambda row: (row.get("确认时间") or "", int(row.get("id", 0))))
        first = confirmed[0]
        coverage["状态"] = COVERAGE_ACTIVE
        coverage["status"] = COVERAGE_ACTIVE
        coverage["pending"] = False
        coverage["abnormal"] = False
        coverage["首次确认时间"] = first.get("确认时间") or coverage.get("首次确认时间") or ""
        coverage["首次确认凭据"] = first.get("凭据编号", "")
        coverage["最近确认时间"] = max(
            (row.get("确认时间") or "" for row in confirmed), default=""
        )
        coverage["确认凭据数"] = len(confirmed)
        coverage["凭据编号列表"] = ",".join(sorted(row.get("凭据编号", "") for row in confirmed))
        coverage["来源集合"] = ",".join(sorted({row.get("来源", "") for row in confirmed}))

    def _refresh_tag_count(self, tag: dict[str, Any]) -> None:
        all_coverages = [
            row for row in _coverage_rows()
            if int(row.get("标签ID", 0)) == int(tag["id"])
        ]
        if not all_coverages:
            # 纯历史标签没有覆盖数据，保留原有关联资产数口径。
            tag["最后更新"] = _now()
            return
        tag["关联资产数"] = str(sum(
            1 for row in all_coverages
            if row.get("状态") in ACTIVE_COVERAGE_STATUSES
        ))
        tag["最后更新"] = _now()

    def confirm_association(
        self,
        reference: Any = None,
        *,
        tag_ref: Any = None,
        asset_code: str | None = None,
        source: str | None = None,
        evidence_id: Any = None,
    ) -> dict[str, Any]:
        """确认关联凭据；标签引用兼容历史标签编号。"""
        candidates: list[dict[str, Any]] = []
        evidence = resolve_evidence(evidence_id) if evidence_id is not None else None
        if evidence is not None:
            candidates = [evidence]
        elif reference is not None and not isinstance(reference, (dict, int)) and str(reference).strip().upper().startswith("EVID"):
            evidence = resolve_evidence(reference)
            if evidence is not None:
                candidates = [evidence]
        if not candidates:
            tag = resolve_tag(tag_ref if tag_ref is not None else reference)
            if tag is None:
                return {"ok": False, "error": "标签不存在"}
            canonical_id = int(tag["id"])
            for row in _evidence_rows():
                if int(row.get("标签ID", 0)) != canonical_id:
                    continue
                if asset_code is not None and row.get("资产编号") != asset_identity(asset_code):
                    continue
                if source is not None and row.get("来源") != source:
                    continue
                if row.get("关联状态") == EVIDENCE_REVOKED:
                    continue
                candidates.append(row)

        if not candidates:
            return {"ok": False, "error": "没有可确认的关联凭据"}

        confirmed = []
        for row in candidates:
            tag = resolve_tag(row.get("标签ID"))
            if tag is None:
                continue
            coverage = self._ensure_coverage(tag, row.get("资产编号", ""))
            self._confirm_evidence(row, coverage)
            self._recompute_coverage(coverage)
            self._refresh_tag_count(tag)
            confirmed.append(row)

        return {
            "ok": True,
            "confirmed": confirmed,
            "confirmed_count": len(confirmed),
        }

    def revoke_association(
        self,
        reference: Any = None,
        *,
        tag_ref: Any = None,
        asset_code: str | None = None,
        source: str | None = None,
        credential: str | None = None,
        evidence_id: Any = None,
    ) -> dict[str, Any]:
        """撤销一个来源的关联凭据；其余来源仍可支撑覆盖。

        撤销后重新计算覆盖状态：只要还有已确认凭据，覆盖保持生效；
        最后一个来源被撤销时覆盖转为「已失效」。
        """
        candidates: list[dict[str, Any]] = []
        evidence = resolve_evidence(evidence_id) if evidence_id is not None else None
        if evidence is not None:
            candidates = [evidence]
        elif reference is not None and not isinstance(reference, (dict, int)) and str(reference).strip().upper().startswith("EVID"):
            evidence = resolve_evidence(reference)
            if evidence is not None:
                candidates = [evidence]
        if not candidates:
            tag = resolve_tag(tag_ref if tag_ref is not None else reference)
            if tag is None:
                return {"ok": False, "error": "标签不存在"}
            canonical_id = int(tag["id"])
            for row in _evidence_rows():
                if int(row.get("标签ID", 0)) != canonical_id:
                    continue
                if asset_code is not None and row.get("资产编号") != asset_identity(asset_code):
                    continue
                if source is not None and row.get("来源") != source:
                    continue
                if credential is not None and row.get("来源凭据") != credential:
                    continue
                if row.get("关联状态") != EVIDENCE_CONFIRMED:
                    continue
                candidates.append(row)

        if not candidates:
            return {"ok": False, "error": "没有可撤销的已确认关联凭据"}

        revoked = []
        coverage_ids: set[str] = set()
        for row in candidates:
            row["关联状态"] = EVIDENCE_REVOKED
            row["status"] = EVIDENCE_REVOKED
            row["pending"] = False
            row["撤销时间"] = _now()
            if row.get("覆盖编号"):
                coverage_ids.add(row["覆盖编号"])
            revoked.append(row)
            store.log_change(
                self.MODULE, int(row.get("标签ID", 0)), "撤销关联",
                before=EVIDENCE_CONFIRMED, after=EVIDENCE_REVOKED,
                source="tag_revoke", scope="tag_registry->tag_coverage",
            )

        affected_coverages = []
        for coverage in _coverage_rows():
            if coverage.get("覆盖编号") in coverage_ids:
                self._recompute_coverage(coverage)
                affected_coverages.append(coverage)
                tag = self.get_entry(int(coverage.get("标签ID", 0)))
                if tag is not None:
                    self._refresh_tag_count(tag)

        return {
            "ok": True,
            "revoked": revoked,
            "revoked_count": len(revoked),
            "coverages": affected_coverages,
            "source": source,
            "asset_code": asset_identity(asset_code) if asset_code is not None else None,
        }

    # ── 覆盖查询 ──────────────────────────────────────────────

    def coverage_count(self, tag_ref: Any) -> int:
        return len(self.get_coverage_assets(tag_ref))

    def get_coverage_assets(self, tag_ref: Any, *, include_pending: bool = False) -> list[str]:
        """标签覆盖的资产身份集合（去重后按资产编号排序）。

        已合并的源标签会解析到合并目标，因此合并前后都能得到并集口径。
        """
        tag = resolve_tag(tag_ref)
        if tag is None:
            return []
        allowed = (COVERAGE_ACTIVE, COVERAGE_PENDING) if include_pending else ACTIVE_COVERAGE_STATUSES
        assets = {
            row.get("资产编号", "")
            for row in _coverage_rows()
            if int(row.get("标签ID", 0)) == int(tag["id"])
            and row.get("状态") in allowed
        }
        return sorted(asset for asset in assets if asset)

    def coverage_union(self, tag_refs: Iterable[Any]) -> list[str]:
        """多个标签的覆盖并集：交集资产只出现一次。"""
        assets: set[str] = set()
        for tag_ref in tag_refs or []:
            assets.update(self.get_coverage_assets(tag_ref))
        return sorted(assets)

    def get_coverage_detail(self, tag_ref: Any) -> dict[str, Any]:
        """覆盖明细：每个资产一条覆盖，附上支撑它的全部来源凭据。"""
        tag = resolve_tag(tag_ref)
        if tag is None:
            return {"ok": False, "error": "标签不存在"}

        rows = []
        for coverage in _coverage_rows():
            if int(coverage.get("标签ID", 0)) != int(tag["id"]):
                continue
            if coverage.get("状态") == COVERAGE_MERGED:
                continue
            evidences = [
                row for row in _evidence_rows()
                if row.get("覆盖编号") == coverage.get("覆盖编号")
            ]
            evidences.sort(key=lambda row: (row.get("提交时间") or "", int(row.get("id", 0))))
            rows.append({
                "覆盖编号": coverage.get("覆盖编号"),
                "标签编号": coverage.get("标签编号"),
                "标签名称": coverage.get("标签名称"),
                "资产编号": coverage.get("资产编号"),
                "覆盖状态": coverage.get("状态"),
                "来源": [item for item in str(coverage.get("来源集合") or "").split(",") if item],
                "凭据": [
                    {
                        "凭据编号": item.get("凭据编号"),
                        "来源": item.get("来源"),
                        "来源凭据": item.get("来源凭据"),
                        "原始标签编号": item.get("原始标签编号"),
                        "关联状态": item.get("关联状态"),
                        "提交时间": item.get("提交时间"),
                        "确认时间": item.get("确认时间"),
                        "撤销时间": item.get("撤销时间"),
                    }
                    for item in evidences
                ],
                "凭据数": len(evidences),
                "确认凭据数": coverage.get("确认凭据数", 0),
                "首次确认时间": coverage.get("首次确认时间", ""),
                "首次确认凭据": coverage.get("首次确认凭据", ""),
                "最近确认时间": coverage.get("最近确认时间", ""),
            })

        rows.sort(key=lambda row: row["资产编号"])
        active_assets = [row["资产编号"] for row in rows if row["覆盖状态"] == COVERAGE_ACTIVE]
        return {
            "ok": True,
            "tag": tag,
            "标签编号": tag["标签编号"],
            "标签名称": tag["标签名称"],
            "覆盖资产集合": sorted(active_assets),
            "覆盖资产数": len(active_assets),
            "明细": rows,
        }

    get_coverage_details = get_coverage_detail

    def asset_coverage(self, asset_code: str) -> dict[str, Any]:
        """某张表当前的标签覆盖情况（同一标签只算一次）。"""
        identity = asset_identity(asset_code)
        tags: list[dict[str, Any]] = []
        coverages: list[dict[str, Any]] = []
        seen: set[int] = set()
        for coverage in _coverage_rows():
            if coverage.get("资产编号") != identity:
                continue
            if coverage.get("状态") != COVERAGE_ACTIVE:
                continue
            tag = resolve_tag(coverage.get("标签ID"))
            if tag is None or int(tag["id"]) in seen:
                continue
            seen.add(int(tag["id"]))
            tags.append(tag)
            coverages.append(coverage)
        return {
            "asset_code": identity,
            "covered": bool(tags),
            "coverage_count": 1 if tags else 0,
            "tags": tags,
            "tag_codes": [tag["标签编号"] for tag in tags],
            "coverages": coverages,
        }

    def find_coverage_confirmation(
        self, asset_code: str, tag_ref: Any = None
    ) -> list[dict[str, Any]]:
        """找出某张表在哪一次确认后取得标签覆盖。"""
        identity = asset_identity(asset_code)
        tag = resolve_tag(tag_ref) if tag_ref is not None else None
        results = []
        for coverage in _coverage_rows():
            if coverage.get("资产编号") != identity:
                continue
            if coverage.get("状态") != COVERAGE_ACTIVE:
                continue
            if tag is not None and int(coverage.get("标签ID", 0)) != int(tag["id"]):
                continue
            evidence = resolve_evidence(coverage.get("首次确认凭据"))
            results.append({
                "资产编号": identity,
                "标签编号": coverage.get("标签编号"),
                "覆盖编号": coverage.get("覆盖编号"),
                "确认凭据编号": coverage.get("首次确认凭据"),
                "确认时间": coverage.get("首次确认时间"),
                "来源": evidence.get("来源") if evidence else "",
                "覆盖状态": coverage.get("状态"),
            })
        return results

    # ── 传播 ──────────────────────────────────────────────────

    def _propagate_tags(self, asset_code: str, tag: dict[str, Any]) -> list[str]:
        """通过血缘关系将标签传播到下游资产（覆盖按资产身份去重）。"""
        identity = asset_identity(asset_code)
        propagated: list[str] = []
        direct = [
            row.get("下游资产", "")
            for row in store.rows("lineage_track")
            if asset_identity(row.get("上游资产")) == identity
        ]
        for downstream in direct:
            if downstream and downstream not in propagated:
                propagated.append(downstream)

        visited = {identity, *propagated}
        additional = []
        for downstream in list(propagated):
            for row in store.rows("lineage_track"):
                if asset_identity(row.get("上游资产")) != asset_identity(downstream):
                    continue
                next_asset = row.get("下游资产", "")
                if next_asset and next_asset not in visited:
                    additional.append(next_asset)
                    visited.add(next_asset)
        propagated.extend(additional)

        for downstream in propagated:
            self._record_association(
                tag, downstream,
                source="血缘传播",
                credential=f"血缘传播:{normalize_tag_code(tag.get('标签编号'))}:{asset_identity(downstream)}",
                confirm=True,
            )
            self._auto_associate_tag(tag, downstream)
        return propagated

    def _auto_associate_tag(self, tag: dict[str, Any], asset_code: str) -> None:
        """自动为资产关联标签（传播），只对已注册资产写入评分。"""
        asset = None
        for row in store.rows("asset_registry"):
            if row.get("资产编号") == asset_code:
                asset = row
                break

        if asset:
            score_id = store.next_id("govern_score")
            score = {
                "id": score_id,
                "任务编号": f"GOVE-TAG-{score_id:04d}",
                "评估对象": asset_code,
                "评分维度": "标签覆盖",
                "当前分数": "90",
                "改进基线": f"已通过血缘传播获得标签 {tag.get('标签名称','')}",
                "评估周期": "自动",
                "预警级别": "正常",
                "整改状态": "已出分",
                "status": "已出分",
                "pending": False,
                "abnormal": False,
                "propagated_tag_id": tag["id"],
                "created_at": _now(),
            }
            store.rows("govern_score").append(score)

    # ── 合并 ──────────────────────────────────────────────────

    def merge_tags(self, source_id: Any, target_id: Any) -> dict[str, Any]:
        """合并两个标签，覆盖按资产身份取并集而不是数值相加。"""
        source = resolve_tag(source_id)
        target = resolve_tag(target_id)
        if source is None or target is None:
            return {"ok": False, "error": "标签不存在"}
        if int(source["id"]) == int(target["id"]):
            assets = self.get_coverage_assets(target)
            return {
                "ok": True,
                "already_merged": True,
                "source": int(source["id"]),
                "target": int(target["id"]),
                "moved_evidence": 0,
                "关联资产数": len(assets),
                "coverage_assets": assets,
                "coverage_count": len(assets),
                "merged_coverages": [],
                "legacy_merge": False,
            }

        source_id_int = int(source["id"])
        target_id_int = int(target["id"])
        source_coverages = [
            row for row in _coverage_rows()
            if int(row.get("标签ID", 0)) == source_id_int
            and row.get("状态") != COVERAGE_MERGED
        ]
        target_coverages = [
            row for row in _coverage_rows()
            if int(row.get("标签ID", 0)) == target_id_int
            and row.get("状态") != COVERAGE_MERGED
        ]
        legacy_merge = not source_coverages and not target_coverages

        # 1. 凭据迁移到目标标签，但保留原始标签编号作为历史凭据。
        moved_evidence = 0
        for evidence in _evidence_rows():
            if int(evidence.get("标签ID", 0)) != source_id_int:
                continue
            evidence["标签ID"] = target_id_int
            evidence["标签编号"] = target["标签编号"]
            evidence["标签名称"] = target["标签名称"]
            evidence["合并去向"] = target["标签编号"]
            moved_evidence += 1

        # 2. 覆盖按资产身份归并，交集资产只保留一条覆盖。
        merged_coverages = []
        for coverage in source_coverages:
            identity = coverage.get("资产编号", "")
            existing = next(
                (
                    row for row in _coverage_rows()
                    if int(row.get("标签ID", 0)) == target_id_int
                    and row.get("资产编号") == identity
                    and row.get("状态") != COVERAGE_MERGED
                ),
                None,
            )
            if existing is None:
                coverage["标签ID"] = target_id_int
                coverage["标签编号"] = target["标签编号"]
                coverage["标签名称"] = target["标签名称"]
                for evidence in _evidence_rows():
                    if evidence.get("覆盖编号") == coverage.get("覆盖编号"):
                        evidence["标签ID"] = target_id_int
                        evidence["标签编号"] = target["标签编号"]
                        evidence["标签名称"] = target["标签名称"]
                self._recompute_coverage(coverage)
                merged_coverages.append(coverage)
            else:
                for evidence in _evidence_rows():
                    if evidence.get("覆盖编号") == coverage.get("覆盖编号"):
                        evidence["覆盖编号"] = existing["覆盖编号"]
                        evidence["标签ID"] = target_id_int
                        evidence["标签编号"] = target["标签编号"]
                        evidence["标签名称"] = target["标签名称"]
                coverage["状态"] = COVERAGE_MERGED
                coverage["status"] = COVERAGE_MERGED
                coverage["pending"] = False
                coverage["并入覆盖编号"] = existing["覆盖编号"]
                coverage["更新时间"] = _now()
                self._recompute_coverage(existing)
                merged_coverages.append(existing)

        for coverage in target_coverages:
            self._recompute_coverage(coverage)

        # 3. 关联资产数按覆盖并集刷新；没有覆盖数据的旧标签保留数值合并口径。
        if legacy_merge:
            target["关联资产数"] = str(
                int(source.get("关联资产数") or 0) + int(target.get("关联资产数") or 0)
            )
        else:
            target["关联资产数"] = str(len(self.get_coverage_assets(target)))
        source["关联资产数"] = "0"

        # 4. 源标签保留为历史别名，后续旧编号/旧名称仍可解析到目标标签。
        source_history = list(source.get("历史标签编号") or [])
        if source["标签编号"] not in source_history:
            source_history.append(source["标签编号"])
        target_history = list(target.get("历史标签编号") or [])
        for code in [source["标签编号"], *source_history]:
            if normalize_tag_code(code) not in {normalize_tag_code(item) for item in target_history}:
                target_history.append(code)
        target["历史标签编号"] = target_history

        # 源标签不再单独生效：状态沿用历史口径「已废弃」，并用合并去向标记
        # 它已并入目标标签，后续旧编号/旧名称仍可解析到目标标签。
        source["status"] = "已废弃"
        source["合并状态"] = "已合并"
        source["pending"] = False
        source["合并去向"] = target["标签编号"]
        source["合并至标签ID"] = target_id_int
        source["最后更新"] = _now()
        target["标签说明"] = f"{target.get('标签说明', '')} (合并自: {source.get('标签名称', '')})"
        target["最后更新"] = _now()

        store.log_change(
            self.MODULE, source_id_int, "合并标签",
            before="已发布", after="已废弃",
            source="tag_merge", scope="tag_registry->tag_coverage",
        )

        self.emit_event("tags_merged", {
            "source_id": source_id_int,
            "target_id": target_id_int,
            "source_name": source.get("标签名称"),
            "target_name": target.get("标签名称"),
            "moved_evidence": moved_evidence,
            "coverage_count": int(target["关联资产数"]),
        })

        return {
            "ok": True,
            "source": source_id_int,
            "target": target_id_int,
            "moved_evidence": moved_evidence,
            "关联资产数": int(target["关联资产数"]),
            "coverage_assets": self.get_coverage_assets(target),
            "coverage_count": len(self.get_coverage_assets(target)),
            "merged_coverages": merged_coverages,
            "legacy_merge": legacy_merge,
        }
