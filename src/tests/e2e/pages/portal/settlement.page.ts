import { Page, Locator } from '@playwright/test';
import { BasePage } from '../base.page';

/**
 * SettlementPage encapsulates the 结算异常导办 page ( /settlement ).
 */
export class SettlementPage extends BasePage {
  readonly pageTitle: Locator;
  readonly exceptionList: Locator;
  readonly patientFilter: Locator;
  readonly patientRow: Locator;
  readonly guideSteps: Locator;
  readonly confirmButton: Locator;

  constructor(page: Page) {
    super(page, 'http://127.0.0.1:3000');

    this.pageTitle = page.getByRole('heading').or(page.getByText(/结算异常/));
    this.exceptionList = page.locator('table, [class*="exception"], [class*="settlement"]');
    this.patientFilter = page.getByPlaceholder(/患者|patient|search/i).or(
      page.locator('input[class*="filter"], input[class*="search"]'),
    );
    this.patientRow = this.exceptionList.locator('tr, [class*="row"], li');
    this.guideSteps = page.locator('[class*="guide"], [class*="step"]');
    this.confirmButton = page.getByRole('button', { name: /确认|confirm|确定/i });
  }

  /**
   * Navigate to /settlement and wait for the page to load.
   */
  async goto(): Promise<void> {
    await super.goto('/settlement');
  }

  /**
   * Filter the exception list by patient ID.
   */
  async selectPatient(patientId: string): Promise<void> {
    await this.patientFilter.fill(patientId);
    await this.page.keyboard.press('Enter');
    await this.waitForLoad();
  }

  /**
   * Assert that the exception list contains at least one visible item.
   */
  async verifyExceptionList(): Promise<void> {
    await this.patientRow.first().waitFor({ state: 'visible' });
  }

  /**
   * Return the number of rows / items in the exception list.
   */
  async getExceptionCount(): Promise<number> {
    return this.patientRow.count();
  }

  /**
   * Click the first row in the exception list.
   */
  async clickFirstException(): Promise<void> {
    await this.patientRow.first().click();
    await this.waitForLoad();
  }

  /**
   * Assert that guidance-step elements are visible.
   */
  async verifyGuideStepsVisible(): Promise<void> {
    await this.guideSteps.first().waitFor({ state: 'visible' });
  }
}
