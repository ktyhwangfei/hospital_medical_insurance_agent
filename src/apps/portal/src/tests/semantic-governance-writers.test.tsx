import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import MetricsPage from '../../app/semantic-layer/metrics/page'
import StandardValuesModal from '../../app/semantic-layer/standard-values-modal'

const SEMANTIC_API = '/api/v1/medical-insurance-ai-agent/semantic'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('semantic governance writers', () => {
  beforeEach(() => {
    sessionStorage.clear()
    sessionStorage.setItem('semantic-review-token', 'review-token')
    vi.stubGlobal('alert', vi.fn())
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    sessionStorage.clear()
  })

  it('preserves a null semantic type when editing only the metric name', async () => {
    const metric = {
      metric_code: 'zcgz.unclassified', name: '未分类指标', definition: null,
      object_code: 'zcgz', metric_type: 'Atomic', semantic_type: null,
      indexed: false, schema_version: 4, unit: null, required: false,
      importance: 'optional', value_domain: null, source_object: null,
      source_field: null, source_adapter_port: null, usage_count: 0,
      quality_score: 0, version: '1.0', status: 'published',
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (init?.method === 'PUT') {
        return jsonResponse({
          status: 'ok', metric_code: metric.metric_code, schema_version: 4,
          requires_reextract: false, task_id: null, task_status: null,
        })
      }
      if (url === `${SEMANTIC_API}/objects`) {
        return jsonResponse([{ object_code: 'zcgz', name: '政策规则', domain_code: 'policy', status: 'published' }])
      }
      if (url.includes('/metrics?object_code=')) return jsonResponse([{ metric_code: metric.metric_code }])
      if (url.includes('/metrics/')) return jsonResponse(metric)
      throw new Error(`unexpected fetch: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<MetricsPage />)

    fireEvent.click(await screen.findByTitle('编辑'))
    fireEvent.change(screen.getByDisplayValue('未分类指标'), { target: { value: '未分类指标（修订）' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      const update = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
      expect(update).toBeDefined()
      expect(JSON.parse(String(update?.[1]?.body))).toEqual({ name: '未分类指标（修订）' })
    })
  })

  it('does not report a standard-value save as successful after forbidden', async () => {
    const onSaved = vi.fn()
    const onClose = vi.fn()
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ domain_code: 'status', standard_values: [] }))
      .mockResolvedValueOnce(jsonResponse({
        detail: { error_code: 'FORBIDDEN', message: '无权限保存', audit_event: {} },
      }, 403))
    vi.stubGlobal('fetch', fetchMock)
    render(<StandardValuesModal valueDomainCode="status" onSaved={onSaved} onClose={onClose} />)

    await screen.findByText(/暂无标准值/)
    fireEvent.click(screen.getByRole('button', { name: '保存 (0)' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(onSaved).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
    expect(alert).toHaveBeenCalledWith('无权限保存')
  })
})
