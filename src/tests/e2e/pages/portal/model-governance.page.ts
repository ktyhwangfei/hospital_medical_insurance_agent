import { expect, type Locator, type Page, type Response } from '@playwright/test';

import { BasePage } from '../base.page';

/** Portal 模型治理资产中心 Page Object。 */
export class ModelGovernancePage extends BasePage {
  readonly roleSwitcher: Locator;
  readonly modelGovernanceLink: Locator;
  readonly title: Locator;
  readonly developerIdentity: Locator;
  private readonly governanceResponseBodies: Promise<string>[] = [];

  constructor(page: Page) {
    super(page, 'http://127.0.0.1:3000');
    this.roleSwitcher = page.locator('header').getByRole('combobox');
    this.modelGovernanceLink = page.getByRole('link', { name: '后台管理', exact: true });
    this.title = page.getByRole('heading', { name: '后台管理', exact: true });
    this.developerIdentity = page.getByLabel('开发身份');
    page.on('response', (response) => {
      if (response.url().includes('/model-governance/')) {
        this.governanceResponseBodies.push(response.text().catch(() => ''));
      }
    });
  }

  async goto(): Promise<void> {
    await super.goto('/');
  }

  async useMobileViewport(): Promise<void> {
    await this.page.setViewportSize({ width: 390, height: 844 });
  }

  async openAndWaitForAssets(): Promise<Response> {
    const responsePromise = this.page.waitForResponse((response) =>
      response.request().method() === 'GET'
      && response.url().includes('/model-governance/assets?'),
    );
    await this.modelGovernanceLink.click();
    return responsePromise;
  }

