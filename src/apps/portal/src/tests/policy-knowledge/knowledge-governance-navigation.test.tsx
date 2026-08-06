import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import KnowledgeIndexPage from '../../../app/policy-knowledge/knowledge/page'
import KnowledgeBuildPage from '../../../app/policy-knowledge/knowledge/build/page'
import LegacyKnowledgeChangeSetPage from '../../../app/policy-knowledge/knowledge/change-sets/[changeSetId]/page'
import LegacyKnowledgeChangeSetsPage from '../../../app/policy-knowledge/knowledge/change-sets/page'
import LegacyKnowledgeDashboardPage from '../../../app/policy-knowledge/knowledge/dashboard/page'
import LegacyKnowledgeDecisionsPage from '../../../app/policy-knowledge/knowledge/decisions/page'
import LegacyKnowledgePublishedPage from '../../../app/policy-knowledge/knowledge/published/page'
import KnowledgeReviewPage from '../../../app/policy-knowledge/knowledge/review/page'
import KnowledgeReviewDetailPage from '../../../app/policy-knowledge/knowledge/review/[changeSetId]/page'
import KnowledgeReleasesPage from '../../../app/policy-knowledge/knowledge/releases/page'
import { WorkspaceNav } from '../../../app/policy-knowledge/knowledge/workspace-nav'
import {
  BuildContextBar,
  KnowledgeFlow,
} from '@/components/policy-knowledge/knowledge-governance-shared'
import { redirect, usePathname } from 'next/navigation'

vi.mock('next/navigation', () => ({
  redirect: vi.fn(() => {
    throw new Error('NEXT_REDIRECT')
  }),
  usePathname: vi.fn(),
  useRouter: vi.fn(() => ({ push: vi.fn(), refresh: vi.fn() })),
}))

vi.mock('@/components/policy-knowledge/knowledge-workbench', () => ({
  KnowledgeWorkbench: () => null,
}))

vi.mock('@/components/policy-knowledge/metric-draft-dialog', () => ({
  MetricDraftDialog: () => null,
}))

vi.mock('@/lib/api-context', () => ({
  useApiContext: vi.fn(() => ({ userId: 'demo' })),
}))

vi.mock('@/lib/policy-knowledge-api', () => ({
  PolicyKnowledgeApiError: class PolicyKnowledgeApiError extends Error {
    status = 500
  },
  approveChangeSet: vi.fn(),
  bindExistingMetric: vi.fn(),
  getActiveRelease: vi.fn().mockResolvedValue(null),
  getActiveSnapshot: vi.fn().mockResolvedValue(null),
  listTestCases: vi.fn(),
  getChangeSet: vi.fn().mockResolvedValue({
    change_set_id: 'CS_001',
    source_document_version_id: 'REV_001',
    doc_id: 'DOC_001',
    doc_title: '测试政策',
    build_task_id: 'TASK_001',
    source_units: [],
    semantic_contract_version: 'v1',
    supersedes_candidate_id: null,
    status: 'PENDING_REVIEW',
    summary: { additions: 0, modifications: 0, replacements: 0, expirations: 0, unchanged: 0 },
    items: [],
    quality_report: {
      source_fidelity: null,
      structural_completeness: null,
      semantic_consistency: null,
      rule_consistency: null,
    },
    risk_summary: {},
    blockers: [],
    review_decision: null,
    created_at: '2026-08-05T00:00:00Z',
    updated_at: '2026-08-05T00:00:00Z',
  }),
  getRuleDetail: vi.fn(),
  getWorkbenchDocument: vi.fn(),
  getWorkbenchDocuments: vi.fn().mockResolvedValue([]),
  listChangeSets: vi.fn().mockResolvedValue([]),
  listDecisionTasks: vi.fn().mockResolvedValue([]),
  listEligibleKnowledgeUnits: vi.fn().mockResolvedValue([]),
  listKnowledgeBuildTasks: vi.fn().mockResolvedValue([]),
  listPublishedSnapshots: vi.fn().mockResolvedValue([]),
  listReleases: vi.fn().mockResolvedValue([]),
  listSemanticMetrics: vi.fn().mockResolvedValue([]),
  proposeStandardValue: vi.fn(),
  rejectChangeSet: vi.fn(),
  resolveDecisionTask: vi.fn(),
  returnKnowledgeReview: vi.fn(),
  reviewKnowledge: vi.fn(),
}))

