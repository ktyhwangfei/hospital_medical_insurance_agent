# Semantic Layer Home Redesign Implementation Plan

> **For implementers:** Execute this plan task-by-task with checkbox tracking.

**Goal:** Rebuild the `/semantic-layer` home page into a polished light medical dashboard with a stronger hero overview, clearer information hierarchy, and more purposeful action entry cards without changing API behavior.

**Architecture:** Keep all data fetching inside `app/semantic-layer/page.tsx`, but reorganize the page into three visual zones: hero overview, ranked domain progress, and action entry cards. Polish the shared semantic-layer shell in `app/semantic-layer/layout.tsx` so the page header and tab strip match the upgraded dashboard styling while preserving the existing routes and navigation behavior.

**Tech Stack:** Next.js 16 App Router, React 19, Tailwind CSS v4, shadcn/ui, Vitest, Testing Library

---

## File Structure

- Modify: `src/apps/portal/app/semantic-layer/page.tsx`
  - Keep API fetching and loading/error states
  - Add derived presentation data for hero copy, stat cards, ranked domains, and quick action cards
  - Replace the current flat card stack with the new light medical dashboard layout
- Modify: `src/apps/portal/app/semantic-layer/layout.tsx`
  - Upgrade the shell background, page header block, and tabs so the home page styling feels intentional and consistent
- Create: `src/apps/portal/src/tests/semantic-layer/semantic-layer-page.test.tsx`
  - Regression test for the new hero overview, domain ranking text, and action-card copy
- Create: `src/apps/portal/src/tests/semantic-layer/semantic-layer-layout.test.tsx`
  - Regression test for the upgraded shell header and navigation tabs

### Task 1: Add Homepage Regression Tests

**Files:**
- Create: `src/apps/portal/src/tests/semantic-layer/semantic-layer-page.test.tsx`

- [ ] **Step 1: Write the failing dashboard test**

```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import SemanticLayerDashboard from '@/app/semantic-layer/page'

const summaryPayload = {
  domains_count: 3,
  objects_count: 12,
  metrics_count: 48,
  mapped_count: 37,
  unmapped_count: 11,
  mapping_rate: 77.1,
  skill_references: 9,
  domain_progress: [
    {
      domain_code: 'settlement',
      name: '医保结算',
      total_metrics: 22,
      mapped_metrics: 20,
      percentage: 90.9,
    },
    {
      domain_code: 'review',
      name: '审核规则',
      total_metrics: 14,
      mapped_metrics: 10,
      percentage: 71.4,
    },
    {
      domain_code: 'drg',
      name: '病种分组',
      total_metrics: 12,
      mapped_metrics: 7,
      percentage: 58.3,
    },
  ],
}

describe('SemanticLayerDashboard', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => summaryPayload,
      }),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the redesigned overview hero and ranked domain copy', async () => {
    render(<SemanticLayerDashboard />)

    expect(await screen.findByText('语义资产工作台')).toBeInTheDocument()
    expect(screen.getByText('优先处理未映射指标')).toBeInTheDocument()
    expect(screen.getByText('77.1%')).toBeInTheDocument()
    expect(screen.getByText('TOP 1 领域')).toBeInTheDocument()
    expect(screen.getByText('医保结算')).toBeInTheDocument()
    expect(screen.getByText('20 / 22 项指标已映射')).toBeInTheDocument()
  })

  it('renders upgraded action cards with operational labels', async () => {
    render(<SemanticLayerDashboard />)

    expect(await screen.findByText('进入域管理')).toBeInTheDocument()
    expect(screen.getByText('继续完善业务域与语义对象')).toBeInTheDocument()
    expect(screen.getByText('处理映射任务')).toBeInTheDocument()
    expect(screen.getByText('扫描新增字段')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- src/tests/semantic-layer/semantic-layer-page.test.tsx`

Expected: FAIL because the current page does not render `语义资产工作台` and the new action-card copy does not exist yet.

- [ ] **Step 3: Add the presentation data needed by the new layout**

Modify `src/apps/portal/app/semantic-layer/page.tsx` by inserting these derived values after `rankedDomains`:

