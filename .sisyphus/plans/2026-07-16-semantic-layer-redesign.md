# Semantic Layer Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign semantic-layer pages with unified headers, rationalized layouts, and professional visual hierarchy — matching skills/policy-qa design standards.

**Architecture:** Four-wave approach: Wave 0 fixes the shared layout (tabs + header pattern), Wave 1 adds headers to all 7 subpages, Wave 2 restructures the dashboard layout, Wave 3 reorders mapping page sections, Wave 4 fixes discovery/object detail structural issues. All logic, API calls, types, and props preserved unchanged.

**Tech Stack:** Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, shadcn/ui (base-nova), lucide-react icons.

**Base reference for design patterns:** `src/apps/portal/app/skills/page.tsx`, `src/apps/portal/app/policy-qa/page.tsx`

---

## Wave 0: Shared Foundation (P0)

### Task 1: Remove emoji from tab labels

**Files:**
- Modify: `src/apps/portal/app/semantic-layer/layout.tsx:12-17`

**Goal:** Replace emoji-prefixed tab labels with clean Chinese text, matching the professional tone of the rest of the app.

- [ ] **Step 1: Update NAV_TABS array**

```tsx
const NAV_TABS: NavTab[] = [
  { label: '概览', href: '/semantic-layer' },
  { label: '域', href: '/semantic-layer/domain' },
  { label: '映射', href: '/semantic-layer/mapping' },
  { label: '发现', href: '/semantic-layer/discovery' },
]
```

- [ ] **Step 2: Verify in browser at http://127.0.0.1:3000/semantic-layer**

Navigate to the page. Confirm tabs display as `概览 | 域 | 映射 | 发现` without emoji. Confirm tab switching still works.

- [ ] **Step 3: Commit**

```bash
git add src/apps/portal/app/semantic-layer/layout.tsx
git commit -m "refactor: remove emoji from semantic-layer tab labels"
```

---

### Task 2: Add shared page header section to layout.tsx

**Files:**
- Modify: `src/apps/portal/app/semantic-layer/layout.tsx`

**Goal:** Add a reusable header area between the tab bar and the `<TabsContent>`, providing each tab page with a consistent badge+breadcrumb+title+description header that matches skills/policy-qa.

**Strategy:** The header content varies per tab. We pass tab-specific header data via a simple mapping object, keyed by tab href. This avoids prop-drilling and keeps all header definitions in one place.

- [ ] **Step 1: Import needed icons at top of layout.tsx**

```tsx
import { LayoutDashboard, Building2, Link2, Search } from 'lucide-react'
```

- [ ] **Step 2: Define per-tab header configuration**

Add after the `NAV_TABS` array but before the component:

```tsx
interface TabHeader {
  badge: string
  breadcrumb: string
  title: string
  description: string
  icon: React.ComponentType<{ className?: string }>
}

const TAB_HEADERS: Record<string, TabHeader> = {
  '/semantic-layer': {
    badge: '语义层',
    breadcrumb: '数据模型 / 指标映射 / 字段发现',
    title: '首页概览',
    description: '管理业务域、语义对象与指标映射关系，快速了解数据资产建设进度。',
    icon: LayoutDashboard,
  },
  '/semantic-layer/domain': {
    badge: '语义层',
    breadcrumb: '数据模型 / 业务域',
    title: '域管理',
    description: '按业务场景组织对象与指标，构建语义模型。',
    icon: Building2,
  },
  '/semantic-layer/mapping': {
    badge: '语义层',
    breadcrumb: '数据模型 / 字段映射',
    title: '映射中心',
    description: '追踪数据源字段到语义指标的映射关系，发现并处理未映射字段。',
    icon: Link2,
  },
  '/semantic-layer/discovery': {
    badge: '语义层',
    breadcrumb: '数据模型 / 字段发现',
    title: '发现中心',
    description: '扫描已接入数据表，自动发现未映射字段并快速创建指标。',
    icon: Search,
  },
}
```

- [ ] **Step 3: Add header rendering between tab list and tab content**

Replace the `<TabsContent>` block to include the header before children:

