import { createServer, type Server } from 'node:http';

import { expect, test } from '@playwright/test';

import { ModelGovernancePage } from '../../pages/portal/model-governance.page';

const apiKey = 'e2e-api-key-value';
const governanceApi = 'http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/model-governance';
const editorTokenPayload = {
  sub: 'portal-governance-editor',
  roles: ['information_department'],
  permissions: [
    'model_governance:read',
    'model_governance:write',
    'model_governance:publish',
  ],
  exp: 4102444800,
};
const governanceHeaders = {
  Authorization: `Bearer test.${Buffer.from(JSON.stringify(editorTokenPayload)).toString('base64url')}.signature`,
};
let provider: Server | undefined;
let providerBaseUrl: string;
let capturedProviderRequest: {
  method?: string;
  path?: string;
  authorization?: string;
  payload: Record<string, unknown>;
} | undefined;

test.beforeAll(async () => {
  capturedProviderRequest = undefined;
  provider = createServer(async (request, response) => {
    let rawBody = '';
    for await (const chunk of request) rawBody += chunk;
    let payload: Record<string, unknown> = {};
    try {
      const parsed: unknown = JSON.parse(rawBody);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        payload = parsed as Record<string, unknown>;
      }
    } catch {
      // 严格 mock 在下面以 422 拒绝非 JSON 请求。
    }
    capturedProviderRequest = {
      method: request.method,
      path: request.url,
      authorization: request.headers.authorization,
      payload,
    };

    let status = 200;
    if (request.method !== 'POST') status = 405;
    else if (request.url !== '/v1/chat/completions') status = 404;
    else if (request.headers.authorization !== `Bearer ${apiKey}`) status = 401;
    else if (
      payload.model !== 'e2e-chat'
      || !Object.prototype.hasOwnProperty.call(payload, 'max_tokens')
      || !Object.prototype.hasOwnProperty.call(payload, 'temperature')
    ) status = 422;

    response.writeHead(status, { 'content-type': 'application/json' });
    response.end(status === 200
      ? JSON.stringify({ model: 'e2e-chat', choices: [{ message: { content: 'pong' }, finish_reason: 'stop' }] })
      : JSON.stringify({ error: 'invalid e2e provider request' }));
  });
  await new Promise<void>((resolve) => provider.listen(0, '127.0.0.1', resolve));
  const address = provider.address();
  if (!address || typeof address === 'string') throw new Error('测试 Provider 启动失败');
  providerBaseUrl = `http://127.0.0.1:${address.port}/v1`;
  const post = (path: string, payload: Record<string, unknown>, authorization = `Bearer ${apiKey}`) => fetch(
    `${providerBaseUrl}${path}`,
    { method: 'POST', headers: { authorization, 'content-type': 'application/json' }, body: JSON.stringify(payload) },
  );
  const validPayload = { model: 'e2e-chat', max_tokens: 1, temperature: 0 };
  expect((await fetch(`${providerBaseUrl}/chat/completions`)).status).toBe(405);
  expect((await post('/wrong', validPayload)).status).toBe(404);
  expect((await post('/chat/completions', validPayload, 'Bearer wrong')).status).toBe(401);
  expect((await post('/chat/completions', { model: 'e2e-chat', max_tokens: 1 })).status).toBe(422);
  capturedProviderRequest = undefined;
});

test.afterAll(async () => {
  if (!provider?.listening) return;
  await new Promise<void>((resolve, reject) => provider!.close((error) => error ? reject(error) : resolve()));
});

test.afterEach(async ({ request }) => {
  try {
    const assetsResponse = await request.get(
      `${governanceApi}/assets?environment=dev&asset_type=prompt`,
      { headers: governanceHeaders },
    );
    if (!assetsResponse.ok()) return;
    const assets = await assetsResponse.json() as {
      result: {
        baselines: Array<{ asset_id: string; system_prompt: string; user_prompt_template: string }>;
        published: Array<{
          asset_id: string;
          content: { system_prompt: string; user_prompt_template: string };
        }>;
      };
    };
    const baseline = assets.result.baselines.find((item) => item.asset_id === 'intent.classify');
    const active = assets.result.published.find((item) => item.asset_id === 'intent.classify');
    if (!baseline || !active || (
      active.content.system_prompt === baseline.system_prompt
      && active.content.user_prompt_template === baseline.user_prompt_template
    )) return;

    const versionsResponse = await request.get(
      `${governanceApi}/assets/intent.classify/versions?environment=dev`,
      { headers: governanceHeaders },
    );
    if (!versionsResponse.ok()) return;
    const history = await versionsResponse.json() as {
      result: {
        versions: Array<{
          version_id: string;
          content: { system_prompt: string; user_prompt_template: string };
        }>;
        releases: Array<{ release_id: string; version_id: string; status: string }>;
      };
    };
    const baselineVersion = history.result.versions.find((item) =>
      item.content.system_prompt === baseline.system_prompt
      && item.content.user_prompt_template === baseline.user_prompt_template);
    const retiredBaseline = history.result.releases.find((item) =>
      item.version_id === baselineVersion?.version_id && item.status === 'retired');
    if (retiredBaseline) {
      await request.post(`${governanceApi}/releases/${retiredBaseline.release_id}/rollback`, {
        headers: governanceHeaders,
      });
    }
  } catch {
    // Best effort: preserve the original E2E failure while avoiding a polluted retry.
  }
});