```tsx
  const topDomain = rankedDomains[0] ?? null

  const statCards = [
    {
      label: '领域数',
      value: data.domains_count,
      tone: 'text-sky-700',
      hint: '按业务场景组织语义模型',
    },
    {
      label: '对象数',
      value: data.objects_count,
      tone: 'text-cyan-700',
      hint: '语义对象持续完善中',
    },
    {
      label: '指标数',
      value: data.metrics_count,
      tone: 'text-violet-700',
      hint: '核心业务口径已沉淀',
    },
    {
      label: '技能引用',
      value: data.skill_references,
      tone: 'text-amber-700',
      hint: '服务下游推理与导办链路',
    },
  ] as const

  const actionCards = [
    {
      href: '/semantic-layer/domain',
      title: '进入域管理',
      description: '继续完善业务域与语义对象',
      meta: `${data.domains_count} 个业务域`,
      icon: Building2,
      iconWrap: 'bg-sky-100 text-sky-700',
      borderTone: 'hover:border-sky-300',
    },
    {
      href: '/semantic-layer/mapping',
      title: '处理映射任务',
      description: '聚焦未映射指标与关系修正',
      meta: `${data.unmapped_count} 项待处理`,
      icon: Link2,
      iconWrap: 'bg-emerald-100 text-emerald-700',
      borderTone: 'hover:border-emerald-300',
    },
    {
      href: '/semantic-layer/discovery',
      title: '扫描新增字段',
      description: '发现新增字段并快速建立指标',
      meta: `${data.metrics_count} 项总指标`,
      icon: Search,
      iconWrap: 'bg-violet-100 text-violet-700',
      borderTone: 'hover:border-violet-300',
    },
  ] as const
```

- [ ] **Step 4: Run the test again to verify it still fails on missing UI**

Run: `npm run test -- src/tests/semantic-layer/semantic-layer-page.test.tsx`

Expected: FAIL, but now the failure should point to missing rendered UI text instead of missing variables.

- [ ] **Step 5: Commit the regression test scaffold**

```bash
git add src/apps/portal/src/tests/semantic-layer/semantic-layer-page.test.tsx src/apps/portal/app/semantic-layer/page.tsx
git commit -m "test: add semantic layer homepage redesign coverage"
```

### Task 2: Implement the Redesigned Homepage

**Files:**
- Modify: `src/apps/portal/app/semantic-layer/page.tsx`
- Test: `src/apps/portal/src/tests/semantic-layer/semantic-layer-page.test.tsx`

- [ ] **Step 1: Replace the current page body with the new light medical dashboard layout**

Replace the existing `return (` block in `src/apps/portal/app/semantic-layer/page.tsx` with:

