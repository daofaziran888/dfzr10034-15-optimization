"""统一资源接口：查询、导出、登记和动作按模块 key 分派到领域服务。"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import (
    ActionPayload, ActionResult, BatchAssociationPayload, EntryPayload,
    MergeTagsPayload, PageResult, RevokeAssociationPayload,
)
from app.services import service_for

router = APIRouter(prefix="/api", tags=["业务资源"])


def require_service(module: str):
    service = service_for(module)
    if service is None:
        raise HTTPException(status_code=404, detail=f"未知业务模块：{module}")
    return service


@router.get("/{module}", response_model=PageResult[dict])
def list_entries(
    module: str,
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    service = require_service(module)
    filters = {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in service.LIST_FIELDS and value.strip()
    }
    items, total = service.list_entries(
        filters=filters, keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{module}/export")
def export_entries(
    module: str,
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    service = require_service(module)
    filters = {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in service.LIST_FIELDS and value.strip()
    }
    items, _ = service.list_entries(
        filters=filters, keyword=keyword, status=status, page=1, size=1_000_000)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *service.LIST_FIELDS, "status"])
    for item in items:
        values = [item.get("id"), *(item.get(field, "") for field in service.LIST_FIELDS),
                  item.get("status", "")]
        writer.writerow([
            "'" + str(value) if str(value or "").startswith(("=", "+", "-", "@")) else value
            for value in values
        ])
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{module}.csv"'},
    )


@router.get("/{module}/{entry_id}", response_model=dict)
def get_entry(module: str, entry_id: int) -> dict[str, Any]:
    service = require_service(module)
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"{service.ENTITY} {entry_id} 不存在或已归档")
    return entry


@router.post("/{module}", response_model=ActionResult)
def create_entry(module: str, payload: EntryPayload) -> ActionResult:
    service = require_service(module)
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message=f"{service.ENTITY}已登记", entry=entry)


@router.post("/{module}/{entry_id}/actions", response_model=ActionResult)
def run_action(module: str, entry_id: int, payload: ActionPayload) -> ActionResult:
    service = require_service(module)
    entry, message = service.run_action(entry_id, payload.action.strip())
    return ActionResult(ok=entry is not None, message=message, entry=entry)


# ── 标签覆盖链路专用接口 ────────────────────────────────────
# 固定路径必须注册在 /{module}/{entry_id} 之前，避免被动态路径抢先匹配。

def require_tag_service():
    from app.services.tag_registry import TagRegistryService

    service = service_for("tag_registry")
    if not isinstance(service, TagRegistryService):
        service = TagRegistryService()
    return service


@router.post("/tag_registry/batch-associate", response_model=ActionResult)
def batch_associate_tags(payload: BatchAssociationPayload) -> ActionResult:
    """批量提交标签关联，逐条按资产身份归并覆盖集合。"""
    service = require_tag_service()
    result = service.batch_associate(
        payload.tag_id if not payload.records else None,
        payload.assets,
        records=payload.records or None,
        source=payload.source,
        credential=payload.credential,
        confirm=payload.confirm,
    )
    if not result.get("ok"):
        message = next(
            (item.get("error") for item in result.get("results", []) if item.get("error")),
            "批量关联未通过",
        )
        return ActionResult(ok=False, message=message, result=result)
    return ActionResult(
        ok=True,
        message=(
            f"批量关联完成：提交{result['submitted']}条，"
            f"新增{result['created']}条，重复{result['duplicates']}条，"
            f"覆盖{result['coverage_count']}张表"
        ),
        result=result,
    )


@router.post("/tag_registry/merge", response_model=ActionResult)
def merge_tags(payload: MergeTagsPayload) -> ActionResult:
    """合并两个标签，覆盖按资产身份取并集。"""
    service = require_tag_service()
    result = service.merge_tags(payload.source_id, payload.target_id)
    if not result.get("ok"):
        return ActionResult(ok=False, message=result.get("error", "标签合并失败"), result=result)
    return ActionResult(
        ok=True,
        message=(
            f"标签已合并：目标标签覆盖{result['coverage_count']}张表"
            f"（迁移凭据{result['moved_evidence']}条）"
        ),
        result=result,
    )


@router.post("/tag_registry/{tag_ref}/revoke", response_model=ActionResult)
def revoke_tag_association(tag_ref: str, payload: RevokeAssociationPayload) -> ActionResult:
    """撤销一个来源的标签关联凭据，保留其余来源的覆盖。"""
    service = require_tag_service()
    result = service.revoke_association(
        tag_ref,
        asset_code=payload.asset_code,
        source=payload.source,
        credential=payload.credential,
        evidence_id=payload.evidence_id,
    )
    if not result.get("ok"):
        return ActionResult(ok=False, message=result.get("error", "撤销失败"), result=result)
    return ActionResult(
        ok=True, message=f"已撤销{result['revoked_count']}条关联凭据", result=result)


@router.post("/tag_registry/{tag_ref}/confirm", response_model=ActionResult)
def confirm_tag_association(tag_ref: str, payload: EntryPayload) -> ActionResult:
    """确认关联凭据，标签引用兼容历史标签编号。"""
    service = require_tag_service()
    values = payload.values or {}
    result = service.confirm_association(
        tag_ref,
        asset_code=values.get("资产编号") or values.get("asset_code"),
        source=values.get("来源") or values.get("source"),
        evidence_id=values.get("凭据编号") or values.get("evidence_id"),
    )
    if not result.get("ok"):
        return ActionResult(ok=False, message=result.get("error", "确认失败"), result=result)
    return ActionResult(
        ok=True, message=f"已确认{result['confirmed_count']}条关联凭据", result=result)


@router.get("/tag_registry/{tag_ref}/coverage", response_model=dict)
def tag_coverage_detail(tag_ref: str) -> dict[str, Any]:
    """覆盖明细：资产覆盖集合 + 每个资产背后的来源凭据。"""
    service = require_tag_service()
    result = service.get_coverage_detail(tag_ref)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "标签不存在"))
    return result


@router.get("/tag_registry/{tag_ref}/coverage-count", response_model=dict)
def tag_coverage_count(tag_ref: str) -> dict[str, Any]:
    service = require_tag_service()
    assets = service.get_coverage_assets(tag_ref)
    return {"标签": tag_ref, "覆盖资产数": len(assets), "覆盖资产集合": assets}
