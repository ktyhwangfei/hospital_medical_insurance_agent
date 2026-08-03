const WORKBENCH_API = '/api/v1/medical-insurance-ai-agent/policy-workbench'
const ALIGNMENT_API = '/api/v1/medical-insurance-ai-agent/semantic/alignment'
const PIPELINE_API = '/api/v1/medical-insurance-ai-agent/policy-pipeline'

export type MappingStatus = 'mapped' | 'unmapped' | 'not_applicable' | 'invalid'

export interface KnowledgeField {
  field_code: string
  field_name: string
  raw_value: unknown
}

export interface StandardizedField {
  source_field: string
  source_value: unknown
  status: MappingStatus
  metric_code: string | null
  metric_name: string | null
  value_domain: string | null
  standard_value: unknown | null
  binding_id: string | null
}

export interface KnowledgeItem {
  knowledge_id: string
  unit_id: string
  extraction_id: string
  relationship_source: 'persisted' | 'legacy_match'
  business_sentence: string
  source_text: string
  fields: KnowledgeField[]
  standardized_fields: StandardizedField[]
  confidence: {
    completeness: number
    accuracy: number | null
    source_fidelity: number
    model_confidence: number
    value_domain_compliance: number | null
    overall: number
    uncertainties: string[]
  }
  citations: Array<{ evidence: string; title: string }>
}

export interface ApprovedUnit {
  unit_id: string
  doc_id: string
  doc_title: string
  path: string[]
  source_text: string
  order_no: number
  status: 'reviewed' | 'published'
  knowledge_count: number
  knowledge: KnowledgeItem[]
}

export interface WorkbenchDocument {
  doc_id: string
  doc_title: string
  contract_version: string | null
  units: ApprovedUnit[]
}

export interface WorkbenchDocumentSummary {
  doc_id: string
  doc_title: string
  approved_unit_count: number
  knowledge_count: number
}

export interface MetricDraftSource {
  doc_id: string
  unit_id: string
  knowledge_id: string
  source_field: string
  field_name: string
  source_value: unknown
  source_text: string
  contract_version: string
}

export interface SemanticMetricSummary {
  metric_code: string
  name: string
  object_code: string
  metric_type: string
  status: string
}

export interface MetricDraftOptions {
  metricType: string
  semanticType: string | null
  unit: string | null
  valueDomain: string | null
}

export interface PolicyTestCase {
  case_id: string
  name: string
  query: string
  mode: 'precise' | 'semantic' | 'hybrid'
  expected_knowledge_ids: string[]
  filters: Record<string, unknown>
  required: boolean
  active: boolean
  case_set_version: number
}

export interface KnowledgeRelease {
  release_id: string
  status: 'building' | 'ready' | 'testing' | 'passed' | 'failed' | 'active' | 'retired'
  facts_collection: string
  rules_collection: string
  contract_version: string
  case_set_version: number
  config_hash: string
  quality_score: number | null
  consistency_score: number | null
}

export interface QualityRun {
  run_id: string
  release_id: string
  baseline_release_id: string | null
  status: 'queued' | 'running' | 'passed' | 'failed'
  candidate_score: number | null
  baseline_score: number | null
  consistency_score: number | null
  blocked_reasons: string[]
  repeat_count: number
  case_set_version: number
  config_hash: string
}

export const QUALITY_RUN_CONFIG = {
  repeat_count: 3,
  minimum_quality: 0.8,
  minimum_consistency: 0.9,
} as const
export const QUALITY_CONFIG_HASH = '197ceb8357b8a65b5db3db7044838ff7fd7010ab36caf2b11270e4ab61607e22'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail?.message || body.detail || `请求失败 (${response.status})`)
  }
  return response.json() as Promise<T>
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export async function getWorkbenchDocuments(): Promise<WorkbenchDocumentSummary[]> {
  const result = await request<{ items: WorkbenchDocumentSummary[] }>(`${WORKBENCH_API}/documents`)
  return result.items
}

export const getWorkbenchDocument = (docId: string) =>
  request<WorkbenchDocument>(`${WORKBENCH_API}/documents/${encodeURIComponent(docId)}`)

export const listSemanticMetrics = () =>
  request<SemanticMetricSummary[]>('/api/v1/medical-insurance-ai-agent/semantic/metrics?object_code=zcgz')

