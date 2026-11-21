<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button
          v-if="isTagRegistry"
          class="btn"
          data-testid="open-batch-associate"
          type="button"
          @click="openBatch"
        >
          批量关联标签
        </button>
        <button
          v-if="isTagRegistry"
          class="btn"
          data-testid="open-merge-tags"
          type="button"
          @click="openMerge"
        >
          合并标签
        </button>
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button
              v-for="action in rowActions(row)"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runRowAction(action, row)"
            >
              {{ action }}
            </button>
            <button
              v-if="isTagRegistry"
              class="link"
              type="button"
              :data-testid="`coverage-${row.id}`"
              @click="openCoverage(String(row['标签编号']))"
            >
              覆盖明细
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="showMerge" class="modal-backdrop" data-testid="merge-modal">
      <form class="modal" @submit.prevent="submitMerge">
        <h3>合并标签</h3>
        <p class="page-desc">覆盖按资产身份取并集，交集资产只保留一条覆盖；源标签保留为历史编号。</p>
        <label class="create-field">
          <span>源标签（并入后作为历史编号）</span>
          <input v-model="mergeValues.source" data-testid="merge-source" placeholder="标签编号或标签名称" required />
        </label>
        <label class="create-field">
          <span>目标标签</span>
          <input v-model="mergeValues.target" data-testid="merge-target" placeholder="标签编号或标签名称" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showMerge = false">取消</button>
          <button class="btn primary" data-testid="submit-merge" type="submit" :disabled="busy">确认合并</button>
        </div>
      </form>
    </div>

    <div v-if="showBatch" class="modal-backdrop" data-testid="batch-modal">
      <form class="modal" @submit.prevent="submitBatch">
        <h3>批量关联标签</h3>
        <p class="page-desc">逐条按资产身份归并；同一张表重复提交只算一次覆盖，不同来源各自保留凭据。</p>
        <label class="create-field">
          <span>标签</span>
          <input v-model="batchValues.tag" data-testid="batch-tag" placeholder="标签编号或标签名称" required />
        </label>
        <label class="create-field">
          <span>资产编号（逗号或换行分隔）</span>
          <textarea
            v-model="batchValues.assets"
            class="batch-textarea"
            data-testid="batch-assets"
            rows="4"
            placeholder="商品甲, 商品乙"
            required
          />
        </label>
        <label class="create-field">
          <span>来源</span>
          <input v-model="batchValues.source" data-testid="batch-source" placeholder="批量关联" />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showBatch = false">取消</button>
          <button class="btn primary" data-testid="submit-batch" type="submit" :disabled="busy">提交关联</button>
        </div>
      </form>
    </div>

    <div v-if="coverage" class="modal-backdrop" data-testid="coverage-modal">
      <div class="modal">
        <h3>覆盖明细 · {{ coverage.标签编号 }} {{ coverage.标签名称 }}</h3>
        <p class="page-desc">
          覆盖资产 {{ coverage.覆盖资产数 }} 张：{{ coverage.覆盖资产集合.join('、') || '无' }}
        </p>
        <table class="data-table">
          <thead>
            <tr>
              <th>资产编号</th>
              <th>覆盖状态</th>
              <th>来源</th>
              <th>凭据数</th>
              <th>首次确认</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in coverage.明细" :key="item.覆盖编号">
              <td>{{ item.资产编号 }}</td>
              <td>{{ item.覆盖状态 }}</td>
              <td>{{ item.来源.join('、') }}</td>
              <td>{{ item.确认凭据数 }} / {{ item.凭据数 }}</td>
              <td>{{ item.首次确认时间 || '—' }}</td>
            </tr>
            <tr v-if="!coverage.明细.length">
              <td colspan="5" class="empty-state">该标签暂无覆盖记录</td>
            </tr>
          </tbody>
        </table>
        <div class="page-actions">
          <button class="btn" type="button" @click="coverage = null">关闭</button>
        </div>
      </div>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  batchAssociate,
  createEntry,
  downloadEntries,
  listEntries,
  loadCoverage,
  mergeTags,
  moduleMeta,
  runAction as applyAction,
} from '@/api/backend-service'
import type { CoverageDetail } from '@/api/backend-service'
import type { EntryRow } from '@/data/types'

const props = defineProps<{ moduleKey: string }>()
const meta = moduleMeta(props.moduleKey)
const isTagRegistry = computed(() => meta.key === 'tag_registry')
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = meta.fields.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const showMerge = ref(false)
const mergeValues = ref({ source: '', target: '' })
const showBatch = ref(false)
const batchValues = ref({ tag: '', assets: '', source: '批量关联' })
const coverage = ref<CoverageDetail | null>(null)
const busy = ref(false)

function rowActions(row: EntryRow): string[] {
  if (meta.key === 'tag_association') {
    const status = String(row['关联状态'] ?? '')
    if (status === '已撤销') return []
    return status === '待确认' ? ['确认关联', '撤销关联'] : ['撤销关联']
  }
  return meta.actions
}

const stats = computed(() => [
  { label: meta.metrics[0], value: total.value },
  { label: meta.metrics[1], value: rows.value.filter((row) => row.status === meta.statuses[1]).length },
  {
    label: meta.metrics[2],
    value: rows.value.filter((row) => row.status === meta.statuses[meta.statuses.length - 1]).length,
  },
])
const statusSummary = computed(() =>
  meta.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.fields.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  return runRowAction(action, row)
}

async function runRowAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  try {
    const result = await applyAction(meta.key, Number(row.id), action)
    if (!result.ok) throw new Error(result.message)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

function openMerge() {
  mergeValues.value = { source: '', target: '' }
  errorMessage.value = ''
  showMerge.value = true
}

async function submitMerge() {
  busy.value = true
  errorMessage.value = ''
  try {
    const result = await mergeTags(mergeValues.value.source, mergeValues.value.target)
    if (!result.ok) throw new Error(result.message)
    showMerge.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '标签合并失败'
  } finally {
    busy.value = false
  }
}

function openBatch() {
  batchValues.value = { tag: '', assets: '', source: '批量关联' }
  errorMessage.value = ''
  showBatch.value = true
}

async function submitBatch() {
  busy.value = true
  errorMessage.value = ''
  try {
    const assets = batchValues.value.assets.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean)
    const result = await batchAssociate(batchValues.value.tag, assets, batchValues.value.source || '批量关联')
    if (!result.ok) throw new Error(result.message)
    showBatch.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量关联失败'
  } finally {
    busy.value = false
  }
}

async function openCoverage(tagRef: string) {
  errorMessage.value = ''
  try {
    coverage.value = await loadCoverage(tagRef)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '覆盖明细读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

onMounted(reload)
</script>
