import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, cleanup, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import SkillEditorPage from '../../app/skills/[skillId]/edit/page'

// Mock next/navigation：编辑器读取 ?draft= 查询参数定位草稿
const routerPush = vi.hoisted(() => vi.fn())
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: routerPush }),
  useSearchParams: () => new URLSearchParams('draft=draft-verify'),
}))

// 编辑器通过 React 19 的 use(params) 解包 Next 16 的动态路由参数（Promise）。
// 测试环境下 use 对 Promise 首帧会 throw 并依赖 Suspense 恢复，RTL 不易 flush；
// 这里把 use 的 Promise 分支替换为同步返回已知路由参数，其余（Context 等）走原实现。
const ROUTE_PARAMS = vi.hoisted(() => ({ skillId: 'outpatient_settlement_verify_skill' }))
vi.mock('react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react')>()
  return {
    ...actual,
    use: (payload: unknown) => {
      if (payload && typeof (payload as { then?: unknown }).then === 'function') {
        return ROUTE_PARAMS
      }
      return actual.use(payload as never)
    },
  }
})

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

// 后端事实标准结构（draft_service._build_template_config / AI schema / package_generator）：
//   description/owner 存放在 structured_config.basic 内，
//   触发词存放在 business_mounting.include_keywords（excluded_intents 为排除意图）。
// 该草稿模拟「门诊结算结果核验」AI 创建后的落库形态。
const VERIFY_DRAFT = {
  draft_id: 'draft-verify',
  skill_id: 'outpatient_settlement_verify_skill',
  skill_name: '门诊结算结果核验',
  status: 'editing',
  source_type: 'ai_generated',
  structured_config: {
    basic: {
      skill_id: 'outpatient_settlement_verify_skill',
      skill_name: '门诊结算结果核验',
      description: '核验门诊医保结算的上下文、金额勾稽关系和待遇适用情况',
      owner: '医保办-张三',
    },
    business_mounting: {
      business_action: 'verify',
      business_object: 'settlement',
      include_keywords: ['门诊结算对不对', '门诊报销对不对', '核对门诊结算'],
      excluded_intents: ['退费', '冲正'],
    },
    inputs: [],
    schemas: {},
  },
  revision: 1,
  validation_blocking_ok: false,
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
  created_by: 'u',
}

describe('SkillEditorPage 回显（后端 basic + include_keywords 结构）', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    routerPush.mockReset()
  })

  it('回显 basic 中的说明、负责人，以及 business_mounting.include_keywords 触发词', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string) => {
        if (typeof url === 'string' && url.includes('/infra-skills/drafts/')) {
          return Promise.resolve(jsonResponse(VERIFY_DRAFT))
        }
        // 语义层 selector 允许返回空；编辑器内部已 catch 失败
        return Promise.resolve(jsonResponse({ tree: [] }))
      }),
    )

    render(
      <SkillEditorPage params={Promise.resolve({ skillId: 'outpatient_settlement_verify_skill' })} />,
    )

    // 修复前：编辑器读顶层 config.description / config.owner / bm.keywords，
    // 三者皆空；这些断言会失败（红）。修复后读取 basic.* / include_keywords（绿）。
    expect(
      await screen.findByDisplayValue(
        '核验门诊医保结算的上下文、金额勾稽关系和待遇适用情况',
      ),
    ).toBeInTheDocument()
    expect(screen.getByDisplayValue('医保办-张三')).toBeInTheDocument()
    expect(
      screen.getByDisplayValue('门诊结算对不对, 门诊报销对不对, 核对门诊结算'),
    ).toBeInTheDocument()
    expect(screen.getByDisplayValue('verify')).toBeInTheDocument()
    expect(screen.getByDisplayValue('settlement')).toBeInTheDocument()
  })

  it('编辑触发词后保存，写回 business_mounting.include_keywords（而非旧 keywords）', async () => {
    const user = userEvent.setup()
    let savedBody: {
      structured_config: {
        business_mounting: { include_keywords: string[]; keywords?: string[] }
      }
    } | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        if (
          typeof url === 'string' &&
          url.includes('/infra-skills/drafts/draft-verify') &&
          init?.method === 'PATCH'
        ) {
          savedBody = JSON.parse(String(init.body)) as typeof savedBody
          return Promise.resolve(jsonResponse({ ...VERIFY_DRAFT, revision: 2 }))
        }
        if (typeof url === 'string' && url.includes('/infra-skills/drafts/')) {
          return Promise.resolve(jsonResponse(VERIFY_DRAFT))
        }
        return Promise.resolve(jsonResponse({ tree: [] }))
      }),
    )

    render(
      <SkillEditorPage params={Promise.resolve({ skillId: 'outpatient_settlement_verify_skill' })} />,
    )

    await screen.findByDisplayValue('verify')
    // 定位触发词输入框：label「触发关键词（逗号分隔）」紧邻 input，容器内仅一个文本框
    const kwLabel = screen.getByText('触发关键词（逗号分隔）')
    const kwInput = within(kwLabel.parentElement!).getByRole('textbox')
    await user.clear(kwInput)
    await user.type(kwInput, '门诊结算核对')
    // dirty 后底部保存条出现，header 和保存条各有一个「保存」按钮，用 header 按钮保存
    await user.click(screen.getAllByText('保存')[0])

    // 修复前：编辑器把触发词写入已废弃的 bm.keywords，而包生成器只认 include_keywords，
    // 编辑结果不生效（原 include_keywords 仍是 3 个旧词）→ 断言失败（红）。
    expect(savedBody).toBeDefined()
    expect(savedBody!.structured_config.business_mounting.include_keywords).toEqual([
      '门诊结算核对',
    ])
    // 不应再向已废弃的 keywords 写入，避免与 include_keywords 双轨
    expect(savedBody!.structured_config.business_mounting.keywords).toBeUndefined()
  })

  it('底部保存条在 config 变更后出现，保存后消失', async () => {
    const user = userEvent.setup()
    let savedBody: unknown
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        if (
          typeof url === 'string' &&
          url.includes('/infra-skills/drafts/draft-verify') &&
          init?.method === 'PATCH'
        ) {
          savedBody = JSON.parse(String(init.body))
          return Promise.resolve(jsonResponse({ ...VERIFY_DRAFT, revision: 2 }))
        }
        if (typeof url === 'string' && url.includes('/infra-skills/drafts/')) {
          return Promise.resolve(jsonResponse(VERIFY_DRAFT))
        }
        return Promise.resolve(jsonResponse({ tree: [] }))
      }),
    )

    render(
      <SkillEditorPage params={Promise.resolve({ skillId: 'outpatient_settlement_verify_skill' })} />,
    )

    await screen.findByDisplayValue('verify')

    // 初始无修改：保存条不应出现
    expect(screen.queryByText('有未保存的修改')).not.toBeInTheDocument()

    // 修改触发词 → dirty
    const kwLabel = screen.getByText('触发关键词（逗号分隔）')
    const kwInput = within(kwLabel.parentElement!).getByRole('textbox')
    await user.clear(kwInput)
    await user.type(kwInput, '新触发词')

    // 保存条出现
    expect(await screen.findByText('有未保存的修改')).toBeInTheDocument()
    expect(screen.getByText('放弃修改')).toBeInTheDocument()

    // 点击保存条上的保存按钮（最后一个「保存」）
    const saveButtons = screen.getAllByText('保存')
    await user.click(saveButtons[saveButtons.length - 1])

    // 保存成功后保存条消失
    expect(screen.queryByText('有未保存的修改')).not.toBeInTheDocument()
    expect(savedBody).toBeDefined()
  })
})