const mockedUsePathname = vi.mocked(usePathname)

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('knowledge workspace navigation', () => {
  it('exposes only the build, review, and release workspaces', () => {
    mockedUsePathname.mockReturnValue('/policy-knowledge/knowledge/build')

    render(<WorkspaceNav />)

    const navigation = screen.getByRole('navigation', { name: '知识治理工作区' })
    const links = within(navigation).getAllByRole('link')
    expect(links).toHaveLength(3)
    expect(within(navigation).getByRole('link', { name: '知识构建' })).toHaveAttribute(
      'href',
      '/policy-knowledge/knowledge/build',
    )
    expect(within(navigation).getByRole('link', { name: '知识审核' })).toHaveAttribute(
      'href',
      '/policy-knowledge/knowledge/review',
    )
    expect(within(navigation).getByRole('link', { name: '发布管理' })).toHaveAttribute(
      'href',
      '/policy-knowledge/knowledge/releases',
    )
    expect(navigation).not.toHaveTextContent(/驾驶舱|工作台|变更集|待决策/)
  })

  it.each([
    ['/policy-knowledge/knowledge/build', '知识构建'],
    ['/policy-knowledge/knowledge/build/history', '知识构建'],
    ['/policy-knowledge/knowledge/review', '知识审核'],
    ['/policy-knowledge/knowledge/review/CS_001', '知识审核'],
    ['/policy-knowledge/knowledge/releases', '发布管理'],
    ['/policy-knowledge/knowledge/releases/R_001', '发布管理'],
  ])('marks only the matching workspace active for %s', (pathname, activeLabel) => {
    mockedUsePathname.mockReturnValue(pathname)

    render(<WorkspaceNav />)

    const links = screen.getAllByRole('link')
    expect(links.filter((link) => link.getAttribute('aria-current') === 'page')).toHaveLength(1)
    expect(screen.getByRole('link', { name: activeLabel })).toHaveAttribute('aria-current', 'page')
  })
})

describe('knowledge route skeletons', () => {
  it('redirects the knowledge index to the build workspace on the server', () => {
    expect(() => render(<KnowledgeIndexPage />)).toThrow('NEXT_REDIRECT')

    expect(redirect).toHaveBeenCalledWith('/policy-knowledge/knowledge/build')
  })

  it.each([
    ['/policy-knowledge/knowledge/build', KnowledgeBuildPage, '知识构建', '知识构建'],
    ['/policy-knowledge/knowledge/review', KnowledgeReviewPage, '知识审核', '知识审核'],
    ['/policy-knowledge/knowledge/releases', KnowledgeReleasesPage, '发布管理', '发布正式版本'],
  ])(
    'renders %s with the shared compact skeleton',
    (pathname, Page, heading, currentStep) => {
      mockedUsePathname.mockReturnValue(pathname)

      render(<Page />)

      expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument()
      expect(screen.getByRole('navigation', { name: '知识治理工作区' })).toBeInTheDocument()
      expect(screen.getByRole('listitem', { name: `${currentStep}：当前` })).toHaveAttribute(
        'aria-current',
        'step',
      )
      expect(screen.getByText('本页只读')).toBeInTheDocument()
    },
  )

  it('renders a dynamic review detail using the Next 16 promise params contract', async () => {
    mockedUsePathname.mockReturnValue('/policy-knowledge/knowledge/review/CS_001')
    const page = await KnowledgeReviewDetailPage({
      params: Promise.resolve({ changeSetId: 'CS_001' }),
    })

    render(page)

    expect(screen.getByRole('heading', { name: '知识审核详情' })).toBeInTheDocument()
    expect(screen.getByText('CS_001')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '知识审核' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.getByRole('listitem', { name: '知识审核：当前' })).toHaveAttribute(
      'aria-current',
      'step',
    )
  })
})

