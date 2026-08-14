import { expect, type Locator, type Page, type Response } from '@playwright/test';

import { BasePage } from '../base.page';

/** Portal 模型治理台账与开发管理 Page Object。 */
export class ModelGovernancePage extends BasePage {
  readonly roleSwitcher: Locator;
  readonly modelGovernanceLink: Locator;
  readonly title: Locator;
  readonly promptLedgerTitle: Locator;
  readonly developerIdentity: Locator;

  constructor(page: Page) {
    super(page, process.env.PORTAL_BASE_URL ?? 'http://127.0.0.1:3000');
    this.roleSwitcher = page.locator('header').getByRole('combobox');
    this.modelGovernanceLink = page.getByRole('link', { name: '模型治理', exact: true });
    this.title = page.getByRole('heading', { name: '模型与提示词治理', exact: true });
    this.promptLedgerTitle = page.getByRole('heading', { name: '提示词台账', exact: true });
    this.developerIdentity = page.getByLabel('开发身份');
  }

  async goto(): Promise<void> {
    await super.goto('/');
  }

  async useMobileViewport(): Promise<void> {
    await this.page.setViewportSize({ width: 390, height: 844 });
  }

  async switchToInformationDepartment(): Promise<void> {
    await this.roleSwitcher.click();
    await this.page.getByRole('option', { name: /信息科/ }).click();
  }

  async openAndWaitForSnapshot(): Promise<Response> {
    const responsePromise = this.page.waitForResponse((response) =>
      response.request().method() === 'GET'
      && response.url().includes('/model-governance/snapshot'),
    );
    await this.modelGovernanceLink.click();
    return responsePromise;
  }

  async hasNoHorizontalOverflow(): Promise<boolean> {
    return this.page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    );
  }

  assetCard(assetId: string): Locator {
    return this.page.locator('article').filter({ hasText: assetId });
  }

  private async selectTab(name: '提示词' | '模型档案' | '路由规则' | '发布记录'): Promise<void> {
    await this.page.getByRole('tab', { name, exact: true }).click();
  }

  private async saveDraft(): Promise<Response> {
    const responsePromise = this.page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && response.url().endsWith('/model-governance/drafts'),
    );
    await this.page.getByRole('button', { name: '保存草稿', exact: true }).click();
    return responsePromise;
  }

  async selectDeveloperIdentity(identity: 'editor' | 'reviewer'): Promise<void> {
    await this.developerIdentity.selectOption(identity);
  }

  async createModelProfile(assetId: string, modelName: string): Promise<void> {
    await this.selectTab('模型档案');
    await this.page.getByRole('button', { name: '新建模型档案', exact: true }).click();
    const panel = this.page.getByRole('tabpanel');
    await panel.getByLabel('资产标识').fill(assetId);
    await panel.getByLabel('显示名称').fill(`E2E ${assetId}`);
    await panel.getByLabel('模型名').fill(modelName);
    expect((await this.saveDraft()).status()).toBe(201);
    await expect(this.assetCard(assetId).first()).toContainText('编辑中');
  }

  async createRouteRule(assetId: string, scene: string, profileId: string): Promise<void> {
    await this.selectTab('路由规则');
    await this.page.getByRole('button', { name: '新建路由规则', exact: true }).click();
    const panel = this.page.getByRole('tabpanel');
    await panel.getByLabel('资产标识').fill(assetId);
    await panel.getByLabel('显示名称').fill(`E2E ${assetId}`);
    await panel.getByLabel('场景').fill(scene);
    await panel.getByLabel('主模型档案').fill(profileId);
    expect((await this.saveDraft()).status()).toBe(201);
    await expect(this.assetCard(assetId).first()).toContainText('编辑中');
  }

  async createPromptDraft(assetId: string, template: string): Promise<void> {
    await this.selectTab('提示词');
    await this.page.getByRole('button', { name: '新建提示词', exact: true }).click();
    const panel = this.page.getByRole('tabpanel');
    await panel.getByLabel('提示词标识').fill(assetId);
    await panel.getByLabel('显示名称').fill(`E2E ${assetId}`);
    await panel.getByLabel('用户提示词模板').fill(template);
    expect((await this.saveDraft()).status()).toBe(201);
    await expect(this.assetCard(assetId).first()).toContainText('编辑中');
  }

  async completeReviewAndPublish(assetId: string): Promise<void> {
    const card = this.assetCard(assetId).first();
    let responsePromise = this.page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && response.url().includes('/validate'),
    );
    await card.getByRole('button', { name: '校验', exact: true }).click();
    expect((await responsePromise).status()).toBe(200);
    await expect(card).toContainText('已校验');

    responsePromise = this.page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && response.url().includes('/request-review'),
    );
    await card.getByRole('button', { name: '申请审核', exact: true }).click();
    expect((await responsePromise).status()).toBe(200);
    await expect(card).toContainText('待审核');

    await this.selectDeveloperIdentity('reviewer');
    responsePromise = this.page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && response.url().includes('/approve'),
    );
    await card.getByRole('button', { name: '审核通过', exact: true }).click();
    expect((await responsePromise).status()).toBe(200);
    await expect(card).toContainText('已审核');

    await this.selectDeveloperIdentity('editor');
    responsePromise = this.page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && response.url().includes('/publish'),
    );
    await card.getByRole('button', { name: '发布到开发环境', exact: true }).click();
    expect((await responsePromise).status()).toBe(200);
    await expect(this.assetCard(assetId).first()).toContainText('已发布，待接入');
  }

  async rollbackToPreviousRelease(assetId: string): Promise<void> {
    await this.selectTab('发布记录');
    const historical = this.page.locator('article')
      .filter({ hasText: assetId })
      .filter({ hasText: '历史版本' })
      .first();
    const responsePromise = this.page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && response.url().includes('/rollback'),
    );
    await historical.getByRole('button', { name: '回滚至此版本', exact: true }).click();
    expect((await responsePromise).status()).toBe(200);
    await this.selectTab('提示词');
  }
}
