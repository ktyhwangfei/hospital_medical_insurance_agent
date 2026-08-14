import { type Locator, type Page, type Response } from '@playwright/test';

import { BasePage } from '../base.page';

/** Portal 模型治理只读台账 Page Object。 */
export class ModelGovernancePage extends BasePage {
  readonly roleSwitcher: Locator;
  readonly modelGovernanceLink: Locator;
  readonly title: Locator;
  readonly promptLedgerTitle: Locator;

  constructor(page: Page) {
    super(page, process.env.PORTAL_BASE_URL ?? 'http://127.0.0.1:3000');
    this.roleSwitcher = page.locator('header').getByRole('combobox');
    this.modelGovernanceLink = page.getByRole('link', { name: '模型治理', exact: true });
    this.title = page.getByRole('heading', { name: '模型与提示词治理', exact: true });
    this.promptLedgerTitle = page.getByRole('heading', { name: '提示词台账', exact: true });
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
}
