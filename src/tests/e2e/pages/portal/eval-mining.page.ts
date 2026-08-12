import { type Locator, type Page } from '@playwright/test';

import { BasePage } from '../base.page';

/** 错误案例挖掘页 Page Object（案例池列表 + 分型编辑确认）。 */
export class EvalMiningPage extends BasePage {
  readonly list: Locator;
  readonly heading: Locator;

  constructor(page: Page) {
    super(page, 'http://127.0.0.1:3000');
    this.heading = page.getByRole('heading', { name: '案例挖掘' });
    this.list = page.getByTestId('eval-case-pool-list');
  }

  async goto(): Promise<void> {
    await super.goto('/skills/eval-mining');
    await this.heading.waitFor({ state: 'visible' });
  }

  row(poolId: string): Locator {
    return this.page.getByTestId(`eval-case-pool-row-${poolId}`);
  }

  async transform(poolId: string): Promise<void> {
    await this.row(poolId).getByRole('button', { name: 'AI 转换' }).click();
  }

  async openEditor(poolId: string): Promise<void> {
    await this.row(poolId).getByRole('button', { name: '编辑确认' }).click();
  }

  dimensionSelect(poolId: string): Locator {
    return this.page.getByTestId(`eval-case-pool-dimension-${poolId}`);
  }

  async confirm(poolId: string): Promise<void> {
    await this.row(poolId).getByRole('button', { name: '确认投影' }).click();
  }

  async reject(poolId: string): Promise<void> {
    await this.row(poolId).getByRole('button', { name: '拒绝' }).click();
  }
}
