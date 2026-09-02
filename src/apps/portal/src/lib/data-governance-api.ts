import { API_PREFIX, parseError, requestJson } from './api-client'
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
  platformReady: boolean
  postgresql: PostgresTarget
  dataSourceCount: number
  runningJobCount: number
  issueCount: number
  latestLatencySeconds: number | null
  sources: DataGovernanceSourceStatus[]
  issues: DataGovernanceIssue[]
  recentRuns: SyncRun[]
}

export interface DataSource {
  sourceId: string
  hospitalCode: string
  hospitalName: string
  name: string
  host: string
  port: number
  database: string
  schemaName: string
  username: string
  credentialId: string
  credentialConfigured: boolean
  credentialRevision: number | null
  connectionStatus: ConnectionStatus
  cdcStatus: CdcStatus
  safeProbeMessage: string | null
  lastProbedAt: string | null
}

export interface CreateDataSourceInput {
  sourceId: string
  hospitalCode: string
  hospitalName: string
  name: string
  host: string
  port: number
  database: string
  username: string
  credentialId: string
  password: string
}

export interface ConnectionProbe {
  status: ConnectionStatus
  errorCode: string | null
  safeMessage: string
  checkedAt: string
}

export interface CdcProbe {
  status: string
  databaseEnabled: boolean
  readyCaptures: string[]
  missingCaptures: string[]
  retentionMinutes: number | null
  safeMessage: string
  checkedAt: string
}

export interface PostgresTarget {
  connectionStatus: ConnectionStatus
  schemaReady: boolean
  safeMessage: string
  checkedAt: string
}

export interface SyncJob {
  sourceId: string
  sourceMode: SourceMode
  status: string
  cdcPollIntervalSeconds: number
  scheduleIntervalMinutes: number
  lookbackHours: number
  reconcileTime: string
  reconcileDays: number
  revision: number
  baselineRequired: boolean
  nextRunAt: string | null
  runOnceRequestedAt: string | null
  lastStartedAt: string | null
  lastSucceededAt: string | null
  lastErrorCode: string | null
}

