# 知枢 Nexus 品牌升级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将产品、代码仓库和本地目录统一升级为“知枢 Nexus / zhishu-nexus”，保留现有会话数据、Agent 能力和线上部署稳定性。

**Architecture:** 新建单一品牌模块集中提供产品名、文案和可复用双字字标，所有用户可见界面从该模块读取；新建独立存储迁移函数，让新命名空间在首次加载时兼容读取旧键。后端只更新应用元数据，稳定的 Python 包、API、数据库和 VPS 目录不迁移。

**Tech Stack:** React 18、TypeScript 5、Vite 6、Lucide React、FastAPI、Pytest、Node.js 22、GitHub Actions、GitHub CLI。

## Global Constraints

- 完整产品名必须为“知枢 Nexus”，代码与仓库 slug 必须为 `zhishu-nexus`。
- 登录页定位必须表达“连接企业知识、经营数据与智能工具的工作台”。
- AI 身份必须显示为“知枢 AI”，不再出现单字“析”头像。
- 沿用现有 `#0CA89B`、`#087F78`、`#2563EB` 设计系统，不增加新图标或前端依赖。
- 保持桌面/手机会话布局、固定输入框、跨设备同步、删除同步和权限逻辑不变。
- localStorage 新键优先、旧键回退、读取后复制到新键，不删除旧键。
- Python 包 `retail_analytics_agent`、数据库、API 路由和 VPS 目录 `/home/ubuntu/retail-analytics-agent` 保持不变。
- GitHub 仓库改名为私有仓库 `xingxing-1031/zhishu-nexus`，本地目录最终改为 `E:\qiuzhaoxiangmu\zhishu-nexus`。

---

## File Structure

- Create `frontend/src/brand.tsx`: 品牌常量、界面文案和可复用 `BrandMark` 组件。
- Create `frontend/src/storageMigration.ts`: 不依赖 React 的 localStorage 兼容读取函数。
- Create `frontend/smoke/storage-migration-smoke.mjs`: 在 Node.js 22 中执行真实的新旧键迁移断言。
- Modify `frontend/src/App.tsx`: 加载页品牌。
- Modify `frontend/src/LoginPage.tsx`: 登录页品牌、能力标签和主操作文案。
- Modify `frontend/src/components.tsx`: 桌面侧栏和移动端顶栏品牌。
- Modify `frontend/src/workspace/ConversationRail.tsx`: 会话栏品牌。
- Modify `frontend/src/workspace/ChatThread.tsx`: 空会话欢迎文案和字标。
- Modify `frontend/src/workspace/AssistantResponse.tsx`: AI 身份、头像和 aria-label。
- Modify `frontend/src/workspace/MessageComposer.tsx`: 输入提示和重要结论提示。
- Modify `frontend/src/workspace/EvidenceInspector.tsx`: 空状态品牌文案。
- Modify `frontend/src/conversations.ts`: 会话存储新旧键迁移。
- Modify `frontend/src/Workspace.tsx`: 查询偏好存储新旧键迁移。
- Modify `frontend/src/styles.css`: 双字字标尺寸、排版和响应式约束。
- Modify `frontend/index.html`: 页面标题与描述。
- Modify `frontend/package.json`, `frontend/package-lock.json`: 前端包名和迁移 smoke 命令。
- Modify `frontend/smoke/console-smoke.mjs`: 新页面标题断言并执行存储迁移 smoke。
- Modify `tests/test_frontend_conversation_contract.py`: 新品牌和迁移源代码契约。
- Modify `src/retail_analytics_agent/app.py`: FastAPI 标题。
- Modify `.github/workflows/ci.yml`: Docker CI 镜像标签。
- Modify `README.md`, `docs/PROJECT_HANDOFF.md`, `docs/INTERVIEW_GUIDE_OPERATIONS_AGENT.md`, `docs/RESUME_EVIDENCE_AGENT.md`, `design-system/qixi-workspace/MASTER.md`: 当前品牌、仓库、本地路径和讲解材料。
- Modify current deployment docs only where they show the GitHub clone URL; retain documented VPS compatibility path.

