import { Page, Locator } from '@playwright/test';
import { BasePage } from '../base.page';

/**
 * QCPage encapsulates the 出院前联合质控 page ( /qc ).
 */
export class QCPage extends BasePage {
  readonly pageTitle: Locator;
  readonly qcList: Locator;
  readonly qcItem: Locator;
  readonly qcStatus: Locator;
  readonly submitButton: Locator;

  constructor(page: Page) {
    super(page, 'http://127.0.0.1:3000');

    this.pageTitle = page.getByRole('heading').or(page.getByText(/质控|QC/));
    this.qcList = page.locator('table, [class*="qc-list"], [class*="checklist"]');
    this.qcItem = this.qcList.locator('tr, [class*="item"], li');
    this.qcStatus = page.locator('[class*="status"], [class*="badge"]');
    this.submitButton = page.getByRole('button', { name: /提交|submit|确认/ });
  }

  /**
   * Navigate to /qc and wait for the page to load.
   */
  async goto(): Promise<void> {
    await super.goto('/qc');
  }

  /**
   * Assert that QC items have loaded (at least one visible).
   */
  async verifyQcItemsLoaded(): Promise<void> {
    await this.qcItem.first().waitFor({ state: 'visible' });
  }

  /**
   * Return the count of QC items on the page.
   */
  async getQcItemCount(): Promise<number> {
    return this.qcItem.count();
  }

  /**
   * Click a QC item by its zero-based index.
   */
  async clickQCItem(index: number): Promise<void> {
    await this.qcItem.nth(index).click();
    await this.waitForLoad();
  }

  /**
   * Assert that a QC result or status display is visible.
   */
  async verifyQCResult(): Promise<void> {
    await this.qcStatus.first().waitFor({ state: 'visible' });
  }
}
