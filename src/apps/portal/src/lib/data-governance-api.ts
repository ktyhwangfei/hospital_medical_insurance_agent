import { requestJson } from './api-client'
import { ApiClientError } from './types'

export type ConnectionStatus = 'unknown' | 'healthy' | 'error'
export type CdcStatus = 'not_applicable' | 'not_checked' | 'waiting_dba' | 'ready' | 'invalid'
export type SourceMode = 'cdc' | 'scheduled_sql'

export interface DataGovernanceSourceStatus {
  sourceId: string
  hospitalCode: string
  hospitalName: string
  name: string
  credentialConfigured: boolean
  connectionStatus: ConnectionStatus
  cdcStatus: CdcStatus
  syncStatus: string | null
  sourceMode: SourceMode | null
  nextRunAt: string | null
  lastSucceededAt: string | null
  qualityStatus: string | null
  latestLatencySeconds: number | null
}

export interface DataGovernanceIssue {
  code: string
  severity: 'warning' | 'blocking'
  message: string
  sourceId: string | null
}

export interface SyncRun {
  attemptId: string
  sourceId: string
  sourceMode: SourceMode
  runKind: string
  status: string
  startedAt: string
  finishedAt: string | null
  safeErrorCode: string | null
  safeMessage: string | null
  rowCount: number
  batchId: string | null
}

export interface DataGovernanceOverview {
  dataSourceCount: number
  runningJobCount: number
  issueCount: number
  latestLatencySeconds: number | null
  sources: DataGovernanceSourceStatus[]
  issues: DataGovernanceIssue[]
  recentRuns: SyncRun[]
}

interface SourceStatusDto {
  source_id: string
  hospital_code: string
  hospital_name: string
  name: string
  credential_configured: boolean
  connection_status: ConnectionStatus
  cdc_status: CdcStatus
  sync_status: string | null
  source_mode: SourceMode | null
  next_run_at: string | null
  last_succeeded_at: string | null
  quality_status: string | null
  latest_latency_seconds: number | null
}

interface SyncRunDto {
  attempt_id: string
  source_id: string
  source_mode: SourceMode
  run_kind: string
  status: string
  started_at: string
  finished_at: string | null
  safe_error_code: string | null
  safe_message: string | null
  row_count: number
  batch_id: string | null
}

interface OverviewResponse {
  result: {
    data_source_count: number
    running_job_count: number
    issue_count: number
    latest_latency_seconds: number | null
    sources: SourceStatusDto[]
    issues: Array<{
      code: string
      severity: 'warning' | 'blocking'
      message: string
      source_id: string | null
    }>
    recent_runs: SyncRunDto[]
  }
}

function governanceToken(): string | null {
  if (typeof window !== 'undefined') {
    const token = window.sessionStorage.getItem('data-governance-token')
    if (token) return token
  }
  return process.env.NODE_ENV === 'production'
    ? null
    : process.env.NEXT_PUBLIC_DATA_GOVERNANCE_TOKEN || null
}

export async function dataGovernanceRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  const token = governanceToken()
  if (token) headers.set('Authorization', token.startsWith('Bearer ') ? token : `Bearer ${token}`)
  try {
    return await requestJson<T>(`/data-governance${path}`, { ...init, headers })
  } catch (error) {
    if (error instanceof ApiClientError) throw error
    throw new Error('无法连接数据治理服务')
  }
}

function mapSource(item: SourceStatusDto): DataGovernanceSourceStatus {
  return {
    sourceId: item.source_id,
    hospitalCode: item.hospital_code,
    hospitalName: item.hospital_name,
    name: item.name,
    credentialConfigured: item.credential_configured,
    connectionStatus: item.connection_status,
    cdcStatus: item.cdc_status,
    syncStatus: item.sync_status,
    sourceMode: item.source_mode,
    nextRunAt: item.next_run_at,
    lastSucceededAt: item.last_succeeded_at,
    qualityStatus: item.quality_status,
    latestLatencySeconds: item.latest_latency_seconds,
  }
}

function mapRun(item: SyncRunDto): SyncRun {
  return {
    attemptId: item.attempt_id,
    sourceId: item.source_id,
    sourceMode: item.source_mode,
    runKind: item.run_kind,
    status: item.status,
    startedAt: item.started_at,
    finishedAt: item.finished_at,
    safeErrorCode: item.safe_error_code,
    safeMessage: item.safe_message,
    rowCount: item.row_count,
    batchId: item.batch_id,
  }
}

export async function getDataGovernanceOverview(): Promise<DataGovernanceOverview> {
  const { result } = await dataGovernanceRequest<OverviewResponse>('/overview')
  return {
    dataSourceCount: result.data_source_count,
    runningJobCount: result.running_job_count,
    issueCount: result.issue_count,
    latestLatencySeconds: result.latest_latency_seconds,
    sources: result.sources.map(mapSource),
    issues: result.issues.map((item) => ({
      code: item.code,
      severity: item.severity,
      message: item.message,
      sourceId: item.source_id,
    })),
    recentRuns: result.recent_runs.map(mapRun),
  }
}