---

### Task 1: Add The Shared Brand Identity

**Files:**
- Create: `frontend/src/brand.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/LoginPage.tsx`
- Modify: `frontend/src/components.tsx`
- Modify: `frontend/src/workspace/ConversationRail.tsx`
- Modify: `frontend/src/workspace/ChatThread.tsx`
- Modify: `frontend/src/workspace/AssistantResponse.tsx`
- Modify: `frontend/src/workspace/MessageComposer.tsx`
- Modify: `frontend/src/workspace/EvidenceInspector.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/index.html`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/smoke/console-smoke.mjs`
- Test: `tests/test_frontend_conversation_contract.py`

**Interfaces:**
- Produces: `BRAND` readonly object and `BrandMark({ size, decorative, className })` React component.
- Consumes: Existing CSS token system and React component structure.

- [ ] **Step 1: Add failing brand contract assertions**

Append assertions that read the active frontend files and require `知枢 Nexus`, `知枢 AI`, `把企业问题交给知枢`, `zhishu-nexus-console`, and the absence of literal `>析<` in active components.

```python
def test_zhishu_brand_is_consistent_across_active_workspace() -> None:
    root = Path(__file__).parents[1]
    login = (root / "frontend/src/LoginPage.tsx").read_text(encoding="utf-8")
    assistant = (root / "frontend/src/workspace/AssistantResponse.tsx").read_text(encoding="utf-8")
    package = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    assert "把企业问题交给知枢" in login
    assert "知枢 AI" in assistant
    assert package["name"] == "zhishu-nexus-console"
    assert ">析<" not in login + assistant
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `python -m pytest tests/test_frontend_conversation_contract.py -q`

Expected: FAIL because current active UI still contains “企析”和“析”, and package name is `retail-analytics-console`.

- [ ] **Step 3: Implement shared brand constants and mark**

Create the public interface:

```tsx
export const BRAND = {
  productName: "知枢 Nexus",
  chineseName: "知枢",
  assistantName: "知枢 AI",
  workspaceName: "知枢工作台",
} as const;

export function BrandMark({ size = "regular", decorative = false, className = "" }: BrandMarkProps) {
  return (
    <span
      className={`brand-mark ${size === "large" ? "large" : ""} ${className}`.trim()}
      aria-label={decorative ? undefined : "知枢 AI 助手"}
      aria-hidden={decorative || undefined}
    >
      <span>知</span><span>枢</span>
    </span>
  );
}
```

Use `BrandMark` in loading, login, sidebars, mobile header, empty state and assistant responses. Apply the approved login/workspace copy and update `frontend/index.html` to:

```html
<meta name="description" content="知枢 Nexus，连接企业知识、经营数据与智能工具的企业智能工作台" />
<title>知枢 Nexus · 企业智能工作台</title>
```

Set the package name to `zhishu-nexus-console` in both package files and update the console smoke marker to the new title.

- [ ] **Step 4: Style and verify the double-character mark**

Replace `.logo-mark`/`.assistant-mark` presentation with `.brand-mark` and fixed two-row glyph layout. Preserve 32 px regular, 40 px large and 30 px mobile dimensions; use `line-height: .9`, stable grid tracks, existing teal/blue colors, focus visibility and reduced-motion behavior.

- [ ] **Step 5: Run focused tests and frontend build**

Run:

```powershell
python -m pytest tests/test_frontend_conversation_contract.py -q
npm --prefix frontend run build
npm --prefix frontend run smoke
```

Expected: all commands exit 0 and built HTML contains `知枢 Nexus · 企业智能工作台`.

- [ ] **Step 6: Commit UI brand changes**

```powershell
git add frontend tests/test_frontend_conversation_contract.py
git commit -m "feat: rebrand workspace as zhishu nexus"
```

