import { Locator, Page } from '@playwright/test';
import { BasePage } from '../base.page';

/** 语义指标/值域提议审核页 Page Object。 */
export class SemanticProposalsPage extends BasePage {
  readonly metricTab: Locator;
  readonly valueTab: Locator;
  readonly publishedStatus: Locator;
  readonly successStatus: Locator;

  constructor(page: Page) {
    super(page, `http://127.0.0.1:${process.env.E2E_FRONTEND_PORT ?? 3000}`);
    this.metricTab = page.getByRole('tab', { name: '指标提议' });
    this.valueTab = page.getByRole('tab', { name: '值域提议' });
    this.publishedStatus = page.getByText('已发布', { exact: true });
    this.successStatus = page.getByRole('status');
  }

  async goto(): Promise<void> {
    await this.page.addInitScript(() => {
      window.sessionStorage.setItem('semantic-review-token', 'e2e-review-token');
    });
    await super.goto('/policy-knowledge/knowledge/semantic-discovery');
  }

  proposalCode(code: string): Locator {
    return this.page.getByText(code, { exact: true });
  }

  evidence(text: string): Locator {
    return this.page.getByText(text, { exact: true });
  }

  async expandEvidence(code: string): Promise<void> {
    await this.page.getByRole('button', { name: `展开 ${code} 证据` }).click();
  }

  async acceptAndPublish(code: string): Promise<void> {
    await this.page.getByRole('button', { name: `通过并发布 ${code}` }).click();
  }
}
