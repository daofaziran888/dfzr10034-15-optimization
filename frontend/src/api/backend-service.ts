import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

export type CoverageDetail = {
  ok: boolean
  标签编号: string
  标签名称: string
  覆盖资产集合: string[]
  覆盖资产数: number
  明细: {
    覆盖编号: string
    标签编号: string
    标签名称: string
    资产编号: string
    覆盖状态: string
    来源: string[]
    凭据数: number
    确认凭据数: number
    首次确认时间: string
    首次确认凭据: string
    最近确认时间: string
  }[]
}

export async function batchAssociate(
  tagId: string | number,
  assets: string[],
  source = '批量关联',
): Promise<ActionResult> {
  const response = await request('/api/tag_registry/batch-associate', {
    method: 'POST',
    body: JSON.stringify({ tag_id: tagId, assets, source }),
  })
  return await response.json()
}

export async function mergeTags(
  sourceId: string | number,
  targetId: string | number,
): Promise<ActionResult> {
  const response = await request('/api/tag_registry/merge', {
    method: 'POST',
    body: JSON.stringify({ source_id: sourceId, target_id: targetId }),
  })
  return await response.json()
}

export async function revokeAssociation(
  tagRef: string,
  payload: { asset_code?: string; source?: string },
): Promise<ActionResult> {
  const response = await request(`/api/tag_registry/${encodeURIComponent(tagRef)}/revoke`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return await response.json()
}

export async function loadCoverage(tagRef: string): Promise<CoverageDetail> {
  const response = await request(`/api/tag_registry/${encodeURIComponent(tagRef)}/coverage`)
  if (!response.ok) throw new Error('标签覆盖明细读取失败')
  return await response.json()
}