---

### Task 2: Migrate Browser Storage Without Losing Data

**Files:**
- Create: `frontend/src/storageMigration.ts`
- Create: `frontend/smoke/storage-migration-smoke.mjs`
- Modify: `frontend/src/conversations.ts`
- Modify: `frontend/src/Workspace.tsx`
- Modify: `frontend/package.json`
- Modify: `frontend/smoke/console-smoke.mjs`
- Modify: `tests/test_frontend_conversation_contract.py`

**Interfaces:**
- Produces: `readMigratedStorage(storage: StorageLike | undefined, primaryKey: string, legacyKey: string): string | null`.
- Consumes: Browser `localStorage`-compatible `getItem`/`setItem` interface.

- [ ] **Step 1: Write executable failing storage migration smoke test**

The smoke script imports `storageMigration.ts` with Node 22 type stripping and checks all three required states:

```js
const oldOnly = memoryStorage({ old: "legacy" });
assert.equal(readMigratedStorage(oldOnly, "new", "old"), "legacy");
assert.equal(oldOnly.getItem("new"), "legacy");
assert.equal(oldOnly.getItem("old"), "legacy");

const both = memoryStorage({ old: "legacy", new: "current" });
assert.equal(readMigratedStorage(both, "new", "old"), "current");
```

- [ ] **Step 2: Run smoke and verify failure**

Run: `node --experimental-strip-types frontend/smoke/storage-migration-smoke.mjs`

Expected: FAIL because `frontend/src/storageMigration.ts` does not exist.

- [ ] **Step 3: Implement the storage migration helper**

```ts
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export function readMigratedStorage(storage: StorageLike | undefined, primaryKey: string, legacyKey: string) {
  if (!storage) return null;
  const current = storage.getItem(primaryKey);
  if (current !== null) return current;
  const legacy = storage.getItem(legacyKey);
  if (legacy !== null) storage.setItem(primaryKey, legacy);
  return legacy;
}
```

Keep exception handling in the existing `loadConversations` and query-preference loading functions so unavailable or full browser storage never blocks the workspace.

- [ ] **Step 4: Connect both migrated namespaces**

Use these exact key families:

```ts
`zhishu-nexus:conversations:v1:${encodeURIComponent(userId)}`
`retail-analytics:conversations:v1:${encodeURIComponent(userId)}`
`zhishu-nexus:query-preferences:v1:${encodeURIComponent(userId)}`
`retail-analytics:query-preferences:v1:${encodeURIComponent(userId)}`
```

Writes go only to the new namespace. Reads call `readMigratedStorage` with the new key first and legacy key second. Do not call `removeItem`.

- [ ] **Step 5: Run migration, contract and build checks**

Run:

```powershell
node --experimental-strip-types frontend/smoke/storage-migration-smoke.mjs
python -m pytest tests/test_frontend_conversation_contract.py -q
npm --prefix frontend run build
```

Expected: migration smoke proves new-key priority, legacy copy and legacy retention; Python contracts and TypeScript build pass.

- [ ] **Step 6: Commit storage migration**

```powershell
git add frontend/src/storageMigration.ts frontend/src/conversations.ts frontend/src/Workspace.tsx frontend/smoke frontend/package.json tests/test_frontend_conversation_contract.py
git commit -m "feat: migrate zhishu browser storage keys"
```

---

### Task 3: Update Application Metadata And Active Documentation