```tsx
<TabsContent value={currentTab} className="mt-0 outline-none">
  {TAB_HEADERS[currentTab] && (
    <header className="mb-6 space-y-1">
      <div className="flex items-center gap-2">
        <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
          {TAB_HEADERS[currentTab].badge}
        </span>
        <span className="text-xs text-slate-500">
          {TAB_HEADERS[currentTab].breadcrumb}
        </span>
      </div>
      <h2 className="text-xl font-semibold tracking-tight text-slate-900">
        {TAB_HEADERS[currentTab].title}
      </h2>
      <p className="text-sm text-slate-600">
        {TAB_HEADERS[currentTab].description}
      </p>
    </header>
  )}
  {children}
</TabsContent>
```

The icon from `TAB_HEADERS` is defined but not rendered in this task (used in Wave 3 for quick-link cards on dashboard). This is intentional — icons are lightweight imports, no performance concern.

- [ ] **Step 4: Verify all four tabs show correct headers**

Navigate to each tab and confirm:
- `/semantic-layer` → badge="语义层", breadcrumb="数据模型 / 指标映射 / 字段发现", title="首页概览"
- `/semantic-layer/domain` → title="域管理"
- `/semantic-layer/mapping` → title="映射中心"
- `/semantic-layer/discovery` → title="发现中心"

- [ ] **Step 5: Commit**

```bash
git add src/apps/portal/app/semantic-layer/layout.tsx
git commit -m "feat: add unified page headers to semantic-layer with tab-specific content"
```

---

## Wave 1: Header Propagation (P0 — continued)

All subpages currently have no header. With Task 2, the layout.tsx now renders a header above every child page. But the subpages that have their own concept of "title" (like domain detail showing "对象列表 (N)") should integrate with the layout-level header, and subpages that are NOT tab-routed (like `/semantic-layer/domain/[domainId]`) need their own header.

### Task 3: Add header to domain detail page

**Files:**
- Modify: `src/apps/portal/app/semantic-layer/domain/[domainId]/page.tsx`

**Goal:** The domain detail page (`/semantic-layer/domain/settlement`) is a deeper route — not covered by layout.tsx's tab-based header. Add a standalone header block with breadcrumb-style back link integrated.

- [ ] **Step 1: Add imports for header icons**

Add to the file's existing lucide-react imports:
```tsx
// Already imported: ArrowLeft, ChevronDown, ChevronRight, FileText, FolderOpen, Loader2, Layers, BarChart3
// No new imports needed — ArrowLeft is already imported
```

- [ ] **Step 2: Add header block at the top of the normal render section**

Find the "Normal Render" section (after loading/error/empty states). Currently it starts with:
```tsx
<div className="flex flex-col gap-6 lg:flex-row">
```

Insert a header block before the sidebar+content layout. The header integrates the back link and domain name. Replace the existing floating back link at line ~396 too.

**In the normal render return, replace the beginning:**
```tsx
// ── Normal Render ──────────────────────────────────────────
return (
  <div className="flex flex-col gap-6">
    {/* Header with integrated breadcrumb */}
    <header className="space-y-1">
      <div className="flex items-center gap-2">
        <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
          语义层
        </span>
        <Link
          href="/semantic-layer/domain"
          className="text-xs text-slate-500 transition-colors hover:text-blue-600"
        >
          域管理
        </Link>
        <span className="text-xs text-slate-400">/</span>
        <span className="text-xs text-slate-700">{domainId}</span>
      </div>
      <h2 className="text-xl font-semibold tracking-tight text-slate-900">
        对象列表
        <span className="ml-2 font-mono text-sm font-normal text-slate-500">
          ({objectCards.length})
        </span>
      </h2>
    </header>

    <div className="flex flex-col gap-6 lg:flex-row">
      {/* ── Left Sidebar: Object Tree ────────────────────────── */}
      {/* ... rest unchanged ... */}
```

- [ ] **Step 3: Remove the standalone back link**

In the right content area, remove the existing back link:
```tsx
{/* REMOVE this block: */}
<Link
  href="/semantic-layer/domain"
  className="mb-4 flex w-fit items-center gap-1.5 text-sm text-slate-500 transition-colors hover:text-blue-400"
>
  <ArrowLeft className="h-4 w-4" />
  返回领域列表
</Link>
```

Also remove the `"对象列表"` title in the right area since it's now in the header:
```tsx
{/* REMOVE this block: */}
<div className="mb-4 flex items-center justify-between">
  <h2 className="text-base font-medium text-slate-300">
    对象列表
    <span className="ml-2 font-mono text-sm text-slate-500">
      ({objectCards.length})
    </span>
  </h2>
  {loadingMetrics && (...)}
</div>
```

