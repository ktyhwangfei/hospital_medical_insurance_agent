import { type Locator, type Page } from '@playwright/test';

import { BasePage } from '../base.page';
import { E2E_FRONTEND_URL } from '../../utils/workspace-ports';

/** Policy QA chat-first page object. */
export class PolicyQAPage extends BasePage {
  readonly composer: Locator;
  readonly sendButton: Locator;
  readonly answer: Locator;
  readonly verification: Locator;
  readonly settlementChip: Locator;
  readonly sourcesButton: Locator;
  readonly sourcesDialog: Locator;
  readonly doneIndicator: Locator;
  readonly feedbackDrawer: Locator;
  readonly feedbackSubmitted: Locator;

  constructor(page: Page) {
    super(page, E2E_FRONTEND_URL);
    this.composer = page.locator('[data-testid="policy-qa-composer"] textarea');
    this.sendButton = page.getByRole('button', { name: '发送' });
    this.answer = page.locator('[data-testid="policy-qa-answer"]');
    this.verification = page.locator('[data-testid="policy-qa-verification"]');
    this.settlementChip = page.getByTestId('policy-qa-composer').getByText(/结算单 \d+/);
    this.sourcesButton = page.getByRole('button', { name: /查看 \d+ 条政策来源/ });
    this.sourcesDialog = page.locator('[data-testid="policy-qa-sources"]');
    this.doneIndicator = page.locator('[data-testid="policy-qa-stream-done"]');
    this.feedbackDrawer = page.locator('[data-testid="policy-qa-feedback-drawer"]');
    this.feedbackSubmitted = page.locator('[data-testid="policy-qa-feedback-submitted"]');
  }

  async goto(): Promise<void> {
    await super.goto('/policy-qa');
  }

  async ask(question: string): Promise<void> {
    const previousAnswers = await this.answer.count();
    await this.composer.fill(question);
    await this.sendButton.click();
    await this.answer.nth(previousAnswers).waitFor({ state: 'visible', timeout: 60_000 });
    await this.waitForDone();
  }

  async waitForDone(): Promise<void> {
    await this.doneIndicator.waitFor({ state: 'visible', timeout: 60_000 });
  }

  async openSources(): Promise<void> {
    await this.sourcesButton.last().click();
    await this.sourcesDialog.waitFor({ state: 'visible' });
  }

  async readAnswer(): Promise<string> {
    return this.answer.last().innerText();
  }

  /** 点击某条「回答有误」原因码提交反馈。 */
  async submitFeedback(reasonCode: string): Promise<void> {
    await this.feedbackDrawer
      .getByTestId(`policy-qa-feedback-reason-${reasonCode}`)
      .click();
    await this.feedbackSubmitted.waitFor({ state: 'visible' });
  }
}