**Files:**
- Modify: `src/retail_analytics_agent/app.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `docs/PROJECT_HANDOFF.md`
- Modify: `docs/INTERVIEW_GUIDE_OPERATIONS_AGENT.md`
- Modify: `docs/RESUME_EVIDENCE_AGENT.md`
- Modify: `docs/VPS_DEPLOYMENT_W7.md`
- Modify: `design-system/qixi-workspace/MASTER.md`
- Test: `tests/test_app.py`
- Test: `tests/test_deployment_assets.py`

**Interfaces:**
- Produces: FastAPI OpenAPI title `知枢 Nexus 企业智能 Agent 平台` and current documentation with new repository/local path.
- Consumes: Existing API routes, deployment scripts and compatibility VPS path.

- [ ] **Step 1: Add failing API metadata assertion**

```python
def test_openapi_uses_zhishu_product_title(client: TestClient) -> None:
    assert client.get("/openapi.json").json()["info"]["title"] == "知枢 Nexus 企业智能 Agent 平台"
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python -m pytest tests/test_app.py tests/test_deployment_assets.py -q`

Expected: metadata assertion fails with current title “零售运营可审计分析助手”.

- [ ] **Step 3: Update runtime and CI metadata**

Change only FastAPI `title` and Docker CI image tag:

```python
app = FastAPI(title="知枢 Nexus 企业智能 Agent 平台", version="0.1.0", lifespan=lifespan)
```

```yaml
run: docker build -t zhishu-nexus:ci .
```

Do not rename `retail_analytics_agent`, Compose services, databases, API paths or VPS paths.

- [ ] **Step 4: Update current documentation**

Rewrite the README opening around this exact positioning:

```markdown
# 知枢 Nexus｜企业智能 Agent 平台

知枢 Nexus 是连接企业知识、经营数据与智能工具的企业智能工作台。
```

Update active interview/resume documents from “企析” to “知枢 Nexus”; retain technical evidence and measured numbers unchanged. Update GitHub/local paths to `xingxing-1031/zhishu-nexus` and `E:\qiuzhaoxiangmu\zhishu-nexus`. Add an explicit note wherever `/home/ubuntu/retail-analytics-agent` appears that it is the retained compatibility deployment path.

- [ ] **Step 5: Verify documentation boundaries and focused tests**

Run:

```powershell
python -m pytest tests/test_app.py tests/test_deployment_assets.py -q
rg -n "企析|>析<|retail-analytics-console" README.md frontend/src frontend/index.html docs/PROJECT_HANDOFF.md docs/INTERVIEW_GUIDE_OPERATIONS_AGENT.md docs/RESUME_EVIDENCE_AGENT.md design-system/qixi-workspace/MASTER.md
```

Expected: tests pass; search returns no stale active product brand. References to `retail_analytics_agent` and `/home/ubuntu/retail-analytics-agent` remain intentionally.

- [ ] **Step 6: Commit metadata and documentation**

```powershell
git add src/retail_analytics_agent/app.py .github/workflows/ci.yml README.md docs design-system tests/test_app.py tests/test_deployment_assets.py
git commit -m "docs: align zhishu product identity"
```

---

### Task 4: Run Full Regression And Visual Verification

**Files:**
- Modify only files required by observed failures.

**Interfaces:**
- Consumes: Completed brand, storage and metadata changes.
- Produces: Verified release candidate before irreversible external renames.

- [ ] **Step 1: Run formatting and full automated regression**

Run:

```powershell
python -m ruff check src tests
python -m pytest -q
npm --prefix frontend run build
npm --prefix frontend run smoke
docker compose --profile demo config --quiet
docker build -t zhishu-nexus:ci .
```

Expected: every command exits 0. Record test count and build output for final reporting.

- [ ] **Step 2: Start a local production-like app**

Start the existing local demo path or Vite dev server on an unused port. Verify login and API availability before taking screenshots.

- [ ] **Step 3: Verify desktop UI at 1440×900**

Check login page, loaded workspace, empty conversation and one assistant answer. Confirm complete branding, readable two-character marks, fixed composer, no overlap and no horizontal scrolling.

- [ ] **Step 4: Verify mobile UI at 390×844**

Check login, mobile header, conversation rail, empty state, assistant answer and composer. Confirm at least 44 px touch targets, recognizable “知枢” mark, no text clipping and no hidden answer content.

- [ ] **Step 5: Check git diff and commit verification fixes**

Run `git diff --check` and `git status --short`. If visual or regression fixes were required, commit only those fixes as:

```powershell
git add frontend/src frontend/index.html frontend/smoke tests/test_frontend_conversation_contract.py
git commit -m "fix: polish zhishu brand presentation"
```

---

### Task 5: Rename GitHub Repository And Local Directory

**Files:**
- External GitHub repository metadata.
- Local folder path.

**Interfaces:**
- Consumes: Fully verified and committed release candidate.
- Produces: `https://github.com/xingxing-1031/zhishu-nexus` and `E:\qiuzhaoxiangmu\zhishu-nexus`.