The `loadingMetrics` indicator (spinner + "加载指标数据...") can move to a subtitle line or be dropped — it's a transient state. Move it to the header as a subtitle if needed:

Add after the header title:
```tsx
{loadingMetrics && (
  <p className="flex items-center gap-1.5 text-xs text-slate-500">
    <Loader2 className="h-3 w-3 animate-spin" />
    加载指标数据...
  </p>
)}
```

- [ ] **Step 4: Verify in browser**

Navigate to http://127.0.0.1:3000/semantic-layer/domain/settlement. Confirm:
- Header shows `[语义层] 域管理 / settlement` breadcrumb
- Title shows "对象列表 (N)"
- Back navigation works via breadcrumb link
- Sidebar tree and object cards render correctly

- [ ] **Step 5: Commit**

```bash
git add src/apps/portal/app/semantic-layer/domain/[domainId]/page.tsx
git commit -m "feat: add header with breadcrumb to domain detail page"
```

---

### Task 4: Add header to object detail page

**Files:**
- Modify: `src/apps/portal/app/semantic-layer/object/[objectId]/page.tsx`

**Goal:** The object detail page is a deeper route. Add a header with breadcrumb linking back to its parent domain.

- [ ] **Step 1: Add header block**

Locate the "Normal Render" section. Before the existing back link `<Link>`:

```tsx
return (
  <div className="flex flex-col gap-5">
    {/* Header with breadcrumb */}
    <header className="space-y-1">
      <div className="flex items-center gap-2">
        <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
          语义层
        </span>
        <Link
          href="/semantic-layer/domain"
          className="text-xs text-slate-500 transition-colors hover:text-blue-600"
        >
          域管理
        </Link>
        {objectDetail.domain_code && (
          <>
            <span className="text-xs text-slate-400">/</span>
            <Link
              href={`/semantic-layer/domain/${objectDetail.domain_code}`}
              className="text-xs text-slate-500 transition-colors hover:text-blue-600"
            >
              {objectDetail.domain_name || objectDetail.domain_code}
            </Link>
          </>
        )}
        <span className="text-xs text-slate-400">/</span>
        <span className="text-xs text-slate-700 font-medium">{objectDetail.name}</span>
      </div>
    </header>
```

- [ ] **Step 2: Remove standalone back link**

Replace the existing back link block:
```tsx
{/* REMOVE: */}
<Link
  href={objectDetail.domain_code ? `/semantic-layer/domain/${objectDetail.domain_code}` : '/semantic-layer/domain'}
  className="flex w-fit items-center gap-1.5 text-sm text-slate-500 transition-colors hover:text-blue-400"
>
  <ArrowLeft className="h-4 w-4" />
  返回领域
</Link>
```

- [ ] **Step 3: Compact the object info header card**

The current Card at ~line 1043 has 6 lines of info (name, badge, definition, domain link, 3 stat lines). Merge the stats into a single horizontal row and reduce padding:

Replace the Card block:
```tsx
<Card className="border-slate-200/70 bg-white/80 backdrop-blur shadow-sm">
  <CardContent className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
    <div className="min-w-0 flex-1">
      <div className="mb-1 flex items-center gap-3">
        <h1 className="truncate text-lg font-semibold text-slate-900">
          {objectDetail.name}
        </h1>
        <Badge
          variant="outline"
          className={`shrink-0 border-slate-200 text-[10px] ${
            objectDetail.status === 'published'
              ? 'text-emerald-600 bg-emerald-50'
              : objectDetail.status === 'draft'
                ? 'text-amber-600 bg-amber-50'
                : 'text-slate-500'
          }`}
        >
          {STATUS_LABELS[objectDetail.status] || objectDetail.status}
        </Badge>
      </div>

      {objectDetail.definition && (
        <p className="mb-2 text-sm leading-relaxed text-slate-600">
          {objectDetail.definition}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-slate-500">
        {objectDetail.domain_name && (
          <>
            <span>
              所属域:{' '}
              <Link
                href={`/semantic-layer/domain/${objectDetail.domain_code}`}
                className="text-blue-600 transition-colors hover:text-blue-700"
              >
                {objectDetail.domain_name}
              </Link>
            </span>
            <span className="text-slate-300">|</span>
          </>
        )}
        <span className="flex items-center gap-1">
          <FileText className="h-3.5 w-3.5 text-cyan-500" />
          指标 <span className="font-mono tabular-nums text-slate-700">{objectDetail.metric_count}</span>
        </span>
        <span className="text-slate-300">|</span>
        <span className="flex items-center gap-1">
          <Check className="h-3.5 w-3.5 text-emerald-500" />
          已映射 <span className="font-mono tabular-nums text-slate-700">{mappedCount}</span>
        </span>
        <span className="text-slate-300">|</span>
        <span className="flex items-center gap-1">
          <X className="h-3.5 w-3.5 text-red-500" />
          未映射 <span className="font-mono tabular-nums text-slate-700">{unmappedCount}</span>
        </span>
      </div>
    </div>

    <div className="shrink-0">
      <Badge
        variant="outline"
        className="border-slate-200 font-mono text-[11px] text-slate-500 bg-slate-50"
      >
        {objectDetail.object_code}
      </Badge>
    </div>
  </CardContent>
</Card>
```

