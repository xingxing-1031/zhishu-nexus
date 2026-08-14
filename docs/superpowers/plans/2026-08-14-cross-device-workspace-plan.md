# 企析跨设备工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让两个固定演示身份分别拥有可跨设备自动同步的完整会话，并修复桌面/手机聊天滚动、历史回答、固定输入框、查询设置与视觉质感问题。

**Architecture:** 保留现有 `agent_conversations` 作为 LLM 上下文存储，新建独立的 `workspace_conversations` JSONB 表保存可恢复的工作台展示状态，避免 UI 状态污染 Agent 上下文。前端采用本地优先、服务端合并和聚焦刷新；聊天区是唯一纵向滚动容器，输入区固定在工作区底行。

**Tech Stack:** FastAPI、Pydantic v2、PostgreSQL/psycopg、React 18、TypeScript 5、Vite、CSS、Lucide、ECharts。

## Global Constraints

- 只支持现有 `analyst-demo` 与 `admin-demo` 两个固定身份，不增加注册、空间码或设备管理。
- 服务端只从 HttpOnly Session 解析 `user_id`，会话 API 不接受客户端指定用户。
- 每个身份最多保存 8 个会话，每个会话最多保存 8 轮，分析结果表格最多持久化 20 行。
- `docs/PROJECT_HANDOFF.md` 是用户私有未跟踪文件，任何提交都不能包含它。
- 新样式使用冰白画布、`#0CA89B` 主操作色、`#2563EB` 数据色、`#172033` 正文和 `#E2EAF0` 边框。

---

### Task 1: 工作台会话模型、迁移与存储

**Files:**
- Create: `db/migrations/009_workspace_conversations.sql`
- Create: `src/retail_analytics_agent/workspace_history.py`
- Create: `tests/test_workspace_history.py`

**Interfaces:**
- Produces: `WorkspaceConversationPayload`, `WorkspaceHistoryStore`, `InMemoryWorkspaceHistoryStore`, `PostgresWorkspaceHistoryStore`。
- `WorkspaceHistoryStore.list_for_user(user_id) -> tuple[WorkspaceConversationPayload, ...]`
- `WorkspaceHistoryStore.put(user_id, conversation) -> WorkspaceConversationPayload`
- `WorkspaceHistoryStore.delete(user_id, conversation_id) -> bool`

- [ ] **Step 1: 写失败测试**

覆盖用户隔离、按 `updatedAt` 降序、同 ID 幂等覆盖、8 会话上限、8 轮上限和删除仅影响当前用户。使用 `InMemoryWorkspaceHistoryStore` 验证公共契约，并使用模拟连接验证 PostgreSQL 查询始终同时带 `user_id` 与 `conversation_id`。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_workspace_history.py -q`
Expected: FAIL，模块 `workspace_history` 尚不存在。

- [ ] **Step 3: 实现模型和存储**

`WorkspaceConversationPayload` 使用前端 JSON 字段别名，严格验证 `id/title/createdAt/updatedAt/turns`；turn 中 `response/outcome/chartSpec/rows/stageState/followUpContext` 作为受大小限制的 JSON 数据保存。PostgreSQL 表以 `(user_id, conversation_id)` 为主键，`payload JSONB NOT NULL`，并建立 `(user_id, updated_at DESC)` 索引。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_workspace_history.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

Run: `git add db/migrations/009_workspace_conversations.sql src/retail_analytics_agent/workspace_history.py tests/test_workspace_history.py && git commit -m "feat: persist workspace conversations by account"`

### Task 2: 账号级会话 API

**Files:**
- Modify: `src/retail_analytics_agent/app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Produces: `GET /agent/conversations`、`PUT /agent/conversations/{conversation_id}`、`DELETE /agent/conversations/{conversation_id}`。
- Consumes: `WorkspaceHistoryStore` 与现有 `AccessContext`。

- [ ] **Step 1: 写失败 API 测试**

覆盖列表只读取当前身份、路径 ID 与 payload ID 不一致返回 422、保存不接受伪造 `user_id`、删除返回 204、另一个身份读取不到数据。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_app.py -q -k "workspace_conversation"`
Expected: FAIL，接口返回 404。

- [ ] **Step 3: 实现依赖与接口**

新增 `get_workspace_history_store()`，生产环境返回 `PostgresWorkspaceHistoryStore(connect_to_database)`；接口从 `get_access_context` 取得 `user_id`，`PUT` 校验路径 ID，`DELETE` 保持幂等并返回 204。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_app.py -q -k "workspace_conversation"`
Expected: PASS。