test('收费员管理真实模型、路由与提示词版本且密钥不泄漏', async ({ page, browserName }, testInfo) => {
  test.skip(browserName !== 'chromium', '治理写流程只需一个 Chromium 实例，避免共享活动版本并发冲突');
  test.setTimeout(120_000);

  const governance = new ModelGovernancePage(page);
  await governance.goto();
  await expect(governance.roleSwitcher).toContainText('收费员');
  await expect(governance.modelGovernanceLink).toBeVisible();

  const assetsResponse = await governance.openAndWaitForAssets();
  expect(assetsResponse.status()).toBe(200);
  await expect(governance.title).toBeVisible();
  const assets = await assetsResponse.json() as {
    result: {
      baselines: Array<{
        asset_id: string;
        asset_type: string;
        system_prompt: string;
        user_prompt_template: string;
      }>;
      published: Array<{
        asset_id: string;
        content: { system_prompt: string; user_prompt_template: string };
      }>;
    };
  };
  const baseline = assets.result.baselines.find((item) =>
    item.asset_type === 'prompt' && item.asset_id === 'intent.classify');
  expect(baseline).toBeTruthy();
  expect(baseline!.user_prompt_template.length).toBeGreaterThan(0);
  expect(baseline!.user_prompt_template).toContain('用户消息');
  const activePrompt = assets.result.published.find((item) => item.asset_id === 'intent.classify');
  if (activePrompt) {
    expect(activePrompt.content.system_prompt).toBe(baseline!.system_prompt);
    expect(activePrompt.content.user_prompt_template).toBe(baseline!.user_prompt_template);
  }

  await governance.selectTab('提示词');
  await governance.openAsset('intent.classify');
  await governance.expectCurrentPrompt(baseline!.system_prompt, baseline!.user_prompt_template);
  await governance.closeDrawer();

  const suffix = `${testInfo.project.name}-${Date.now()}`.replace(/[^a-z0-9-]/g, '-');
  const profileId = `profile.e2e-${suffix}`;
  const routeId = `route.e2e-${suffix}`;
  const createModelResponse = await governance.createModelProfile({
    assetId: profileId,
    baseUrl: providerBaseUrl,
    modelName: 'e2e-chat',
    credentialId: `credential.e2e-${suffix}`,
    apiKey,
  });
  expect(await createModelResponse.text()).not.toContain(apiKey);
  const connectionResponse = await governance.testModelConnection();
  expect(await connectionResponse.text()).not.toContain(apiKey);
  expect(capturedProviderRequest).toEqual({
    method: 'POST',
    path: '/v1/chat/completions',
    authorization: `Bearer ${apiKey}`,
    payload: expect.objectContaining({ model: 'e2e-chat', max_tokens: 1, temperature: 0 }),
  });
  await governance.completeReviewAndPublish(profileId);

  await governance.createRouteRule(routeId, `e2e-${suffix}`, profileId);
  await governance.completeReviewAndPublish(routeId);

  if (!activePrompt) {
    await governance.activateBaselinePrompt('intent.classify');
    await governance.completeReviewAndPublish('intent.classify');
  }
  const nextPrompt = `${baseline!.user_prompt_template}\nE2E_ACTIVE_${suffix}`;
  await governance.createPromptVersion('intent.classify', nextPrompt);
  await governance.completeReviewAndPublish('intent.classify');

  await governance.selectTab('提示词');
  await governance.openAsset('intent.classify');
  await governance.expectCurrentPrompt(baseline!.system_prompt, nextPrompt);
  if (process.env.MODEL_GOVERNANCE_E2E_FORCE_RETRY === '1' && testInfo.retry === 0) {
    throw new Error('E2E retry recovery probe');
  }
  await governance.rollbackPromptToPrevious(baseline!.system_prompt, baseline!.user_prompt_template);
  await governance.closeDrawer();

  await governance.assertSecretAbsent(apiKey);
  await governance.useMobileViewport();
  expect(await governance.hasNoHorizontalOverflow()).toBe(true);
});