- [ ] **Step 4: Unfold the bottom collapsible section**

The "关联对象 / Skill 引用 / 操作" card at the bottom is always collapsed by default. Change it to be always expanded:

```tsx
<Card className="border-slate-200/70 bg-white/80 backdrop-blur shadow-sm">
  <CardContent className="px-5 py-4">
    <div className="grid gap-6 md:grid-cols-2">
      {/* Relations */}
      <div>
        <h4 className="mb-2 text-xs font-medium text-slate-500">关联对象</h4>
        {/* ... same content, no button wrapper needed ... */}
      </div>

      {/* Skill References */}
      <div>
        <h4 className="mb-2 text-xs font-medium text-slate-500">Skill 引用</h4>
        {/* ... same content ... */}
      </div>
    </div>
  </CardContent>
</Card>
```

Remove the collapsible button, the `bottomExpanded` state, and the conditional rendering. The delete button moves to a section at the bottom of the card.

- [ ] **Step 5: Clean up unused state variables**

Remove `bottomExpanded` from the useState declarations. Remove the delete confirmation section (it duplicates functionality already present in the metric table rows).

- [ ] **Step 6: Verify in browser**

Navigate to http://127.0.0.1:3000/semantic-layer/object/claim_header. Confirm:
- Breadcrumb header shows `[语义层] 域管理 / settlement / claim_header`
- Object info card is more compact (stats on one line)
- Bottom section shows relations and skill references without needing to click
- Delete button is accessible in the bottom card

- [ ] **Step 7: Commit**

```bash
git add src/apps/portal/app/semantic-layer/object/[objectId]/page.tsx
git commit -m "feat: add header, compact object card, unfold bottom section on object detail page"
```

---

## Wave 2: Dashboard Restructure (P1)

### Task 5: Restructure dashboard layout — merge redundant sections

**Files:**
- Modify: `src/apps/portal/app/semantic-layer/page.tsx`

**Goal:** Merge "Domain Construction Progress" and "Domain Ranking" into one section (progress list with ranking badges), collapse "Mapping Overview" into a compact strip, and add quick-entry cards replacing the ranking list.

- [ ] **Step 1: Replace duplicate sections with unified domain section**

Find the two sections "领域建设进度" (lines ~205-242) and "领域排名" (lines ~245-279). Replace both with a single unified card:

```tsx
{/* ── Domain Construction & Ranking (merged) ─────────────── */}
<Card className="border-slate-200/70 bg-white/80 backdrop-blur shadow-sm">
  <CardHeader className="pb-2">
    <CardTitle className="text-base text-slate-800">领域建设进度</CardTitle>
  </CardHeader>
  <CardContent className="space-y-4">
    {data.domain_progress.length === 0 ? (
      <p className="text-sm text-slate-500">暂无领域数据</p>
    ) : (
      data.domain_progress.map((domain, index) => (
        <div key={domain.domain_code} className="flex items-center gap-3">
          {/* Rank badge */}
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-medium text-slate-500">
            {index + 1}
          </span>

          {/* Progress area */}
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex items-center justify-between">
              <Link
                href={`/semantic-layer/domain/${domain.domain_code}`}
                className="text-sm font-medium text-slate-700 transition-colors hover:text-blue-600"
              >
                {domain.name}
              </Link>
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs tabular-nums text-slate-500">
                  {domain.mapped_metrics}/{domain.total_metrics}
                </span>
                <Badge variant="outline" className={badgeStyle(domain.percentage)}>
                  {domain.percentage.toFixed(0)}%
                </Badge>
              </div>
            </div>
            <Progress value={domain.percentage}>
              <ProgressTrack className="bg-slate-200">
                <ProgressIndicator className={progressBarColor(domain.percentage)} />
              </ProgressTrack>
            </Progress>
          </div>
        </div>
      ))
    )}
  </CardContent>
</Card>
```