- [ ] **Step 5: 提交**

Run: `git add src/retail_analytics_agent/app.py tests/test_app.py && git commit -m "feat: expose account conversation sync api"`

### Task 3: 前端历史兼容与合并规则

**Files:**
- Modify: `frontend/src/conversations.ts`
- Modify: `frontend/src/chatModels.ts`
- Modify: `frontend/src/types.ts`
- Create: `tests/test_frontend_conversation_contract.py`

**Interfaces:**
- Produces: `normalizeConversations(value)`, `mergeConversations(local, remote)` 和历史回答 fallback。
- `assistantFromTurn` 的回答优先级为 `response.answer`、`outcome.answer`、`summary`。

- [ ] **Step 1: 写失败契约测试**

通过读取 TypeScript 源码和固定 JSON fixture，验证旧 turn 缺少 `response` 时仍保留 summary、合并按 `updatedAt` 选新版本、服务端字段与前端接口一致。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_frontend_conversation_contract.py -q`
Expected: FAIL，合并与兼容入口尚不存在。

- [ ] **Step 3: 实现规范化、合并与答案兜底**

将本地读取和远端读取共用同一规范化函数；丢弃损坏 turn 而非整段对话；保存仍执行 8x8 与 20 行限制；`assistantFromTurn` 永远为有效历史 turn 生成可见文本。

- [ ] **Step 4: 验证 TypeScript 与契约测试**

Run: `pytest tests/test_frontend_conversation_contract.py -q`
Run: `npm run build --prefix frontend`
Expected: 两者 PASS。

- [ ] **Step 5: 提交**

Run: `git add frontend/src/conversations.ts frontend/src/chatModels.ts frontend/src/types.ts tests/test_frontend_conversation_contract.py && git commit -m "fix: restore and merge conversation history"`

### Task 4: 前端自动同步与同步状态

**Files:**
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/useConversationSync.ts`
- Modify: `frontend/src/Workspace.tsx`
- Modify: `frontend/src/workspace/ConversationRail.tsx`

**Interfaces:**
- Produces: `api.conversations.list/save/delete` 和 `useConversationSync(userId, conversations, setConversations)`。
- Hook 返回 `syncState: "syncing" | "synced" | "local"`、`refresh()`、`deleteRemote(id)`。

- [ ] **Step 1: 添加 API 类型并让构建暴露未实现引用**

先在 Workspace 接入 hook 和同步状态，运行构建确认缺少 API/Hook。

- [ ] **Step 2: 实现 API 与同步 Hook**

登录后拉取并合并；变更后 400ms 防抖保存；窗口 focus、页面恢复可见和网络 online 时刷新；失败保留本地副本并显示“仅保存在本机”；删除先更新 UI 再调用远端，失败时不恢复已删除 UI。

- [ ] **Step 3: 修复会话切换状态**

远端合并后确保 active ID 有效；手机选择历史后关闭抽屉；每次切换使用该会话最新 request ID；空会话不会覆盖远端已有会话。

- [ ] **Step 4: 验证构建**

Run: `npm run build --prefix frontend`
Expected: PASS。

- [ ] **Step 5: 提交**

Run: `git add frontend/src/api.ts frontend/src/useConversationSync.ts frontend/src/Workspace.tsx frontend/src/workspace/ConversationRail.tsx && git commit -m "feat: sync conversations across signed-in devices"`

### Task 5: 查询设置与显示偏好

**Files:**
- Modify: `src/retail_analytics_agent/agent_models.py`
- Modify: `tests/test_agent_models.py`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/Workspace.tsx`
- Modify: `frontend/src/workspace/MessageComposer.tsx`
- Modify: `frontend/src/workspace/AssistantResponse.tsx`

**Interfaces:**
- Produces: `result_display: "auto" | "chart_table" | "table"` 与 `auto_open_evidence: bool` 请求字段。
- 前端本地设置键按 `user_id` 隔离；`maxRows` 仍由服务端上限裁剪。

- [ ] **Step 1: 写失败模型测试**

验证合法显示模式可解析，非法值返回校验错误，默认值为 `auto` 与 `false`。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agent_models.py -q -k "display_preferences"`
Expected: FAIL，字段尚不存在。

- [ ] **Step 3: 实现三项设置**

设置弹层使用原生 select、单选分段控件和 checkbox；显示模式控制图表/表格默认呈现；自动证据设置在结果完成后打开 inspector。设置变更持久化到当前身份的 localStorage。

- [ ] **Step 4: 验证后端和前端**