export interface SaveSyncJobInput {
  sourceMode: SourceMode
  expectedRevision: number
  confirmModeSwitch?: boolean
  cdcPollIntervalSeconds?: number
  scheduleIntervalMinutes?: number
  lookbackHours?: number
  reconcileTime?: string
  reconcileDays?: number
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
    platform_ready: boolean
    postgresql: {
      connection_status: ConnectionStatus
      schema_ready: boolean
      safe_message: string
      checked_at: string
    }
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

interface DataSourceDto {
  source_id: string
  hospital_code: string
  hospital_name: string
  name: string
  host: string
  port: number
  database: string
  schema_name: string
  username: string
  credential_id: string
  credential_configured: boolean
  credential_revision: number | null
  connection_status: ConnectionStatus
  cdc_status: CdcStatus
  safe_probe_message: string | null
  last_probed_at: string | null
}

interface SyncJobDto {
  source_id: string
  source_mode: SourceMode
  status: string
  cdc_poll_interval_seconds: number
  schedule_interval_minutes: number
  lookback_hours: number
  reconcile_time: string
  reconcile_days: number
  revision: number
  baseline_required: boolean
  next_run_at: string | null
  run_once_requested_at: string | null
  last_started_at: string | null
  last_succeeded_at: string | null
  last_error_code: string | null
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

export function hasDataGovernancePermission(permission: 'read' | 'write'): boolean {
  const token = governanceToken()
  if (!token) return process.env.NODE_ENV !== 'production'
  try {
    const payload = token.replace(/^Bearer\s+/i, '').split('.')[1]
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(payload.length / 4) * 4, '=')
    const permissions = JSON.parse(atob(base64)).permissions
    return Array.isArray(permissions) && permissions.includes(`data_governance:${permission}`)
  } catch {
    return false
  }
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

function mapDataSource(item: DataSourceDto): DataSource {
  return {
    sourceId: item.source_id,
    hospitalCode: item.hospital_code,
    hospitalName: item.hospital_name,
    name: item.name,
    host: item.host,
    port: item.port,
    database: item.database,
    schemaName: item.schema_name,
    username: item.username,
    credentialId: item.credential_id,
    credentialConfigured: item.credential_configured,
    credentialRevision: item.credential_revision,
    connectionStatus: item.connection_status,
    cdcStatus: item.cdc_status,
    safeProbeMessage: item.safe_probe_message,
    lastProbedAt: item.last_probed_at,
  }
}

function mapJob(item: SyncJobDto): SyncJob {
  return {
    sourceId: item.source_id,
    sourceMode: item.source_mode,
    status: item.status,
    cdcPollIntervalSeconds: item.cdc_poll_interval_seconds,
    scheduleIntervalMinutes: item.schedule_interval_minutes,
    lookbackHours: item.lookback_hours,
    reconcileTime: item.reconcile_time,
    reconcileDays: item.reconcile_days,
    revision: item.revision,
    baselineRequired: item.baseline_required,
    nextRunAt: item.next_run_at,
    runOnceRequestedAt: item.run_once_requested_at,
    lastStartedAt: item.last_started_at,
    lastSucceededAt: item.last_succeeded_at,
    lastErrorCode: item.last_error_code,
  }
}

export async function getDataGovernanceOverview(): Promise<DataGovernanceOverview> {
  const { result } = await dataGovernanceRequest<OverviewResponse>('/overview')
  return {
    platformReady: result.platform_ready,
    postgresql: {
      connectionStatus: result.postgresql.connection_status,
      schemaReady: result.postgresql.schema_ready,
      safeMessage: result.postgresql.safe_message,
      checkedAt: result.postgresql.checked_at,
    },
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

export async function listDataSources(): Promise<DataSource[]> {
  const response = await dataGovernanceRequest<{ result: { items: DataSourceDto[] } }>('/data-sources')
  return response.result.items.map(mapDataSource)
}

export async function createDataSource(input: CreateDataSourceInput): Promise<DataSource> {
  const response = await dataGovernanceRequest<{ result: DataSourceDto }>('/data-sources', {
    method: 'POST',
    body: JSON.stringify({
      source_id: input.sourceId,
      hospital_code: input.hospitalCode,
      hospital_name: input.hospitalName,
      name: input.name,
      host: input.host,
      port: input.port,
      database: input.database,
      schema_name: 'dbo',
      username: input.username,
      credential: { credential_id: input.credentialId, password: input.password },
    }),
  })
  return mapDataSource(response.result)
}

export async function updateDataSource(
  sourceId: string,
  input: Partial<Pick<CreateDataSourceInput, 'hospitalCode' | 'hospitalName' | 'name' | 'host' | 'port' | 'database' | 'username'>>,
): Promise<DataSource> {
  const response = await dataGovernanceRequest<{ result: DataSourceDto }>(`/data-sources/${encodeURIComponent(sourceId)}`, {
    method: 'PATCH',
    body: JSON.stringify(Object.fromEntries(Object.entries({
      hospital_code: input.hospitalCode,
      hospital_name: input.hospitalName,
      name: input.name,
      host: input.host,
      port: input.port,
      database: input.database,
      username: input.username,
    }).filter(([, value]) => value !== undefined))),
  })
  return mapDataSource(response.result)
}

export async function rotateDataSourceCredential(
  sourceId: string,
  credentialId: string,
  password: string,
  expectedRevision: number,
): Promise<DataSource> {
  const response = await dataGovernanceRequest<{ result: DataSourceDto }>(`/data-sources/${encodeURIComponent(sourceId)}/credential`, {
    method: 'PUT',
    body: JSON.stringify({ credential_id: credentialId, password, expected_revision: expectedRevision }),
  })
  return mapDataSource(response.result)
}

export async function testDataSourceConnection(sourceId: string): Promise<ConnectionProbe> {
  const response = await dataGovernanceRequest<{ result: { status: ConnectionStatus; error_code: string | null; safe_message: string; checked_at: string } }>(`/data-sources/${encodeURIComponent(sourceId)}/test`, { method: 'POST' })
  return {
    status: response.result.status,
    errorCode: response.result.error_code,
    safeMessage: response.result.safe_message,
    checkedAt: response.result.checked_at,
  }
}

export async function downloadCdcScript(sourceId: string): Promise<void> {
  const headers = new Headers()
  const token = governanceToken()
  if (token) headers.set('Authorization', token.startsWith('Bearer ') ? token : `Bearer ${token}`)
  const response = await fetch(`${API_PREFIX}/data-governance/data-sources/${encodeURIComponent(sourceId)}/cdc-script`, { headers })
  if (!response.ok) throw await parseError(response)
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = 'enable_outpatient_cdc.sql'
  link.click()
  URL.revokeObjectURL(url)
}

export async function checkDataSourceCdc(sourceId: string): Promise<CdcProbe> {
  const response = await dataGovernanceRequest<{ result: {
    status: string; database_enabled: boolean; ready_captures: string[]; missing_captures: string[];
    retention_minutes: number | null; safe_message: string; checked_at: string
  } }>(`/data-sources/${encodeURIComponent(sourceId)}/cdc-check`, { method: 'POST' })
  return {
    status: response.result.status,
    databaseEnabled: response.result.database_enabled,
    readyCaptures: response.result.ready_captures,
    missingCaptures: response.result.missing_captures,
    retentionMinutes: response.result.retention_minutes,
    safeMessage: response.result.safe_message,
    checkedAt: response.result.checked_at,
  }
}

export async function getPostgresTargetStatus(): Promise<PostgresTarget> {
  const response = await dataGovernanceRequest<{ result: { connection_status: ConnectionStatus; schema_ready: boolean; safe_message: string; checked_at: string } }>('/postgresql/status')
  return {
    connectionStatus: response.result.connection_status,
    schemaReady: response.result.schema_ready,
    safeMessage: response.result.safe_message,
    checkedAt: response.result.checked_at,
  }
}

export async function getSyncJob(sourceId: string): Promise<SyncJob | null> {
  try {
    const response = await dataGovernanceRequest<{ result: SyncJobDto }>(`/sync-jobs/${encodeURIComponent(sourceId)}`)
    return mapJob(response.result)
  } catch (error) {
    if (error instanceof ApiClientError && error.status === 404) return null
    throw error
  }
}

export async function saveSyncJob(sourceId: string, input: SaveSyncJobInput): Promise<SyncJob> {
  const response = await dataGovernanceRequest<{ result: SyncJobDto }>(`/sync-jobs/${encodeURIComponent(sourceId)}`, {
    method: 'PUT',
    body: JSON.stringify({
      source_mode: input.sourceMode,
      expected_revision: input.expectedRevision,
      confirm_mode_switch: input.confirmModeSwitch ?? false,
      cdc_poll_interval_seconds: input.cdcPollIntervalSeconds ?? 45,
      schedule_interval_minutes: input.scheduleIntervalMinutes ?? 5,
      lookback_hours: input.lookbackHours ?? 2,
      reconcile_time: input.reconcileTime ?? '02:00:00',
      reconcile_days: input.reconcileDays ?? 30,
    }),
  })
  return mapJob(response.result)
}

async function syncJobAction(sourceId: string, action: 'start' | 'pause' | 'run-once'): Promise<SyncJob> {
  const response = await dataGovernanceRequest<{ result: SyncJobDto }>(`/sync-jobs/${encodeURIComponent(sourceId)}/${action}`, { method: 'POST' })
  return mapJob(response.result)
}

export const startSyncJob = (sourceId: string) => syncJobAction(sourceId, 'start')
export const pauseSyncJob = (sourceId: string) => syncJobAction(sourceId, 'pause')
export const runSyncJobOnce = (sourceId: string) => syncJobAction(sourceId, 'run-once')

export async function listSyncRuns(sourceId: string): Promise<SyncRun[]> {
  const response = await dataGovernanceRequest<{ result: { items: SyncRunDto[] } }>(`/sync-jobs/${encodeURIComponent(sourceId)}/runs`)
  return response.result.items.map(mapRun)
}

// ---- 源表探查 / 映射 / SQL 预览 ----

export interface SourceTable {
  table_schema: string
  table_name: string
  row_count: number
}

export interface SourceColumn {
  name: string
  data_type: string
  is_nullable: boolean
  max_length: number | null
  is_primary_key: boolean
}

export interface CaptureMapping {
  capture: string
  table_schema: string
  table_name: string
  key_fields: string[]
  column_map: Record<string, string>
}

export interface SourceMapping {
  source_id: string
  captures: Record<string, CaptureMapping>
  revision: number
  created_at: string
  updated_at: string
}

export interface MappingSqlPreview {
  is_default: boolean
  mapping_revision: number
  baseline_sql: string[]
  incremental_window_sql: string
  incremental_children_sql: string[]
}

export async function exploreSourceTables(sourceId: string): Promise<SourceTable[]> {
  const response = await dataGovernanceRequest<{ result: SourceTable[] }>(
    `/data-sources/${encodeURIComponent(sourceId)}/explore`,
  )
  return response.result
}

export async function exploreSourceTable(
  sourceId: string,
  tableSchema: string,
  tableName: string,
): Promise<SourceColumn[]> {
  const response = await dataGovernanceRequest<{ result: SourceColumn[] }>(
    `/data-sources/${encodeURIComponent(sourceId)}/explore/${encodeURIComponent(tableSchema)}/${encodeURIComponent(tableName)}`,
  )
  return response.result
}

export async function getSourceMapping(sourceId: string): Promise<SourceMapping> {
  const response = await dataGovernanceRequest<{ result: SourceMapping }>(
    `/data-sources/${encodeURIComponent(sourceId)}/mapping`,
  )
  return response.result
}

export async function saveSourceMapping(
  sourceId: string,
  captures: CaptureMapping[],
  expectedRevision: number,
): Promise<SourceMapping> {
  const response = await dataGovernanceRequest<{ result: SourceMapping }>(
    `/data-sources/${encodeURIComponent(sourceId)}/mapping`,
    { method: 'PUT', body: JSON.stringify({ captures, expected_revision: expectedRevision }) },
  )
  return response.result
}

export async function getMappingSqlPreview(
  sourceId: string,
  draftCaptures?: CaptureMapping[],
): Promise<MappingSqlPreview> {
  const response = await dataGovernanceRequest<{ result: MappingSqlPreview }>(
    `/data-sources/${encodeURIComponent(sourceId)}/mapping/sql-preview`,
    draftCaptures ? {
      method: 'POST',
      body: JSON.stringify({ captures: draftCaptures }),
    } : { method: 'POST' },
  )
  return response.result
}
