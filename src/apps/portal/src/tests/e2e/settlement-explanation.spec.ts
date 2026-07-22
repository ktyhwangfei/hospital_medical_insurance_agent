/**
 * SettlementExplanationPage — Playwright E2E 测试
 *
 * 验证 SettlementExplanationPage 组件在 single 和 compare 两种模式下的渲染正确性。
 *
 * 测试策略：
 * - 使用 page.route() 拦截 API 请求，返回 mock 数据
 * - 不依赖真实后端 API，确保测试确定性
 * - 验证各子组件（ProfileCard / ConclusionArea / OutputGroupsSection / FeeComparisonTable 等）正确出现
 * - 截图保存到 test-results/ 目录
 */

import { test, expect } from '@playwright/test'
import type { SettlementExplanationData, OutputGroupValue, ProfileValue } from '../../lib/settlement-explanation-types'
import { MOCK_SETTLEMENT_EXPLANATION } from '../../lib/settlement-explanation-mock'

// ════════════════════════════════════════════════════════════════
// Compare 模式 mock 数据
// ════════════════════════════════════════════════════════════════

const PRIMARY_PROFILE: ProfileValue[] = [
  { field: 'person_type', label: '人员类别', value: '退休人员' },
  { field: 'insurance_type', label: '参保类型', value: '城镇职工基本医疗保险' },
  { field: 'service_type', label: '医疗类别', value: '普通住院' },
  { field: 'hospital_level', label: '医院等级', value: '三级' },
]

const SECONDARY_PROFILE: ProfileValue[] = [
  { field: 'person_type', label: '人员类别', value: '退休人员' },
  { field: 'insurance_type', label: '参保类型', value: '城镇职工基本医疗保险' },
  { field: 'service_type', label: '医疗类别', value: '普通住院' },
  { field: 'hospital_level', label: '医院等级', value: '二级' },
]

const PRIMARY_OUTPUT_GROUPS: OutputGroupValue[] = [
  {
    group: '医保帮您付的',
    items: [
      { label: '统筹基金支付', value: 91759.51, format: 'money' },
      { label: '大额基金支付', value: 53631.71, format: 'money' },
    ],
  },
  {
    group: '您个人承担的',
    items: [
      { label: '起付线', value: 650, format: 'money', hint: '报销门槛' },
      { label: '统筹自付', value: 4962.67, format: 'money', hint: '统筹段按比例', highlight: true },
      { label: '大额自付', value: 13407.93, format: 'money', hint: '大额段按比例' },
    ],
  },
  {
    group: '合计',
    items: [{ label: '个人总支付', value: 43694.64, format: 'money', hint: '以上合计' }],
  },
]

const SECONDARY_OUTPUT_GROUPS: OutputGroupValue[] = [
  {
    group: '医保帮您付的',
    items: [
      { label: '统筹基金支付', value: 85000.0, format: 'money' },
      { label: '大额基金支付', value: 48000.0, format: 'money' },
    ],
  },
  {
    group: '您个人承担的',
    items: [
      { label: '起付线', value: 650, format: 'money', hint: '报销门槛' },
      { label: '统筹自付', value: 3800.0, format: 'money', hint: '统筹段按比例', highlight: true },
      { label: '大额自付', value: 11000.0, format: 'money', hint: '大额段按比例' },
    ],
  },
  {
    group: '合计',
    items: [{ label: '个人总支付', value: 36150.0, format: 'money', hint: '以上合计' }],
  },
]

/**
 * Compare 模式数据：
 * - mode = 'compare'
 * - profile 为 CompareProfileSet[]（数组中每项含 label + items）
 * - output_groups 为 OutputGroupValue[][]（嵌套数组，第一维表示对比组）
 * - comparison.diff_summary 为差异摘要文本
 */
const MOCK_COMPARE_DATA: Record<string, unknown> = {
  ...MOCK_SETTLEMENT_EXPLANATION,
  question: '本次和上次的统筹自付对比',
  mode: 'compare',
  profile: [
    { label: '本次（2025年5月）', items: PRIMARY_PROFILE },
    { label: '上次（2025年3月）', items: SECONDARY_PROFILE },
  ],
  output_groups: [PRIMARY_OUTPUT_GROUPS, SECONDARY_OUTPUT_GROUPS],
  comparison: {
    diff_summary:
      '本次住院与上次相比，统筹自付增加了1,162.67元，主要原因是本次住院费用更高导致统筹段内个人负担增加。',
  },
}