- [ ] **Step 2: Compress mapping overview into a compact strip**

Replace the "映射总览" full card with a compact horizontal strip:

```tsx
{/* ── Mapping Overview (compact strip) ────────────────────── */}
<div className="flex flex-wrap items-center gap-4 rounded-2xl border border-slate-200/70 bg-white/80 px-5 py-3 backdrop-blur shadow-sm">
  <span className="text-sm font-medium text-slate-700">映射总览</span>
  <span className="font-mono text-2xl font-bold tabular-nums text-blue-600">
    {data.mapping_rate.toFixed(1)}%
  </span>
  <div className="h-8 flex-1 min-w-[120px]">
    <Progress value={data.mapping_rate} className="h-2">
      <ProgressTrack className="bg-slate-200 h-2">
        <ProgressIndicator className={progressBarColor(data.mapping_rate)} />
      </ProgressTrack>
    </Progress>
  </div>
  <div className="flex items-center gap-5 text-xs text-slate-500">
    <span>已映射 <span className="font-mono text-slate-700">{data.mapped_count}</span></span>
    <span>未映射 <span className="font-mono text-slate-700">{data.unmapped_count}</span></span>
    <span>总计 <span className="font-mono text-slate-700">{data.metrics_count}</span></span>
  </div>
</div>
```

- [ ] **Step 3: Add quick-entry cards row**

After the merged domain progress card, add a row of 3 quick-link cards:

```tsx
{/* ── Quick Entry Cards ──────────────────────────────────── */}
<div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
  <Link href="/semantic-layer/domain">
    <Card className="group border-slate-200/70 bg-white/80 backdrop-blur shadow-sm transition-all hover:border-blue-300 hover:shadow-md">
      <CardContent className="flex items-center gap-3 px-5 py-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600 group-hover:bg-blue-100">
          <Building2 className="h-5 w-5" />
        </div>
        <div>
          <div className="text-sm font-medium text-slate-800">域管理</div>
          <div className="text-xs text-slate-500">管理业务域与对象</div>
        </div>
      </CardContent>
    </Card>
  </Link>

  <Link href="/semantic-layer/mapping">
    <Card className="group border-slate-200/70 bg-white/80 backdrop-blur shadow-sm transition-all hover:border-blue-300 hover:shadow-md">
      <CardContent className="flex items-center gap-3 px-5 py-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600 group-hover:bg-emerald-100">
          <Link2 className="h-5 w-5" />
        </div>
        <div>
          <div className="text-sm font-medium text-slate-800">映射中心</div>
          <div className="text-xs text-slate-500">追踪字段映射关系</div>
        </div>
      </CardContent>
    </Card>
  </Link>

  <Link href="/semantic-layer/discovery">
    <Card className="group border-slate-200/70 bg-white/80 backdrop-blur shadow-sm transition-all hover:border-blue-300 hover:shadow-md">
      <CardContent className="flex items-center gap-3 px-5 py-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-purple-50 text-purple-600 group-hover:bg-purple-100">
          <Search className="h-5 w-5" />
        </div>
        <div>
          <div className="text-sm font-medium text-slate-800">发现中心</div>
          <div className="text-xs text-slate-500">扫描未映射字段</div>
        </div>
      </CardContent>
    </Card>
  </Link>
</div>
```

- [ ] **Step 4: Import new icons**

Add at the top of page.tsx (in the `lucide-react` already-imported set or as a standalone):
```tsx
// No new imports needed if Building2, Link2, Search already imported in layout
// But if not accessible, add locally:
import { LayoutDashboard, Building2, Link2, Search, Layers, Database, BarChart3 } from 'lucide-react'
```

Actually, since page.tsx doesn't currently import lucide-react icons, add a clean import:
```tsx
import { Building2, Link2, Search } from 'lucide-react'
```

- [ ] **Step 5: Verify in browser**