```tsx
  return (
    <div className="flex flex-col gap-8">
      <section className="relative overflow-hidden rounded-[32px] border border-white/70 bg-[linear-gradient(135deg,rgba(255,255,255,0.96),rgba(246,250,252,0.88))] p-6 shadow-[0_24px_60px_rgba(15,46,74,0.10)] backdrop-blur xl:p-8">
        <div aria-hidden className="pointer-events-none absolute inset-0">
          <div className="absolute left-0 top-0 h-40 w-40 rounded-full bg-cyan-200/30 blur-3xl" />
          <div className="absolute bottom-0 right-0 h-48 w-48 rounded-full bg-sky-200/30 blur-3xl" />
        </div>

        <div className="relative grid gap-5 xl:grid-cols-[1.35fr_0.65fr]">
          <div className="space-y-5">
            <div className="inline-flex items-center gap-2 rounded-full border border-cyan-200/70 bg-cyan-50/80 px-3 py-1 text-xs font-semibold tracking-[0.18em] text-cyan-800">
              SEMANTIC OVERVIEW
            </div>

            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <h3 className="text-3xl font-semibold tracking-tight text-slate-950 xl:text-[2.15rem]">
                  语义资产工作台
                </h3>
                <Badge variant="outline" className="border-sky-200 bg-white/75 text-sky-700">
                  映射健康度 {data.mapping_rate.toFixed(1)}%
                </Badge>
              </div>
              <p className="max-w-3xl text-sm leading-7 text-slate-600 xl:text-[15px]">
                以语义域、对象和指标为中心查看当前建设进度，优先定位未映射指标与高价值业务域，让语义层首页从数据列表升级为真正可操作的资产总览。
              </p>
            </div>

            <div className="grid gap-4 md:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
              <div className="rounded-[28px] border border-sky-100 bg-white/78 p-5 shadow-[0_18px_45px_rgba(37,99,235,0.08)]">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="space-y-2">
                    <div className="text-xs font-semibold tracking-[0.18em] text-slate-500">
                      映射总览
                    </div>
                    <div className="flex items-end gap-3">
                      <span className="font-mono text-5xl font-bold leading-none tracking-tight text-sky-700">
                        {data.mapping_rate.toFixed(1)}%
                      </span>
                      <span className="pb-1 text-sm text-slate-500">
                        已映射 {data.mapped_count} / 总计 {data.metrics_count}
                      </span>
                    </div>
                  </div>

                  <div className="rounded-2xl border border-amber-100 bg-amber-50/80 px-4 py-3 text-sm text-amber-800">
                    <div className="font-semibold">优先处理未映射指标</div>
                    <div className="mt-1 text-amber-700">{data.unmapped_count} 项待处理</div>
                  </div>
                </div>

                <div className="mt-5">
                  <Progress value={data.mapping_rate} className="h-3">
                    <ProgressTrack className="h-3 bg-slate-200/90">
                      <ProgressIndicator className="bg-[linear-gradient(90deg,#0ea5e9,#2563eb)]" />
                    </ProgressTrack>
                  </Progress>
                </div>

                <div className="mt-5 grid gap-3 sm:grid-cols-3">
                  <div className="rounded-2xl bg-slate-50/90 px-4 py-3">
                    <div className="text-xs font-medium text-slate-500">已映射</div>
                    <div className="mt-1 font-mono text-2xl font-semibold text-slate-900">
                      {data.mapped_count}
                    </div>
                  </div>
                  <div className="rounded-2xl bg-slate-50/90 px-4 py-3">
                    <div className="text-xs font-medium text-slate-500">未映射</div>
                    <div className="mt-1 font-mono text-2xl font-semibold text-amber-700">
                      {data.unmapped_count}
                    </div>
                  </div>
                  <div className="rounded-2xl bg-slate-50/90 px-4 py-3">
                    <div className="text-xs font-medium text-slate-500">总指标</div>
                    <div className="mt-1 font-mono text-2xl font-semibold text-slate-900">
                      {data.metrics_count}
                    </div>
                  </div>
                </div>
              </div>

              <div className="rounded-[28px] border border-slate-200/80 bg-white/72 p-5 shadow-[0_18px_45px_rgba(15,23,42,0.06)]">
                <div className="text-xs font-semibold tracking-[0.18em] text-slate-500">
                  TOP 1 领域
                </div>

                {topDomain ? (
                  <div className="mt-4 space-y-4">
                    <div>
                      <Link
                        href={`/semantic-layer/domain/${topDomain.domain_code}`}
                        className="text-xl font-semibold tracking-tight text-slate-900 transition-colors hover:text-sky-700"
                      >
                        {topDomain.name}
                      </Link>
                      <p className="mt-2 text-sm leading-6 text-slate-600">
                        {topDomain.mapped_metrics} / {topDomain.total_metrics} 项指标已映射，当前完成度 {topDomain.percentage.toFixed(1)}%，适合作为优先展示的成熟业务域。
                      </p>
                    </div>

                    <div className="rounded-2xl bg-slate-50/90 p-4">
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-slate-500">建设完成度</span>
                        <span className={`font-semibold ${textColor(topDomain.percentage)}`}>
                          {topDomain.percentage.toFixed(0)}%
                        </span>
                      </div>
                      <Progress value={topDomain.percentage} className="mt-3">
                        <ProgressTrack className="bg-slate-200">
                          <ProgressIndicator className={progressBarColor(topDomain.percentage)} />
                        </ProgressTrack>
                      </Progress>
                    </div>
                  </div>
                ) : (
                  <p className="mt-4 text-sm text-slate-500">暂无可展示的领域建设数据</p>
                )}
              </div>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1">
            {statCards.map((item) => (
              <Card
                key={item.label}
                className="rounded-[24px] border border-white/80 bg-white/78 shadow-[0_16px_38px_rgba(15,23,42,0.06)]"
              >
                <CardHeader className="pb-1">
                  <CardTitle className="text-sm font-medium text-slate-500">{item.label}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <div className={`text-4xl font-bold tracking-tight ${item.tone}`}>
                    {item.value}
                  </div>
                  <p className="text-sm text-slate-500">{item.hint}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      <Card className="rounded-[30px] border border-white/75 bg-white/80 shadow-[0_20px_55px_rgba(15,23,42,0.06)]">
        <CardHeader className="flex flex-col gap-2 border-b border-slate-100 pb-5">
          <CardTitle className="text-lg text-slate-900">领域建设进度</CardTitle>
          <p className="text-sm leading-6 text-slate-500">
            按完成度排序查看当前语义域建设情况，优先关注高价值域与待补齐域。
          </p>
        </CardHeader>
        <CardContent className="space-y-3 pt-6">
          {rankedDomains.length === 0 ? (
            <p className="text-sm text-slate-500">暂无领域数据</p>
          ) : (
            rankedDomains.map((domain, index) => (
              <div
                key={domain.domain_code}
                className="rounded-[22px] border border-slate-100 bg-slate-50/80 px-4 py-4 transition-colors hover:border-sky-200 hover:bg-white"
              >
                <div className="flex flex-col gap-4 md:flex-row md:items-center">
                  <div className="flex min-w-0 items-center gap-4">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-sky-100 text-sm font-semibold text-sky-700">
                      {index + 1}
                    </span>
                    <div className="min-w-0">
                      <Link
                        href={`/semantic-layer/domain/${domain.domain_code}`}
                        className="text-base font-semibold text-slate-900 transition-colors hover:text-sky-700"
                      >
                        {domain.name}
                      </Link>
                      <p className="mt-1 text-sm text-slate-500">
                        {domain.mapped_metrics} / {domain.total_metrics} 项指标已映射
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-1 items-center gap-3 md:justify-end">
                    <div className="min-w-0 flex-1 md:max-w-md">
                      <Progress value={domain.percentage}>
                        <ProgressTrack className="bg-slate-200">
                          <ProgressIndicator className={progressBarColor(domain.percentage)} />
                        </ProgressTrack>
                      </Progress>
                    </div>
                    <Badge variant="outline" className={badgeStyle(domain.percentage)}>
                      {domain.percentage.toFixed(0)}%
                    </Badge>
                  </div>
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {actionCards.map((item) => {
          const Icon = item.icon

          return (
            <Link key={item.href} href={item.href}>
              <Card
                className={`group h-full rounded-[26px] border border-white/80 bg-white/82 shadow-[0_18px_44px_rgba(15,23,42,0.06)] transition-all duration-200 hover:-translate-y-1 hover:shadow-[0_24px_60px_rgba(37,99,235,0.12)] ${item.borderTone}`}
              >
                <CardContent className="flex h-full flex-col gap-5 px-5 py-5">
                  <div className="flex items-start justify-between gap-4">
                    <div className={`flex h-12 w-12 items-center justify-center rounded-2xl ${item.iconWrap}`}>
                      <Icon className="h-5 w-5" />
                    </div>
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-500">
                      {item.meta}
                    </span>
                  </div>

                  <div className="space-y-2">
                    <div className="text-lg font-semibold tracking-tight text-slate-900">
                      {item.title}
                    </div>
                    <p className="text-sm leading-6 text-slate-500">{item.description}</p>
                  </div>

                  <div className="mt-auto text-sm font-medium text-sky-700">
                    立即进入 →
                  </div>
                </CardContent>
              </Card>
            </Link>
          )
        })}
      </div>
    </div>
  )
```