describe('legacy knowledge route redirects', () => {
  it.each([
    ['dashboard', LegacyKnowledgeDashboardPage, '/policy-knowledge/knowledge/build'],
    ['change-set list', LegacyKnowledgeChangeSetsPage, '/policy-knowledge/knowledge/review'],
    ['decisions', LegacyKnowledgeDecisionsPage, '/policy-knowledge/knowledge/review?view=issues'],
    ['published', LegacyKnowledgePublishedPage, '/policy-knowledge/knowledge/releases'],
  ])('executes the %s server redirect to %s', (_name, Page, destination) => {
    expect(() => Page()).toThrow('NEXT_REDIRECT')
    expect(redirect).toHaveBeenCalledTimes(1)
    expect(redirect).toHaveBeenCalledWith(destination)
  })

  it('executes the dynamic change-set redirect after awaiting and encoding params', async () => {
    await expect(LegacyKnowledgeChangeSetPage({
      params: Promise.resolve({ changeSetId: 'cs/a b' }),
    })).rejects.toThrow('NEXT_REDIRECT')

    expect(redirect).toHaveBeenCalledTimes(1)
    expect(redirect).toHaveBeenCalledWith('/policy-knowledge/knowledge/review/cs%2Fa%20b')
  })

  it.each([
    ['app/policy-knowledge/knowledge/dashboard/page.tsx', '/policy-knowledge/knowledge/build'],
    ['app/policy-knowledge/knowledge/change-sets/page.tsx', '/policy-knowledge/knowledge/review'],
    ['app/policy-knowledge/knowledge/decisions/page.tsx', '/policy-knowledge/knowledge/review?view=issues'],
    ['app/policy-knowledge/knowledge/published/page.tsx', '/policy-knowledge/knowledge/releases'],
  ])('keeps %s only as a server redirect to %s', (sourcePath, destination) => {
    const source = readFileSync(resolve(process.cwd(), sourcePath), 'utf8')

    expect(source).not.toContain("'use client'")
    expect(source).toContain("import { redirect } from 'next/navigation'")
    expect(source).toContain(`redirect('${destination}')`)
  })

  it('redirects the legacy change-set detail with the Next 16 promise params contract', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'app/policy-knowledge/knowledge/change-sets/[changeSetId]/page.tsx'),
      'utf8',
    )

    expect(source).not.toContain("'use client'")
    expect(source).toContain("import { redirect } from 'next/navigation'")
    expect(source).toContain('params: Promise<{ changeSetId: string }>')
    expect(source).toContain('const { changeSetId } = await params')
    expect(source).toContain(
      "redirect(`/policy-knowledge/knowledge/review/${encodeURIComponent(changeSetId)}`)",
    )
  })
})

describe('knowledge governance shared context', () => {
  it('shows the compact five-stage flow with accessible state semantics', () => {
    const { container } = render(<KnowledgeFlow current="review" />)

    expect(container).toHaveTextContent(
      '文档接入 → 单元拆分与审核 → 知识构建 → 知识审核 → 发布正式版本',
    )
    expect(screen.getByRole('listitem', { name: '知识构建：已完成' })).toBeInTheDocument()
    expect(screen.getByRole('listitem', { name: '知识审核：当前' })).toHaveAttribute(
      'aria-current',
      'step',
    )
    expect(screen.getByRole('listitem', { name: '发布正式版本：后续' })).toBeInTheDocument()
  })

  it('shows readonly build context and honest missing-data fallbacks', () => {
    const { rerender } = render(
      <BuildContextBar availableUnitCount={12} semanticContractVersion="v2.3" />,
    )

    expect(screen.getByText('可用单元：12')).toBeInTheDocument()
    expect(screen.getByText('语义契约版本：v2.3')).toBeInTheDocument()
    expect(screen.getByText('本页只读')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看语义层' })).toHaveAttribute(
      'href',
      '/semantic-layer/metrics',
    )

    rerender(<BuildContextBar availableUnitCount={null} semanticContractVersion={null} />)
    expect(screen.getByText('可用单元：暂无统计')).toBeInTheDocument()
    expect(screen.getByText('语义契约版本：暂无版本')).toBeInTheDocument()
  })
})