export const bindExistingMetric = (source: MetricDraftSource, metricCode: string) =>
  request(`${ALIGNMENT_API}/bindings`, json('POST', {
    metric_code: metricCode,
    source_type: 'policy_knowledge',
    source_ref: `${source.doc_id}/${source.unit_id}/${source.knowledge_id}`,
    source_field: source.source_field,
    source_version: source.contract_version,
    evidence: source.source_text,
  }))

export const createMetricDraft = (source: MetricDraftSource, metricCode: string, name: string, options: MetricDraftOptions) =>
  request(`${ALIGNMENT_API}/metrics`, json('POST', {
    metric_code: metricCode,
    object_code: 'zcgz',
    name,
    definition: `由政策知识字段“${source.field_name}”提炼，待语义层审核发布。`,
    metric_type: options.metricType,
    semantic_type: options.semanticType,
    unit: options.unit,
    value_domain: options.valueDomain,
    source_binding: {
      metric_code: metricCode,
      source_type: 'policy_knowledge',
      source_ref: `${source.doc_id}/${source.unit_id}/${source.knowledge_id}`,
      source_field: source.source_field,
      source_version: source.contract_version,
      evidence: source.source_text,
    },
  }))

export const proposeStandardValue = (source: MetricDraftSource, domainCode: string, value: string) =>
  request(`${ALIGNMENT_API}/standard-values`, json('POST', {
    domain_code: domainCode,
    standard_value: value,
    evidence: source.source_text,
    source_ref: `${source.doc_id}/${source.unit_id}/${source.knowledge_id}/${source.source_field}`,
  }))

export const listTestCases = () => request<PolicyTestCase[]>(`${WORKBENCH_API}/test-cases`)
export const saveTestCase = (testCase: Partial<PolicyTestCase>) =>
  request<PolicyTestCase>(`${WORKBENCH_API}/test-cases`, json('POST', testCase))
export const createRelease = (body: { release_id: string; contract_version: string; config_hash: string }) =>
  request<KnowledgeRelease>(`${WORKBENCH_API}/releases`, json('POST', body))
export const listReleases = () => request<KnowledgeRelease[]>(`${WORKBENCH_API}/releases`)
export const buildRelease = (releaseId: string) =>
  request<KnowledgeRelease>(`${WORKBENCH_API}/releases/${encodeURIComponent(releaseId)}/build`, { method: 'POST' })
export const runQuality = (releaseId: string) =>
  request<QualityRun>(`${WORKBENCH_API}/releases/${encodeURIComponent(releaseId)}/test`, json('POST', QUALITY_RUN_CONFIG))
export const getActiveRelease = () => request<KnowledgeRelease>(`${WORKBENCH_API}/releases/active`)
export const promoteRelease = (releaseId: string, reviewedBy: string) =>
  request<KnowledgeRelease>(`${WORKBENCH_API}/releases/${encodeURIComponent(releaseId)}/promote`, json('POST', { reviewed_by: reviewedBy }))
export const rollbackRelease = (releaseId: string, reviewedBy: string) =>
  request<KnowledgeRelease>(`${WORKBENCH_API}/releases/${encodeURIComponent(releaseId)}/rollback`, json('POST', { reviewed_by: reviewedBy }))
export const listQualityCaseResults = (runId: string) =>
  request<QualityCaseResult[]>(`${WORKBENCH_API}/quality-runs/${encodeURIComponent(runId)}/case-results`)

export interface QualityCaseResult {
  run_id: string
  target: 'candidate' | 'baseline'
  case_id: string
  repeat_index: number
  result_knowledge_ids: string[]
  score: number
  passed: boolean
  diagnostics: Record<string, unknown>
}

export interface QualityRunReport {
  run: QualityRun
  case_results: QualityCaseResult[]
}

export const getLatestReleaseQuality = (releaseId: string) =>
  request<QualityRunReport>(`${WORKBENCH_API}/releases/${encodeURIComponent(releaseId)}/quality/latest`)

export const searchPolicyKnowledge = (body: Record<string, unknown>) =>
  request<{ groups: Array<Record<string, unknown>>; total_groups: number }>(
    `${PIPELINE_API}/rules/search`, json('POST', body)
  )