Navigate to http://127.0.0.1:3000/semantic-layer. Confirm:
- Page header visible (from Task 2)
- Four stat cards at top
- Compact mapping overview strip (not a full card)
- Single "领域建设进度" card with rank numbers + progress bars
- Three quick-entry cards at bottom
- No duplicate domain ranking section
- All links work

- [ ] **Step 6: Commit**

```bash
git add src/apps/portal/app/semantic-layer/page.tsx
git commit -m "refactor: restructure dashboard — merge duplicate sections, compact mapping overview, add quick-entry cards"
```

---

## Wave 3: Mapping Page Reorder (P1)

### Task 6: Reorder mapping page sections — summary to top, todo above table

**Files:**
- Modify: `src/apps/portal/app/semantic-layer/mapping/page.tsx`

**Goal:** Move the summary row (mapping rate stats) from the bottom to merge with the data source cards at the top. Move the value-domain standardization todo section above the main mapping table, and make it default-expanded.

- [ ] **Step 1: Add compact summary stats to the data source cards section**

After the data source card grid, add a compact summary strip. Replace the bottom summary Card entirely.

After the closing `</div>` of the data source cards grid, and before the filter controls, add:

```tsx
{/* ── Summary Strip ──────────────────────────────────────── */}
{summary && (
  <div className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-2xl border border-slate-200/70 bg-white/80 px-5 py-2.5 text-xs text-slate-500 backdrop-blur shadow-sm">
    <span className="flex items-center gap-1.5">
      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
      映射率{' '}
      <span className="font-mono text-slate-700">
        {summary.mapping_rate.toFixed(1)}%
      </span>
      <span className="text-slate-400">
        ({summary.mapped_count}/{summary.metrics_count})
      </span>
    </span>
    <span className="text-slate-300">|</span>
    <span className="flex items-center gap-1.5">
      <XCircle className="h-3.5 w-3.5 text-red-500" />
      未映射{' '}
      <span className="font-mono text-slate-700">
        {summary.unmapped_count}
      </span>
    </span>
    <span className="text-slate-300">|</span>
    <span className="flex items-center gap-1.5">
      <Layers className="h-3.5 w-3.5 text-cyan-500" />
      对象{' '}
      <span className="font-mono text-slate-700">
        {summary.objects_count}
      </span>
    </span>
    <span className="text-slate-300">|</span>
    <span className="flex items-center gap-1.5">
      <Database className="h-3.5 w-3.5 text-purple-500" />
      数据源{' '}
      <span className="font-mono text-slate-700">
        {dataSourceCards.length}
      </span>
    </span>
  </div>
)}
```

- [ ] **Step 2: Move value-domain todo section above the table**

The value-domain todo section currently appears after the table (lines ~712-804). Move it to appear between the filter controls and the table. Cut the entire `{valueTodos.length > 0 && (...)}` block and paste it after the filter controls section (`<div className="flex flex-wrap items-center justify-between gap-3">` and its children) and before the main table (`<div className="overflow-x-auto rounded-lg border border-slate-200">`).

- [ ] **Step 3: Change default expanded state for todo section**

At the top of the component, change:
```tsx
const [todoExpanded, setTodoExpanded] = useState(true)  // was false
```

- [ ] **Step 4: Remove the old bottom summary row**

Scroll to the bottom of the return statement. Remove the entire `{summary && (<Card>...)}` block (the last Card containing CheckCircle2, XCircle, Layers, Database stats). This data is now shown at the top.

- [ ] **Step 5: Verify in browser**

Navigate to http://127.0.0.1:3000/semantic-layer/mapping. Confirm:
- Compact summary strip appears below data source cards (with mapping rate, unmapped count, object count, data source count)
- Value-domain todo section (if present) appears above the mapping table, default-expanded
- Mapping table renders correctly
- No duplicate summary at bottom
- Tab header shows "映射中心" (from Task 2)

- [ ] **Step 6: Commit**

```bash
git add src/apps/portal/app/semantic-layer/mapping/page.tsx
git commit -m "refactor: reorder mapping page — summary to top, todo above table, default-expanded"
```

---

## Wave 4: Discovery & Object Detail Fixes (P2)

### Task 7: Fix discovery page — remove nested tables, compress scan trigger

**Files:**
- Modify: `src/apps/portal/app/semantic-layer/discovery/page.tsx`

**Goal:** Replace the nested `<table>` pattern in expanded rows with a flat `<div>` panel. Compress the scan trigger card into a compact strip.