- [ ] **Step 2: Run the homepage test to verify the redesign passes**

Run: `npm run test -- src/tests/semantic-layer/semantic-layer-page.test.tsx`

Expected: PASS, with both test cases green.

- [ ] **Step 3: Validate the page visually in the app**

Run: `npm run dev`

Then open: `http://127.0.0.1:3000/semantic-layer`

Expected:
- The page opens with a large hero card labeled `语义资产工作台`
- `映射总览` is visually dominant
- The top-ranked domain block appears on the right side of the hero
- The quick entry cards read `进入域管理` / `处理映射任务` / `扫描新增字段`

- [ ] **Step 4: Commit the homepage redesign**

```bash
git add src/apps/portal/app/semantic-layer/page.tsx
git commit -m "feat: redesign semantic layer homepage dashboard"
```

### Task 3: Polish the Semantic Layer Shell

**Files:**
- Create: `src/apps/portal/src/tests/semantic-layer/semantic-layer-layout.test.tsx`
- Modify: `src/apps/portal/app/semantic-layer/layout.tsx`
- Test: `src/apps/portal/src/tests/semantic-layer/semantic-layer-layout.test.tsx`

- [ ] **Step 1: Write the failing shell test**

```tsx
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import SemanticLayerLayout from '@/app/semantic-layer/layout'

vi.mock('next/navigation', () => ({
  usePathname: () => '/semantic-layer',
  useRouter: () => ({ push: vi.fn() }),
}))

describe('SemanticLayerLayout', () => {
  it('renders the upgraded shell header and tabs', () => {
    render(
      <SemanticLayerLayout>
        <div>dashboard body</div>
      </SemanticLayerLayout>,
    )

    expect(screen.getByText('语义资产工作台')).toBeInTheDocument()
    expect(screen.getByText('映射健康度与建设进度')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '概览' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '映射' })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the layout test to verify it fails**

Run: `npm run test -- src/tests/semantic-layer/semantic-layer-layout.test.tsx`

Expected: FAIL because the current shell does not render `语义资产工作台` or `映射健康度与建设进度`.

- [ ] **Step 3: Update the shell copy and container styling**

In `src/apps/portal/app/semantic-layer/layout.tsx`, update the tab header metadata:

```tsx
const TAB_HEADERS: Record<string, TabHeader> = {
  '/semantic-layer': {
    badge: '语义层总览',
    breadcrumb: '数据模型 / 指标映射 / 字段发现',
    title: '语义资产工作台',
    description: '映射健康度与建设进度集中呈现，帮助你快速定位成熟业务域与待完善指标。',
    icon: LayoutDashboard,
  },
  '/semantic-layer/domain': {
    badge: '业务域',
    breadcrumb: '数据模型 / 业务域',
    title: '域管理',
    description: '按业务场景维护语义对象、口径与模型边界。',
    icon: Building2,
  },
  '/semantic-layer/mapping': {
    badge: '映射中心',
    breadcrumb: '数据模型 / 字段映射',
    title: '映射任务中心',
    description: '追踪映射关系、处理未映射指标并保证语义口径一致。',
    icon: Link2,
  },
  '/semantic-layer/discovery': {
    badge: '字段发现',
    breadcrumb: '数据模型 / 字段发现',
    title: '发现中心',
    description: '扫描新增字段并快速建立指标，持续扩展语义资产覆盖面。',
    icon: Search,
  },
}
```

Then replace the shell wrapper and header JSX with:

```tsx
  return (
    <div className="relative min-h-screen">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(14,165,233,0.14),transparent_28%),radial-gradient(circle_at_bottom_right,rgba(37,99,235,0.10),transparent_30%),linear-gradient(180deg,#f8fbfd_0%,#eef4f7_100%)]" />
        <div className="absolute inset-0 opacity-[0.35] [background-image:linear-gradient(to_right,rgba(15,23,42,0.045)_1px,transparent_1px),linear-gradient(to_bottom,rgba(15,23,42,0.045)_1px,transparent_1px)] [background-size:42px_42px]" />
      </div>

      <main className="mx-auto flex w-full max-w-[1240px] flex-col gap-6 px-6 py-6">
        <Tabs value={currentTab} onValueChange={handleTabChange}>
          <div className="rounded-[28px] border border-white/80 bg-white/72 p-4 shadow-[0_18px_52px_rgba(15,23,42,0.06)] backdrop-blur">
            <div className="mb-5 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="inline-flex h-8 items-center rounded-full border border-cyan-200/70 bg-cyan-50 px-3 text-xs font-semibold tracking-[0.18em] text-cyan-800">
                    {TAB_HEADERS[currentTab].badge}
                  </span>
                  <span className="text-xs text-slate-500">
                    {TAB_HEADERS[currentTab].breadcrumb}
                  </span>
                </div>

                <div className="space-y-2">
                  <h2 className="text-2xl font-semibold tracking-tight text-slate-950">
                    {TAB_HEADERS[currentTab].title}
                  </h2>
                  <p className="max-w-3xl text-sm leading-6 text-slate-600">
                    {TAB_HEADERS[currentTab].description}
                  </p>
                </div>
              </div>

              <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                <TAB_HEADERS[currentTab].icon className="h-4 w-4 text-sky-700" />
                当前模块
              </div>
            </div>

            <TabsList
              variant="line"
              className="h-auto w-full justify-start gap-2 rounded-[20px] border border-slate-200/80 bg-slate-50/80 p-1"
            >
              {NAV_TABS.map((tab) => (
                <TabsTrigger
                  key={tab.href}
                  value={tab.href}
                  className="rounded-2xl px-4 py-2.5 text-sm font-medium text-slate-500 data-[active]:bg-white data-[active]:text-slate-900 data-[active]:shadow-sm data-[active]:after:opacity-0"
                >
                  {tab.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>

          <TabsContent value={currentTab} className="mt-0 outline-none">
            {children}
          </TabsContent>
        </Tabs>
      </main>
    </div>
  )
```

- [ ] **Step 4: Run both semantic-layer tests**

Run: `npm run test -- src/tests/semantic-layer/semantic-layer-page.test.tsx src/tests/semantic-layer/semantic-layer-layout.test.tsx`

Expected: PASS, both files green.

- [ ] **Step 5: Commit the shell polish**

```bash
git add src/apps/portal/app/semantic-layer/layout.tsx src/apps/portal/src/tests/semantic-layer/semantic-layer-layout.test.tsx
git commit -m "feat: polish semantic layer shell styling"
```

### Task 4: Final Verification

**Files:**
- Modify: none
- Test: `src/apps/portal/src/tests/semantic-layer/semantic-layer-page.test.tsx`
- Test: `src/apps/portal/src/tests/semantic-layer/semantic-layer-layout.test.tsx`

- [ ] **Step 1: Run the full targeted portal test pass**

Run: `npm run test -- src/tests/semantic-layer/semantic-layer-page.test.tsx src/tests/semantic-layer/semantic-layer-layout.test.tsx`

Expected: PASS, 3 total tests green.

- [ ] **Step 2: Run the app and verify the live page**

Run: `npm run dev`

Open:
- `http://127.0.0.1:3000/semantic-layer`
- `http://127.0.0.1:3000/semantic-layer/domain`
- `http://127.0.0.1:3000/semantic-layer/mapping`
- `http://127.0.0.1:3000/semantic-layer/discovery`

Expected:
- Home page hero is visually dominant and airy
- Home page quick entry cards feel like actions instead of default links
- The shell header and tab strip remain visually consistent across all semantic-layer routes
- No loading, navigation, or hydration errors appear in the browser console

- [ ] **Step 3: Commit the verification pass**

```bash
git add src/apps/portal/app/semantic-layer/page.tsx src/apps/portal/app/semantic-layer/layout.tsx src/apps/portal/src/tests/semantic-layer/semantic-layer-page.test.tsx src/apps/portal/src/tests/semantic-layer/semantic-layer-layout.test.tsx
git commit -m "chore: verify semantic layer redesign"
```
