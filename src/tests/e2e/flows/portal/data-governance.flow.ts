import { expect, test, type Route } from '@playwright/test';

import { DataGovernancePage } from '../../pages/portal/data-governance.page';

const secret = 'e2e-sqlserver-password';
const source = {
  source_id: 'hospital-e2e', hospital_code: 'H-E2E', hospital_name: 'E2E 示例医院',
  name: '门诊医保库', host: '10.20.30.40', port: 1433, database: 'bjybdb', schema_name: 'dbo',
  username: 'readonly', credential_id: 'credential.hospital-e2e', credential_configured: true,
  credential_revision: 1, connection_status: 'healthy', cdc_status: 'waiting_dba',
  safe_probe_message: '门诊 3 张源表及 117 个契约字段可读', last_probed_at: '2026-08-31T08:00:00Z',
  created_at: '2026-08-31T08:00:00Z', updated_at: '2026-08-31T08:00:00Z',
};
let sources: typeof source[];
let capturedPassword: string | undefined;
let job: Record<string, unknown>;
let runs: Record<string, unknown>[];

function token(permissions: string[]): string {
  return `header.${Buffer.from(JSON.stringify({ permissions })).toString('base64url')}.signature`;
}

async function respond(route: Route, result: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ result }) });
}

test.beforeEach(async ({ page }) => {
  sources = [];
  capturedPassword = undefined;
  job = {
    source_id: source.source_id, source_mode: 'cdc', status: 'paused',
    cdc_poll_interval_seconds: 45, schedule_interval_minutes: 5, lookback_hours: 2,
    reconcile_time: '02:00:00', reconcile_days: 30, revision: 1, baseline_required: true,
    next_run_at: null, run_once_requested_at: null, active_attempt_id: null,
    last_started_at: null, last_succeeded_at: null, last_reconciled_at: null,
    last_error_code: null, created_at: '2026-08-31T08:00:00Z', updated_at: '2026-08-31T08:00:00Z',
  };
  runs = [];
  await page.addInitScript((value) => {
    if (!sessionStorage.getItem('data-governance-token')) sessionStorage.setItem('data-governance-token', value);
  }, token(['data_governance:read', 'data_governance:write']));
  await page.route('**/api/v1/medical-insurance-ai-agent/data-governance/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    if (path.endsWith('/overview')) {
      await respond(route, {
        platform_ready: true,
        postgresql: { connection_status: 'healthy', schema_ready: true, safe_message: 'PostgreSQL 门诊结构及读写已就绪', checked_at: '2026-08-31T08:00:00Z' },
        data_source_count: sources.length, running_job_count: 0, issue_count: 0,
        latest_latency_seconds: null,
        sources: sources.map((item) => ({
          source_id: item.source_id, hospital_code: item.hospital_code,
          hospital_name: item.hospital_name, name: item.name,
          credential_configured: true, connection_status: item.connection_status,
          cdc_status: item.cdc_status, sync_status: 'draft', source_mode: 'scheduled_sql',
          next_run_at: null, last_succeeded_at: null, quality_status: null,
          latest_latency_seconds: null,
        })),
        issues: [], recent_runs: [],
      });
    } else if (path.endsWith('/postgresql/status')) {
      await respond(route, { connection_status: 'healthy', schema_ready: true, safe_message: 'PostgreSQL 门诊结构及读写已就绪', checked_at: '2026-08-31T08:00:00Z' });
    } else if (path.endsWith('/data-sources') && method === 'GET') {
      await respond(route, { items: sources });
    } else if (path.endsWith('/data-sources') && method === 'POST') {
      const body = request.postDataJSON();
      capturedPassword = body.credential.password;
      sources = [source];
      await respond(route, source, 201);
    } else if (path.endsWith(`/sync-jobs/${source.source_id}/runs`)) {
      await respond(route, { items: runs });
    } else if (path.endsWith(`/sync-jobs/${source.source_id}`) && method === 'GET') {
      await respond(route, job);
    } else if (path.endsWith(`/sync-jobs/${source.source_id}`) && method === 'PUT') {
      const body = request.postDataJSON();
      job = { ...job, source_mode: body.source_mode, status: 'paused', revision: 2 };
      await respond(route, job);
    } else if (path.endsWith(`/sync-jobs/${source.source_id}/start`)) {
      job = { ...job, status: 'ready' };
      await respond(route, job);
    } else if (path.endsWith(`/sync-jobs/${source.source_id}/run-once`)) {
      job = { ...job, status: 'running', run_once_requested_at: '2026-08-31T08:05:00Z' };
      runs = [{
        attempt_id: 'attempt-e2e', source_id: source.source_id, source_mode: 'scheduled_sql',
        run_kind: 'manual', status: 'succeeded', started_at: '2026-08-31T08:05:00Z',
        finished_at: '2026-08-31T08:05:01Z', safe_error_code: null, safe_message: null,
        row_count: 3, batch_id: 'batch-e2e',
      }];
      await respond(route, job);
    } else if (path.endsWith(`/sync-jobs/${source.source_id}/pause`)) {
      job = { ...job, status: 'paused' };
      await respond(route, job);
    } else {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ message: 'not found' }) });
    }
  });
});

test('管理员配置双模式任务且只读用户没有写入口', async ({ page }) => {
  const governance = new DataGovernancePage(page);
  await governance.gotoDataSources();
  await governance.createSource(secret);
  expect(capturedPassword).toBe(secret);
  await governance.expectSecretAbsent(secret);
  await governance.gotoOverview();
  await governance.expectReadyStates();

  await governance.gotoSyncJobs();
  await governance.configureScheduledSql();
  await governance.startRunAndPause();

  await page.evaluate((value) => sessionStorage.setItem('data-governance-token', value), token(['data_governance:read']));
  await governance.gotoDataSources();
  await governance.expectReadOnly();
  await governance.expectSecretAbsent(secret);
});
