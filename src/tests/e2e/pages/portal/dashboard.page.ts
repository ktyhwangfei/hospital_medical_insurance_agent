import { Page, Locator } from '@playwright/test';
import { BasePage } from '../base.page';

/**
 * DashboardPage encapsulates the 运营看板 page ( /dashboard ).
 */
export class DashboardPage extends BasePage {
  readonly pageTitle: Locator;
  readonly chartArea: Locator;
  readonly statsCards: Locator;
  readonly refreshButton: Locator;

  constructor(page: Page) {
    super(page, 'http://127.0.0.1:3000');

    this.pageTitle = page.getByRole('heading').or(page.getByText(/看板|Dashboard/));
    this.chartArea = page.locator('[class*="chart"], [class*="graph"], svg, canvas');
    this.statsCards = page.locator('[class*="card"], [class*="stat"]');
    this.refreshButton = page.getByRole('button', { name: /刷新|refresh|reload/i });
  }

  /**
   * Navigate to /dashboard and wait for the page to load.
   */
  async goto(): Promise<void> {
    await super.goto('/dashboard');
  }

  /**
   * Assert that chart elements have rendered (at least one visible).
   */
  async verifyChartsLoaded(): Promise<void> {
    await this.chartArea.first().waitFor({ state: 'visible' });
  }

  /**
   * Return the count of statistic card elements on the page.
   */
  async getStatsCardCount(): Promise<number> {
    return this.statsCards.count();
  }
}
