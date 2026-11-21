# 治数工坊 · 数据治理与生命周期管理平台

面向资产注册、元数据索引与搜索、质量规则引擎、数据画像与分级、脱敏与操作日志、生命周期策略、冷热归档、血缘追踪、影响分析、变更捕获与契约治理的数据治理与生命周期管理平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 资产注册 | `asset_registry` | 数据资产 | 资产编号、资产名称、资产类型 |
| 元数据索引 | `metadata_index` | 元数据条目 | 条目编号、所属资产、字段名称 |
| 质量规则 | `quality_rule` | 质量检查 | 规则编号、目标资产、检查类型 |
| 数据画像 | `profile_stats` | 数据画像 | 画像编号、目标资产、行数统计 |
| 数据分级 | `classification` | 分级标签 | 标签编号、目标字段、敏感等级 |
| 生命周期 | `lifecycle_policy` | 生命周期策略 | 策略编号、目标资产、创建阶段 |
| 冷热归档 | `cold_archive` | 归档任务 | 任务编号、源资产、归档条件 |
| 保留清理 | `retention_job` | 清理计划 | 计划编号、目标资产、保留天数 |
| 脱敏引擎 | `data_anonym` | 脱敏规则 | 规则编号、目标字段、脱敏算法 |
| 操作日志 | `operation_log` | 操作记录 | 记录编号、目标资产、操作人 |
| 变更捕获 | `change_capture` | 变更记录 | 记录编号、目标资产、变更类型 |
| 血缘追踪 | `lineage_track` | 血缘关系 | 关系编号、上游资产、下游资产 |
| 影响分析 | `impact_analysis` | 影响报告 | 报告编号、变更资产、影响下游 |
| 标签体系 | `tag_registry` | 业务标签 | 标签编号、标签名称、标签层级 |
| 关联凭据 | `tag_association` | 关联凭据 | 凭据编号、标签编号、资产编号、来源、关联状态 |
| 覆盖明细 | `tag_coverage` | 标签覆盖 | 覆盖编号、标签编号、资产编号、状态、确认凭据数 |
| 治理评分 | `govern_score` | 评分任务 | 任务编号、评估对象、评分维度 |
| 数据契约 | `data_contract` | 契约定义 | 契约编号、数据资产、Schema约束 |
| 合规扫描 | `compliance_scan` | 扫描任务 | 任务编号、目标资产、合规条款 |
| 问题追踪 | `issue_track` | 治理问题 | 问题编号、关联资产、问题类型 |
| 版本履历 | `version_history` | 版本快照 | 快照编号、目标资产、版本标签 |
| 调度治理 | `schedule_job` | 治理调度 | 作业编号、治理类型、目标资产 |
| 差异报告 | `diff_report` | 差异记录 | 记录编号、比较对象、比较维度 |
| 负责人管理 | `owner_mgr` | 责任人 | 指派编号、目标资产、负责角色 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

### 标签覆盖口径

标签关联分「凭据」与「覆盖」两层：`tag_association` 记录每个来源的提交凭据，
`tag_coverage` 按「标签 + 资产身份」归并，同一张表在一个标签下只有一条覆盖。

- **去重**：同一来源重复提交只保留一份凭据；同一批次内重复的资产只算一次覆盖。
- **多来源**：不同来源支持同一张表时各自保留凭据，覆盖仍只算一次。
- **合并**：合并标签时覆盖按资产身份取并集，交集资产不会重复计数；源标签保留为
  历史编号，之后用旧标签编号或旧名称提交关联仍落到合并后的目标标签。
- **撤销**：可按资产 + 来源撤销单个凭据；只要还有其他已确认凭据，覆盖保持生效。
- **追溯**：`GET /api/tag_registry/{标签}/coverage` 返回覆盖明细与来源凭据，
  覆盖记录的 `首次确认凭据` / `首次确认时间` 回答「哪一次确认后取得覆盖」。
- **评分**：治理评分的「标签覆盖」维度按覆盖并集计算，`标签覆盖变化` 后可用
  `recompute_after_tag_change()` 重算汇总。

相关接口：

```text
POST /api/tag_registry/batch-associate        批量关联（records 或 tag_id + assets）
POST /api/tag_registry/merge                  合并标签（source_id / target_id）
POST /api/tag_registry/{标签}/confirm         确认关联（兼容历史标签编号）
POST /api/tag_registry/{标签}/revoke          撤销某个来源的凭据
GET  /api/tag_registry/{标签}/coverage        覆盖明细
GET  /api/tag_registry/{标签}/coverage-count  覆盖集合与数量
```

领域：数据工程
子方向：数仓与数据湖
