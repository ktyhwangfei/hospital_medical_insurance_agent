import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ReextractConfigDialog } from '../../components/policy-knowledge/reextract-config-dialog'
import {
  getExtractionConfig,
  listExtractionModels,
  reextractChangeSet,
  testExtractChangeSetItem,
  type ReextractReport,
} from '@/lib/policy-knowledge-api'

// 注：base-ui Dialog 在 jsdom 中以 Portal 渲染，userEvent 的指针命中检测会失效，
// 故本组件测试统一用 fireEvent 触发交互。
vi.mock('@/lib/api-context', () => ({
  useApiContext: vi.fn(() => ({ userId: 'rev1' })),
}))

vi.mock('@/lib/policy-knowledge-api', () => ({
  getExtractionConfig: vi.fn(),
  listExtractionModels: vi.fn(),
  getPromptPreview: vi.fn(),
  reextractChangeSet: vi.fn(),
  testExtractChangeSetItem: vi.fn(),
}))

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function resolvedConfig() {
  ;(getExtractionConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
    default_prompt_mode: 'schema',
    default_model: 'deepseek-chat',
    default_max_tokens: 8192,
    schema_version: 3,
    metrics: [
      { code: 'payment_ratio', name: '支付比例', kind: 'field', extraction_hint: '比例', value_domain: null },
      { code: 'deductible_amount', name: '起付金额', kind: 'field', extraction_hint: null, value_domain: null },
    ],
    note: 'schema 模式实时读指标',
  })
  ;(listExtractionModels as ReturnType<typeof vi.fn>).mockResolvedValue([
    { model_name: 'deepseek-chat', display_name: 'deepseek-chat', available: true },
  ])
}

function clickByText(text: string) {
  fireEvent.click(screen.getByText(text))
}

function successReport(): ReextractReport {
  return { change_set_id: 'CS_test', total: 1, succeeded: 1, failed: 0, items: [], override_applied: null }
}