Run: `pytest tests/test_agent_models.py -q -k "display_preferences"`
Run: `npm run build --prefix frontend`
Expected: PASS。

- [ ] **Step 5: 提交**

Run: `git add src/retail_analytics_agent/agent_models.py tests/test_agent_models.py frontend/src/types.ts frontend/src/api.ts frontend/src/Workspace.tsx frontend/src/workspace/MessageComposer.tsx frontend/src/workspace/AssistantResponse.tsx && git commit -m "feat: expand query display preferences"`

### Task 6: 滚动、固定输入区与高级视觉

**Files:**
- Modify: `frontend/src/workspace/WorkspaceShell.tsx`
- Modify: `frontend/src/workspace/ChatThread.tsx`
- Modify: `frontend/src/workspace/MessageComposer.tsx`
- Modify: `frontend/src/styles.css`
- Create: `design-system/qixi-workspace/MASTER.md`

**Interfaces:**
- 聊天区 `.chat-thread` 是唯一纵向滚动容器。
- 输入区 `.composer-wrap` 永远位于工作区底部，不随消息列表滚动。

- [ ] **Step 1: 生成并保存 UI 设计系统**

Run: `python C:/Users/21078/.codex/skills/ui-ux-pro-max/scripts/search.py "enterprise AI analytics workspace polished light" --design-system --persist -p "Qixi Workspace" --output-dir "E:/qiuzhaoxiangmu/retail-analytics-agent" --variance 5 --motion 3 --density 7`
Expected: 生成 `design-system/qixi-workspace/MASTER.md`；仅采用与已批准颜色和企业工作台定位一致的规则。

- [ ] **Step 2: 修复高度链与触摸滚动**

为 workspace 根、网格、conversation stage、thread 添加明确的 `min-height: 0`、`height: 100%`、`overflow` 与 `touch-action: pan-y`；移动端使用安全区；textarea 禁止手动 resize，内部超长文本自己滚动。

- [ ] **Step 3: 重做层次和按钮状态**

替换暗青色变量，增加浅青蓝环境带、主按钮高光/阴影、次按钮 hover/pressed、冷灰边框与蓝色数据强调；保持卡片半径不超过 8px、按钮触控尺寸至少 44px、focus-visible 清晰。

- [ ] **Step 4: 验证构建和静态规则**

Run: `npm run build --prefix frontend`
Run: `rg -n "border-radius: (1[0-9]|[2-9][0-9])px|letter-spacing: -" frontend/src/styles.css`
Expected: 构建 PASS；工作台不出现超规格卡片半径或负字距。

- [ ] **Step 5: 提交**

Run: `git add frontend/src/workspace/WorkspaceShell.tsx frontend/src/workspace/ChatThread.tsx frontend/src/workspace/MessageComposer.tsx frontend/src/styles.css design-system/qixi-workspace/MASTER.md && git commit -m "feat: polish responsive enterprise workspace"`

### Task 7: 全量验证、浏览器验收与部署

**Files:**
- Modify: `src/retail_analytics_agent/static/**`（由前端构建生成）

**Interfaces:**
- Consumes: 所有新增后端、前端和样式接口。
- Produces: 可部署静态包与线上验收结果。

- [ ] **Step 1: 全量自动化验证**

Run: `pytest -q`
Run: `ruff check .`
Run: `npm run build --prefix frontend`
Expected: 全部退出码 0。

- [ ] **Step 2: 更新后端静态资源**

使用现有项目构建流程将 `frontend/dist` 同步到 `src/retail_analytics_agent/static`，不手工编辑带哈希的产物。

- [ ] **Step 3: 本地桌面和手机浏览器验收**

在 1280x720 与 390x844 验证：长会话 `scrollHeight > clientHeight` 且 scrollTop 可变化；composer 的 bottom 坐标滚动前后不变；历史切换显示回答；设置弹层无溢出；抽屉、图表、表格和按钮无重叠。

- [ ] **Step 4: 跨身份与跨设备验收**

用两个独立浏览器上下文登录同一身份验证同步，再登录另一身份验证隔离；刷新和切换历史后回答、表格、图表仍可见。

- [ ] **Step 5: 提交、推送并观察部署**

只提交本轮文件和生成资源，推送 `main`，等待 GitHub Actions 部署成功；不得提交 `docs/PROJECT_HANDOFF.md`。

- [ ] **Step 6: 线上复验**

在 `http://106.52.176.63/` 重复桌面和手机关键检查，确认加载的是新静态资源且 API 数据来自服务器。