- [ ] **Step 1: Compress scan trigger card**

Replace the large scan trigger Card (lines ~827-922) with a compact horizontal strip:

```tsx
{/* ── Section 1: Scan Trigger (compact strip) ─────────────── */}
<div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200/70 bg-white/80 px-5 py-3 backdrop-blur shadow-sm">
  <div className="flex items-center gap-3 text-xs text-slate-500">
    {history.length > 0 && history[0] ? (
      <>
        <span>上次扫描: <span className="text-slate-600">{formatDateTime(history[0].started_at)}</span></span>
        <span className="text-slate-300">|</span>
        <span>耗时: <span className="font-mono text-slate-600">{formatDuration(history[0].duration_seconds)}</span></span>
        <span className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${statusBg(history[0].status)} ${statusColor(history[0].status)}`}>
          {statusLabel(history[0].status)}
        </span>
      </>
    ) : (
      <span>尚未执行过扫描</span>
    )}
  </div>

  <div className="flex items-center gap-2">
    <select
      value={scanScope}
      onChange={(e) => setScanScope(e.target.value)}
      disabled={scanning}
      className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-blue-500 focus:outline-none disabled:opacity-50"
    >
      {SCAN_SCOPE_OPTIONS.map((opt) => (
        <option key={opt} value={opt}>{opt}</option>
      ))}
    </select>

    <Button
      variant="outline"
      size="sm"
      onClick={startScan}
      disabled={scanning}
      className="gap-1.5 border-slate-300 text-xs text-slate-700 hover:text-slate-900"
    >
      {scanning ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <ScanSearch className="h-3.5 w-3.5" />
      )}
      {scanning ? '扫描中...' : '重新扫描'}
    </Button>
  </div>