describe('ReextractConfigDialog（迭代 19：诊断 + 测试 + 3步向导）', () => {
  beforeEach(resolvedConfig)

  it('第1步展示问题诊断：四类补救路径 + 缺失字段清单', async () => {
    render(
      <ReextractConfigDialog
        changeSetId="CS_test"
        scope={{ kind: 'single', itemId: 'ci_1', extractedFields: ['payment_ratio'] }}
        onClose={() => {}}
        onComplete={() => {}}
      />,
    )
    expect(await screen.findByText('问题诊断')).toBeInTheDocument()
    expect(screen.getByText('缺少指标')).toBeInTheDocument()
    expect(screen.getByText('有指标未提取出来')).toBeInTheDocument()
    expect(screen.getByText('怎么修改提示词都不行')).toBeInTheDocument()
    expect(screen.getByText('大模型质量差')).toBeInTheDocument()
    // 缺失字段诊断：契约有 deductible_amount 但候选只提取了 payment_ratio
    expect(await screen.findByText('deductible_amount')).toBeInTheDocument()
  })

  it('选择诊断路径后进入第2步可切换自定义提示词', async () => {
    render(
      <ReextractConfigDialog
        changeSetId="CS_test"
        scope={{ kind: 'single', itemId: 'ci_1' }}
        onClose={() => {}}
        onComplete={() => {}}
      />,
    )
    await screen.findByText('问题诊断')
    clickByText('有指标未提取出来')
    clickByText('下一步：配置与测试')
    expect(await screen.findByText('配置与测试')).toBeInTheDocument()
    expect(screen.getByDisplayValue('schema')).toBeInTheDocument()
  })

  it('第2步展示动态加载指标 + schema 模式默认', async () => {
    render(
      <ReextractConfigDialog
        changeSetId="CS_test"
        scope={{ kind: 'single', itemId: 'ci_1' }}
        onClose={() => {}}
        onComplete={() => {}}
      />,
    )
    await screen.findByText('问题诊断')
    clickByText('下一步：配置与测试')
    // 指标动态加载：契约指标展示
    expect(await screen.findByText('payment_ratio')).toBeInTheDocument()
    expect(screen.getByText(/当前契约版本 v3/)).toBeInTheDocument()
    const schemaRadio = screen.getByDisplayValue('schema') as HTMLInputElement
    expect(schemaRadio.checked).toBe(true)
  })

  it('修改2：测试提取不落库预览（调用 testExtractChangeSetItem）', async () => {
    ;(testExtractChangeSetItem as ReturnType<typeof vi.fn>).mockResolvedValue({
      change_set_id: 'CS_test', item_id: 'ci_1', extraction_id: 'ext_1',
      fact_count: 1, rule_count: 2, fields_extracted: ['payment_ratio', 'psn_type'],
      facts: [{ fact_text: '退休人员支付60%', rules: [{ payment_ratio: '60%' }] }],
      override_applied: { prompt_mode: 'schema', operator: 'rev1' },
    })
    render(
      <ReextractConfigDialog
        changeSetId="CS_test"
        scope={{ kind: 'single', itemId: 'ci_1' }}
        onClose={() => {}}
        onComplete={() => {}}
      />,
    )
    await screen.findByText('问题诊断')
    clickByText('下一步：配置与测试')
    await screen.findByText('payment_ratio')

    clickByText('测试提取')

    await waitFor(() => {
      expect(testExtractChangeSetItem).toHaveBeenCalledWith(
        'CS_test',
        expect.objectContaining({
          item_id: 'ci_1',
          override: expect.objectContaining({ prompt_mode: 'schema' }),
        }),
      )
    })
    expect(await screen.findByText(/提取 1 条事实/)).toBeInTheDocument()
    expect(screen.getByText('psn_type')).toBeInTheDocument()
  })

  it('custom 模式提交时携带 custom_prompt（3步后提交）', async () => {
    ;(reextractChangeSet as ReturnType<typeof vi.fn>).mockResolvedValue(successReport())
    render(
      <ReextractConfigDialog
        changeSetId="CS_test"
        scope={{ kind: 'single', itemId: 'ci_1' }}
        onClose={() => {}}
        onComplete={() => {}}
      />,
    )
    await screen.findByText('问题诊断')
    clickByText('下一步：配置与测试')
    await screen.findByText('payment_ratio')

    fireEvent.click(screen.getByDisplayValue('custom'))
    fireEvent.change(screen.getByLabelText('自定义提示词'), {
      target: { value: '请提取起付线 {title} {text}' },
    })
    clickByText('下一步：提交确认')
    await screen.findByText('提交确认')
    clickByText('开始重新提取')

    await waitFor(() => {
      expect(reextractChangeSet).toHaveBeenCalledWith(
        'CS_test',
        expect.objectContaining({
          item_ids: ['ci_1'],
          override: expect.objectContaining({
            prompt_mode: 'custom',
            custom_prompt: '请提取起付线 {title} {text}',
          }),
        }),
      )
    })
  })

  it('schema 批量提交不带 custom_prompt，可用默认模型', async () => {
    ;(reextractChangeSet as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...successReport(), total: 2,
    } satisfies ReextractReport)
    render(
      <ReextractConfigDialog
        changeSetId="CS_test"
        scope={{ kind: 'batch', itemIds: ['ci_1', 'ci_2'] }}
        onClose={() => {}}
        onComplete={() => {}}
      />,
    )
    await screen.findByText('问题诊断')
    clickByText('下一步：配置与测试')
    await screen.findByText('payment_ratio')
    clickByText('下一步：提交确认')
    await screen.findByText('提交确认')
    clickByText('开始重新提取')

    await waitFor(() => {
      expect(reextractChangeSet).toHaveBeenCalledWith(
        'CS_test',
        expect.objectContaining({ item_ids: ['ci_1', 'ci_2'] }),
      )
    })
    const override = (reextractChangeSet as ReturnType<typeof vi.fn>).mock.calls[0][1].override
    expect(override.prompt_mode).toBe('schema')
    expect(override.custom_prompt).toBeUndefined()
    expect(override.model_name).toBeUndefined()
  })

  it('部分失败时展示失败项并提供仅重试失败项', async () => {
    ;(reextractChangeSet as ReturnType<typeof vi.fn>).mockResolvedValue({
      change_set_id: 'CS_test', total: 2, succeeded: 1, failed: 1,
      items: [
        { extraction_id: 'ext_1', item_ids: ['ci_1'], success: true, new_knowledge_count: 1 },
        { extraction_id: 'ext_2', item_ids: ['ci_2'], success: false, error: 'LLM 未返回结果', new_knowledge_count: 0 },
      ],
      override_applied: null,
    } satisfies ReextractReport)
    render(
      <ReextractConfigDialog
        changeSetId="CS_test"
        scope={{ kind: 'batch', itemIds: ['ci_1', 'ci_2'] }}
        onClose={() => {}}
        onComplete={() => {}}
      />,
    )
    await screen.findByText('问题诊断')
    clickByText('下一步：配置与测试')
    await screen.findByText('payment_ratio')
    clickByText('下一步：提交确认')
    await screen.findByText('提交确认')
    clickByText('开始重新提取')

    expect(await screen.findByText(/成功 1 \/ 2/)).toBeInTheDocument()
    expect(screen.getByText('仅重试失败 1 条')).toBeInTheDocument()
  })

  it('全部成功后调用 onComplete 并显示完成按钮', async () => {
    ;(reextractChangeSet as ReturnType<typeof vi.fn>).mockResolvedValue(successReport())
    const onComplete = vi.fn()
    render(
      <ReextractConfigDialog
        changeSetId="CS_test"
        scope={{ kind: 'single', itemId: 'ci_1' }}
        onClose={() => {}}
        onComplete={onComplete}
      />,
    )
    await screen.findByText('问题诊断')
    clickByText('下一步：配置与测试')
    await screen.findByText('payment_ratio')
    clickByText('下一步：提交确认')
    await screen.findByText('提交确认')
    clickByText('开始重新提取')

    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1))
    expect(screen.getByText('完成')).toBeInTheDocument()
  })
})
