import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SkillDetailPage from '../../app/skills/[skillId]/page'
import { ApiClientError } from '@/lib/types'

// 详情页通过 React 19 的 use(params) 解包 Next 16 的动态路由参数（Promise）。
// 测试环境下 use 对 Promise 首帧会 throw 并依赖 Suspense 恢复，RTL 不易 flush；
// 把 Promise 分支替换为同步返回已知路由参数，其余走原实现。
const ROUTE_PARAMS = vi.hoisted(() => ({ skillId: 'settlement_explain_skill' }))
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

const apiMocks = vi.hoisted(() => ({
  detail: vi.fn(),
  definition: vi.fn(),
  versions: vi.fn(),
  evalRuns: vi.fn(),
  releases: vi.fn(),
  copy: vi.fn(),
  disable: vi.fn(),
  restore: vi.fn(),
  archive: vi.fn(),
}))

vi.mock('@/lib/api-client', () => ({
  getInfraSkillDetail: (...a: unknown[]) => apiMocks.detail(...a),
  listInfraSkillVersions: (...a: unknown[]) => apiMocks.versions(...a),
  listSkillEvalRuns: (...a: unknown[]) => apiMocks.evalRuns(...a),
  listSkillReleases: (...a: unknown[]) => apiMocks.releases(...a),
}))

vi.mock('@/lib/skill-draft-api', () => ({
  getSkillDefinition: (...a: unknown[]) => apiMocks.definition(...a),
  copySkill: (...a: unknown[]) => apiMocks.copy(...a),
  disableSkill: (...a: unknown[]) => apiMocks.disable(...a),
  restoreSkill: (...a: unknown[]) => apiMocks.restore(...a),
  archiveSkill: (...a: unknown[]) => apiMocks.archive(...a),
}))

// next/navigation stub：记录 push 调用
const pushMock = vi.hoisted(() => vi.fn())
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
}))

const DETAIL = {
  skill_id: 'settlement_explain_skill',
  skill_name: '结算解释技能',
  manifest: {},
  readme: '',
  file_tree: [],
}

const DEFINITION = {
  skill_id: 'settlement_explain_skill',
  lifecycle_status: 'enabled',
  current_version_id: 'version-1',
  semantic_dependency_changed: false,
  revision: 3,
  business_action: 'explain',
  business_object: 'settlement',
  disabled_at: null,
  archived_at: null,
  updated_at: '2026-08-14T00:00:00Z',
}

const VERSIONS = [
  { version_id: 'version-abc12345', semantic_version: '1.2.0', validation_status: 'passed', created_at: '2026-08-10T00:00:00Z' },
  { version_id: 'version-def67890', semantic_version: '1.1.0', validation_status: 'pending', created_at: '2026-08-01T00:00:00Z' },
]

const EVAL_RUNS = {
  items: [
    { run_id: 'run-11112222', status: 'passed', created_at: '2026-08-12T00:00:00Z' },
    { run_id: 'run-33334444', status: 'failed', created_at: '2026-08-11T00:00:00Z' },
  ],
  total: 2,
}

const RELEASES = {
  items: [
    { release_id: 'rel-55556666', status: 'active', activated_at: '2026-08-13T00:00:00Z' },
  ],
  total: 1,
}

function renderPage() {
  // params 传任意已 resolve 的 Promise；use 已被 mock 为同步解包
  return render(<SkillDetailPage params={Promise.resolve(ROUTE_PARAMS)} />)
}

describe('Skill 详情页（/skills/[skillId]）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    pushMock.mockClear()
    apiMocks.detail.mockResolvedValue(DETAIL)
    apiMocks.definition.mockResolvedValue(DEFINITION)
    apiMocks.versions.mockResolvedValue(VERSIONS)
    apiMocks.evalRuns.mockResolvedValue(EVAL_RUNS)
    apiMocks.releases.mockResolvedValue(RELEASES)
  })

  afterEach(cleanup)

  it('加载并渲染版本记录、最近评测与发布记录', async () => {
    renderPage()

    expect(await screen.findByText('版本与发布')).toBeVisible()
    // 版本记录
    expect(screen.getByText('v1.2.0')).toBeVisible()
    expect(screen.getByText('v1.1.0')).toBeVisible()
    expect(screen.getByText('校验通过')).toBeVisible()
    // 最近评测
    expect(screen.getByText('run-1111')).toBeVisible()
    expect(screen.getByText('通过')).toBeVisible()
    expect(screen.getByText('未通过')).toBeVisible()
    // 发布记录
    expect(screen.getByText('rel-5555')).toBeVisible()
    expect(screen.getByText('active')).toBeVisible()
    // 并行加载全部触发
    expect(apiMocks.versions).toHaveBeenCalledWith('settlement_explain_skill')
    expect(apiMocks.evalRuns).toHaveBeenCalledWith('settlement_explain_skill')
    expect(apiMocks.releases).toHaveBeenCalledWith('settlement_explain_skill')
  })

  it('版本/评测/发布接口失败时页面主体仍正常渲染', async () => {
    apiMocks.versions.mockRejectedValue(new Error('not materialized'))
    apiMocks.evalRuns.mockRejectedValue(new Error('not materialized'))
    apiMocks.releases.mockRejectedValue(new Error('not materialized'))

    renderPage()

    expect(await screen.findByText('结算解释技能')).toBeVisible()
    expect(screen.getByText('暂无版本记录')).toBeVisible()
    expect(screen.getByText('暂无评测记录')).toBeVisible()
    expect(screen.getByText('暂无发布记录')).toBeVisible()
  })

  it('「创建新草稿」调 copySkill 并跳转到新草稿编辑器', async () => {
    const user = userEvent.setup()
    apiMocks.copy.mockResolvedValue({ draft_id: 'draft-new-1', skill_id: 'settlement_explain_skill_v2' })
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('settlement_explain_skill_v2')

    renderPage()
    await screen.findByText('结算解释技能')
    await user.click(screen.getByRole('button', { name: /创建新草稿/ }))

    await waitFor(() => {
      expect(apiMocks.copy).toHaveBeenCalledWith(
        { source_skill_id: 'settlement_explain_skill', new_skill_id: 'settlement_explain_skill_v2' },
        expect.stringContaining('settlement_explain_skill:copy:'),
      )
    })
    expect(pushMock).toHaveBeenCalledWith(
      '/skills/settlement_explain_skill_v2/edit?draft=draft-new-1',
    )
    promptSpy.mockRestore()
  })

  it('新 skill_id 与源相同时拒绝并提示', async () => {
    const user = userEvent.setup()
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('settlement_explain_skill')
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})

    renderPage()
    await screen.findByText('结算解释技能')
    await user.click(screen.getByRole('button', { name: /创建新草稿/ }))

    expect(apiMocks.copy).not.toHaveBeenCalled()
    expect(alertSpy).toHaveBeenCalled()
    promptSpy.mockRestore()
    alertSpy.mockRestore()
  })

  it('copySkill 失败时展示错误且不跳转', async () => {
    const user = userEvent.setup()
    apiMocks.copy.mockRejectedValue(
      new ApiClientError(409, { error_code: 'SKILL_DRAFT_CONFLICT', message: 'skill_id 已存在' }),
    )
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('existing_skill')

    renderPage()
    await screen.findByText('结算解释技能')
    await user.click(screen.getByRole('button', { name: /创建新草稿/ }))

    await waitFor(() => expect(screen.getByText(/skill_id 已存在/)).toBeVisible())
    expect(pushMock).not.toHaveBeenCalled()
    promptSpy.mockRestore()
  })
})