// ════════════════════════════════════════════════════════════════
// Tests
// ════════════════════════════════════════════════════════════════

test.describe('SettlementExplanationPage — 展示模式', () => {
  const BASE_URL = 'http://127.0.0.1:3000'

  test.beforeEach(async ({ page }) => {
    // 导航到政策问答页面
    await page.goto(`${BASE_URL}/policy-qa`)
    await page.waitForLoadState('networkidle')
  })

  test('Single 模式：渲染参保信息卡片、费用分组表格和结论区域', async ({ page }) => {
    // ── 拦截 API 返回 single 模式 mock 数据 ──
    await page.route('**/policy-qa/settlement-explanation**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SETTLEMENT_EXPLANATION),
      })
    })

    // ── 填写表单并提交 ──
    await page.locator('input[placeholder*="例如 1671213"]').fill('1671213')
    await page.locator('input[placeholder*="统筹自付"]').fill('统筹自付为什么是 4962.67 元？')
    await page.locator('button:has-text("查询")').click()

    // ── 验证 ProfileCard ──
    await expect(page.locator('text=您的参保信息')).toBeVisible({ timeout: 15000 })
    await expect(page.locator('text=人员类别')).toBeVisible()
    await expect(page.locator('text=参保类型')).toBeVisible()
    await expect(page.locator('text=医疗类别')).toBeVisible()
    await expect(page.locator('text=医院等级')).toBeVisible()

    // ── 验证 ConclusionArea ──
    await expect(page.locator('text=AI 生成')).toBeVisible()
    await expect(page.locator('text=这 4,962.67 元')).toBeVisible()

    // ── 验证 OutputGroupsSection（费用分组表格） ──
    await expect(page.locator('text=医保帮您付的')).toBeVisible()
    await expect(page.locator('text=您个人承担的')).toBeVisible()
    await expect(page.locator('text=统筹基金支付')).toBeVisible()
    await expect(page.locator('text=大额基金支付')).toBeVisible()
    await expect(page.locator('text=统筹自付')).toBeVisible()

    // ── 验证 CollapsibleSection（政策依据 · 计算过程 默认折叠可见） ──
    await expect(page.locator('text=政策依据 · 计算过程')).toBeVisible()

    // ── 验证 WarningCard ──
    await expect(page.locator('text=重要提示')).toBeVisible()
    await expect(page.locator('text=统筹自付 ≠ 患者总自付')).toBeVisible()

    // ── 截图保存 ──
    await page.screenshot({ path: 'test-results/settlement-explanation-single.png', fullPage: true })
  })

  test('Compare 模式：渲染双栏对比展示', async ({ page }) => {
    // ── 拦截 API 返回 compare 模式 mock 数据 ──
    await page.route('**/policy-qa/settlement-explanation**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_COMPARE_DATA),
      })
    })

    // ── 填写表单并提交 ──
    await page.locator('input[placeholder*="例如 1671213"]').fill('1671213')
    await page.locator('input[placeholder*="统筹自付"]').fill('本次和上次的统筹自付对比')
    await page.locator('button:has-text("查询")').click()

    // ── 验证 CompareProfileSection（两栏对比卡片） ──
    await expect(page.locator('text=本次（2025年5月）')).toBeVisible({ timeout: 15000 })
    await expect(page.locator('text=上次（2025年3月）')).toBeVisible()
    // 两个 profile 卡片中都应出现"医院等级"（diff 字段有★标记）
    await expect(page.locator('text=医院等级')).toBeVisible()

    // ── 验证 DiffSummaryCard（差异摘要） ──
    await expect(page.locator('text=本次住院与上次相比')).toBeVisible()

    // ── 验证 FeeComparisonTable（费用对比表格） ──
    await expect(page.locator('text=费用对比')).toBeVisible()
    // 表格表头
    await expect(page.locator('text=本次')).toBeVisible()
    await expect(page.locator('text=上次')).toBeVisible()
    await expect(page.locator('text=差额')).toBeVisible()

    // ── 验证 CollapsibleSection ──
    await expect(page.locator('text=政策依据 · 计算过程')).toBeVisible()

    // ── 验证 DataTraceAccordion ──
    await expect(page.locator('text=数据追溯')).toBeVisible()

    // ── 截图保存 ──
    await page.screenshot({ path: 'test-results/settlement-explanation-compare.png', fullPage: true })
  })
})