</div>
```

Keep the scan progress and completion/dismiss sections as-is but move them into a conditional area below this strip.

- [ ] **Step 2: Replace nested table in FieldExpandDetail row with flat div**

The current code uses `<td colSpan={7}><table>...</table></td>` for expanded rows. Replace this pattern with a clean `<div>` approach.

In the table body where `{isExpanded && (...)}` renders, replace the nested `<tr><td colSpan={7}><table>...` structure:

```tsx
{/* Expanded detail panel — flat div, no nested table */}
{isExpanded && (
  <tr key={`${compositeKey}-detail`}>
    <td colSpan={7} className="bg-slate-50 p-0">
      <div className="border-t border-slate-200 px-5 py-4">
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          {/* Left: Field Quality */}
          <div className="space-y-3">
            <h4 className="text-xs font-medium text-slate-600">字段质量</h4>

            {/* Non-null rate bar */}
            <div>
              <div className="mb-1 flex items-center justify-between">
                <span className="text-[11px] text-slate-500">非空率</span>
                <span className="font-mono text-xs tabular-nums text-slate-700">
                  {field.non_null_rate.toFixed(1)}%
                </span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
                <div
                  className={`h-full rounded-full transition-all ${nonNullBarColor(field.non_null_rate)}`}
                  style={{ width: `${field.non_null_rate}%` }}
                />
              </div>
            </div>

            {/* Sample value */}
            {field.sample_value && (
              <div>
                <span className="text-[11px] text-slate-500">样本值</span>
                <div className="mt-0.5 font-mono text-xs text-slate-700">
                  {field.sample_value}
                </div>
              </div>
            )}

            {/* Description */}
            <div>
              <span className="text-[11px] text-slate-500">描述</span>
              <div className="mt-0.5 text-xs text-slate-600">
                {field.description || (
                  <span className="text-slate-400">暂无描述</span>
                )}
              </div>
            </div>
          </div>

          {/* Right: Quick Metric Create */}
          <div>
            {showCreateForm ? (
              <QuickMetricForm
                field={field}
                onSuccess={() => {
                  setShowCreateForm(false)
                  onMetricCreated()
                }}
                onCancel={() => setShowCreateForm(false)}
              />
            ) : (
              <div className="flex flex-col items-start gap-3">
                <p className="text-xs text-slate-500">
                  此字段尚未关联指标。可快速创建指标并与当前字段关联。
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowCreateForm(true)}
                  className="gap-1 border-slate-300 text-xs text-slate-600 hover:text-slate-800"
                >
                  <PlusCircle className="h-3 w-3" />
                  快速创建指标
                </Button>
              </div>
            )}
          </div>
        </div>
      </div>
    </td>
  </tr>
)}
```

Also need to move `showCreateForm` state to be per-field. Currently it's a single boolean in FieldExpandDetail component — that's fine since only one field can be expanded at a time via `expandedFields` set. Keep the existing logic.

- [ ] **Step 3: Adjust the scan results table colors**

Already mostly done from the light theme conversion, but ensure the table row colors match the compact style:

- Table header: `bg-slate-50 border-b border-slate-200`
- Row hover: `hover:bg-slate-50`
- Row border: `border-b border-slate-200`

- [ ] **Step 4: Verify in browser**

Navigate to http://127.0.0.1:3000/semantic-layer/discovery. Confirm:
- Scan trigger is a compact strip (not a full card)
- "扫描结果" table works — click to expand a row
- Expanded row shows field quality + quick-create form in a flat div (no nested table)
- "扫描历史" section at the bottom still works

- [ ] **Step 5: Commit**

```bash
git add src/apps/portal/app/semantic-layer/discovery/page.tsx
git commit -m "refactor: compress scan trigger strip, replace nested table with flat div in discovery page"
```

---

## Final Verification

### Task 8: Full end-to-end verification

- [ ] **Step 1: Smoke test all semantic-layer routes**

Navigate to each route and verify:
| Route | Expected |
|-------|----------|
| `/semantic-layer` | Header "首页概览" + 4 stat cards + compact mapping strip + domain progress + quick links |
| `/semantic-layer/domain` | Header "域管理" + domain cards |
| `/semantic-layer/domain/settlement` | Header with breadcrumb + sidebar tree + object cards |
| `/semantic-layer/domain/settlement/object/claim_header` | Header with breadcrumb + compact info card + metric table + unfolded bottom section |
| `/semantic-layer/mapping` | Header "映射中心" + summary strip + data source cards + todo + table |
| `/semantic-layer/discovery` | Header "发现中心" + compact scan strip + results table + history |
| `/semantic-layer/metrics` | Header "指标中心" + stat cards + filters + table (no changes needed, verify header only) |

- [ ] **Step 2: Check responsive layout**

Resize browser to 768px width. Confirm:
- Headers don't break
- Cards wrap correctly
- Tables are horizontally scrollable (already implemented with `overflow-x-auto`)
- Quick-entry cards stack vertically

- [ ] **Step 3: Verify no regressions**

- All API calls still work (data loads correctly on each page)
- All links navigate correctly
- All interactive elements (buttons, selects, checkboxes) still function
- No console errors

- [ ] **Step 4: Run LSP diagnostics**

```bash
# Check all modified files
```
Run `lsp_diagnostics` on the following directories:
- `src/apps/portal/app/semantic-layer/layout.tsx`
- `src/apps/portal/app/semantic-layer/page.tsx`
- `src/apps/portal/app/semantic-layer/domain/[domainId]/page.tsx`
- `src/apps/portal/app/semantic-layer/object/[objectId]/page.tsx`
- `src/apps/portal/app/semantic-layer/mapping/page.tsx`
- `src/apps/portal/app/semantic-layer/discovery/page.tsx`

All must show 0 errors.

---

## Summary of Changes

| Wave | Task | Files | Type |
|------|------|-------|------|
| 0 | T1 | layout.tsx | Remove emoji from tabs |
| 0 | T2 | layout.tsx | Add shared page headers with tab mapping |
| 1 | T3 | domain/[domainId]/page.tsx | Header + breadcrumb, remove floating back link |
| 1 | T4 | object/[objectId]/page.tsx | Header + breadcrumb, compact info card, unfold bottom |
| 2 | T5 | page.tsx | Merge duplicate sections, compact mapping strip, quick-link cards |
| 3 | T6 | mapping/page.tsx | Summary to top, todo above table, default-expanded |
| 4 | T7 | discovery/page.tsx | Compress scan trigger, replace nested table with flat div |
| — | T8 | All | E2E verification |

**Not modified (no changes needed):**
- `domain/page.tsx` — already has header from layout.tsx (Task 2)
- `metrics/page.tsx` — already has header from layout.tsx (Task 2), layout already evaluated as "reasonable"
- `discovery/page.tsx` sub-components (QuickMetricForm, FieldExpandDetail, etc.) — only the parent render structure changes