  async hasNoHorizontalOverflow(): Promise<boolean> {
    return this.page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    );
  }

  async assertSecretAbsent(secret: string): Promise<void> {
    await expect(this.page.locator('body')).not.toContainText(secret);
    for (const body of await Promise.all(this.governanceResponseBodies)) {
      expect(body).not.toContain(secret);
    }
  }

  assetRow(assetId: string): Locator {
    return this.page.locator('tbody tr').filter({ hasText: assetId });
  }

  async selectTab(name: '提示词' | '模型' | '路由规则' | '发布记录'): Promise<void> {
    await this.page.getByRole('tab', { name, exact: true }).click();
  }

  async openAsset(assetId: string): Promise<void> {
    await this.assetRow(assetId).getByRole('button', { name: `查看 ${assetId}` }).click();
    await expect(this.page.getByRole('dialog')).toBeVisible();
  }

  async closeDrawer(): Promise<void> {
    await this.page.getByRole('button', { name: '关闭详情抽屉' }).click();
  }

  async expectCurrentPrompt(systemPrompt: string, userPrompt: string): Promise<void> {
    const current = this.page.locator('section[aria-labelledby="current-version-title"]');
    await expect(current.getByText(systemPrompt || '（空）', { exact: true })).toBeVisible();
    await expect(current.getByText(userPrompt, { exact: true })).toBeVisible();
  }

  async selectDeveloperIdentity(identity: 'editor' | 'reviewer'): Promise<void> {
    await this.developerIdentity.selectOption(identity);
  }

  private async saveWorkingVersion(method: 'POST' | 'PATCH'): Promise<Response> {
    const responsePromise = this.page.waitForResponse((response) =>
      response.request().method() === method
      && response.url().includes('/model-governance/drafts'),
    );
    await this.page.getByRole('button', { name: '保存工作版本', exact: true }).click();
    return responsePromise;
  }

  async createModelProfile(input: {
    assetId: string;
    baseUrl: string;
    modelName: string;
    credentialId: string;
    apiKey: string;
  }): Promise<Response> {
    await this.selectTab('模型');
    await this.page.getByRole('button', { name: '新建模型', exact: true }).click();
    await expect(this.page.getByLabel('Provider')).toHaveValue('OpenAI-compatible');
    await this.page.getByLabel('资产 ID').fill(input.assetId);
    await this.page.getByLabel('显示名称').fill(`E2E ${input.assetId}`);
    await this.page.getByLabel('API 访问地址').fill(input.baseUrl);
    await this.page.getByLabel('模型名').fill(input.modelName);
    await this.page.getByLabel('Credential ID').fill(input.credentialId);
    await this.page.getByLabel('API Key').fill(input.apiKey);
    await this.page.getByLabel('超时（秒）').fill('5');
    await this.page.getByLabel('温度').fill('0');
    await this.page.getByLabel('最大 tokens').fill('16');
    await this.page.getByLabel('启用模型').check();
    const response = await this.saveWorkingVersion('POST');
    expect(response.status()).toBe(201);
    await expect(this.page.getByLabel('API Key')).toHaveValue('');
    return response;
  }

  async testModelConnection(): Promise<Response> {
    const responsePromise = this.page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && response.url().endsWith('/test-connection'),
    );
    await this.page.getByRole('button', { name: '测试连接', exact: true }).click();
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    await expect(this.page.getByText(/连接成功/)).toBeVisible();
    return response;
  }

  async createRouteRule(assetId: string, scene: string, profileId: string): Promise<Response> {
    await this.selectTab('路由规则');
    await this.page.getByRole('button', { name: '新建路由规则', exact: true }).click();
    await this.page.getByLabel('资产 ID').fill(assetId);
    await this.page.getByLabel('显示名称').fill(`E2E ${assetId}`);
    await this.page.getByLabel('场景').fill(scene);
    const profileSelect = this.page.getByLabel('主模型');
    await expect(profileSelect).toHaveJSProperty('tagName', 'SELECT');
    await profileSelect.selectOption(profileId);
    const response = await this.saveWorkingVersion('POST');
    expect(response.status()).toBe(201);
    return response;
  }

  async activateBaselinePrompt(assetId: string): Promise<void> {
    await this.selectTab('提示词');
    await this.openAsset(assetId);
    const responsePromise = this.page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && response.url().endsWith('/model-governance/drafts'),
    );
    await this.page.getByRole('button', { name: '创建首个草稿' }).click();
    expect((await responsePromise).status()).toBe(201);
  }

  async createPromptVersion(assetId: string, userPrompt: string): Promise<void> {
    await this.selectTab('提示词');
    await this.openAsset(assetId);
    const newVersionButton = this.page.getByRole('button', { name: '新建版本' });
    if (await newVersionButton.isVisible()) {
      const versionPromise = this.page.waitForResponse((response) =>
        response.request().method() === 'POST'
        && response.url().includes(`/model-governance/assets/${assetId}/versions`),
      );
      await newVersionButton.click();
      expect((await versionPromise).status()).toBe(201);
    }
    await this.page.getByLabel('用户提示词模板').fill(userPrompt);
    expect((await this.saveWorkingVersion('PATCH')).status()).toBe(200);
  }

  async completeReviewAndPublish(assetId: string): Promise<void> {
    let responsePromise = this.page.waitForResponse((response) =>
      response.request().method() === 'POST' && response.url().endsWith('/validate'),
    );
    await this.page.getByRole('button', { name: '校验', exact: true }).click();
    expect((await responsePromise).status()).toBe(200);

    responsePromise = this.page.waitForResponse((response) =>
      response.request().method() === 'POST' && response.url().endsWith('/request-review'),
    );
    await this.page.getByRole('button', { name: '申请审核', exact: true }).click();
    expect((await responsePromise).status()).toBe(200);

    await this.selectDeveloperIdentity('reviewer');
    responsePromise = this.page.waitForResponse((response) =>
      response.request().method() === 'POST' && response.url().endsWith('/approve'),
    );
    await this.page.getByRole('button', { name: '审核通过', exact: true }).click();
    expect((await responsePromise).status()).toBe(200);

    await this.selectDeveloperIdentity('editor');
    responsePromise = this.page.waitForResponse((response) =>
      response.request().method() === 'POST' && response.url().endsWith('/publish'),
    );
    await this.page.getByRole('button', { name: '发布到dev环境', exact: true }).click();
    expect((await responsePromise).status()).toBe(200);
    await expect(this.assetRow(assetId)).toContainText('dev 活动版本');
  }

  async rollbackPromptToPrevious(systemPrompt: string, userPrompt: string): Promise<void> {
    const responsePromise = this.page.waitForResponse((response) =>
      response.request().method() === 'POST' && response.url().endsWith('/rollback'),
    );
    const baselineVersion = this.page.getByText('版本 1 · 历史', { exact: true }).locator('..').locator('..');
    await baselineVersion.getByRole('button', { name: '回滚至此版本' }).click();
    expect((await responsePromise).status()).toBe(200);
    await this.expectCurrentPrompt(systemPrompt, userPrompt);
  }
}