- [ ] **Step 1: Push verified commits before renaming**

Run: `git push origin main`

Expected: push succeeds and old repository main contains all rebrand commits.

- [ ] **Step 2: Confirm GitHub authentication and repository privacy**

Run:

```powershell
gh auth status
gh repo view xingxing-1031/retail-analytics-agent --json name,isPrivate,defaultBranchRef
```

Expected: authenticated account has admin permission, repository is private and default branch is `main`.

- [ ] **Step 3: Rename the GitHub repository**

Run:

```powershell
gh api --method PATCH repos/xingxing-1031/retail-analytics-agent -f name=zhishu-nexus
gh repo view xingxing-1031/zhishu-nexus --json name,url,isPrivate,defaultBranchRef
```

Expected: name is `zhishu-nexus`, URL is the new URL, repository remains private and branch remains `main`.

- [ ] **Step 4: Update and verify local origin**

Run:

```powershell
git remote set-url origin https://github.com/xingxing-1031/zhishu-nexus.git
git remote -v
git ls-remote --heads origin main
```

Expected: both fetch/push URLs are new and `main` resolves.

- [ ] **Step 5: Rename the local directory from its parent**

From `E:\qiuzhaoxiangmu`, verify both exact paths, then run:

```powershell
Rename-Item -LiteralPath 'E:\qiuzhaoxiangmu\retail-analytics-agent' -NewName 'zhishu-nexus'
```

Expected: old path is absent and `E:\qiuzhaoxiangmu\zhishu-nexus\.git` exists. Do not recursively move or delete any other path.

- [ ] **Step 6: Verify repository state at the new path**

Run:

```powershell
git -C E:\qiuzhaoxiangmu\zhishu-nexus status --short --branch
git -C E:\qiuzhaoxiangmu\zhishu-nexus remote -v
```

Expected: `main...origin/main`, no uncommitted files, new origin URL.

---

### Task 6: Deploy And Verify Production

**Files:**
- No additional source changes unless release verification finds a real defect.

**Interfaces:**
- Consumes: Renamed GitHub repository and unchanged VPS compatibility directory.
- Produces: Public “知枢 Nexus” workspace at `http://106.52.176.63/`.

- [ ] **Step 1: Verify GitHub Actions after repository rename**

Run:

```powershell
gh run list --repo xingxing-1031/zhishu-nexus --branch main --limit 10
```

Expected: CI and Deploy VPS release workflows for the rebrand commit finish with `success`. If the rename did not trigger a new deployment, dispatch the existing deploy workflow for `main`.

- [ ] **Step 2: Verify health and readiness**

Run:

```powershell
Invoke-RestMethod http://106.52.176.63/health
Invoke-RestMethod http://106.52.176.63/ready
```

Expected: health reports `ok` and readiness reports `ready`.

- [ ] **Step 3: Verify public HTML and core flows**

Open `http://106.52.176.63/` and confirm the page title, login page, analyst login, new conversation, general answer and business analysis use the new brand without functional regressions.

- [ ] **Step 4: Final repository audit**

Run:

```powershell
git -C E:\qiuzhaoxiangmu\zhishu-nexus status --short --branch
gh repo view xingxing-1031/zhishu-nexus --json name,url,isPrivate,defaultBranchRef
```

Expected: local and GitHub names match, repository is private, `main` is synchronized and the worktree is clean.
