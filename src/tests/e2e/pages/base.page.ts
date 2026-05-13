import { Page } from '@playwright/test';

/**
 * BasePage provides shared navigation, load-state waiting, and screenshot
 * utilities for all Page Object Model classes in the E2E test suite.
 */
export class BasePage {
  protected readonly page: Page;
  protected baseURL: string;

  constructor(page: Page, baseURL: string) {
    this.page = page;
    this.baseURL = baseURL;
  }

  /**
   * Navigate to a path relative to `baseURL`, then wait for the network to
   * become idle.
   */
  async goto(path = '/'): Promise<void> {
    await this.page.goto(`${this.baseURL}${path}`);
    await this.waitForLoad();
  }

  /**
   * Wait until the page reaches the `networkidle` load state.
   */
  async waitForLoad(): Promise<void> {
    await this.page.waitForLoadState('networkidle');
  }

  /**
   * Capture a full-page screenshot saved to `test-results/<name>.png`.
   */
  async takeScreenshot(name: string): Promise<void> {
    await this.page.screenshot({ path: `test-results/${name}.png`, fullPage: true });
  }

  /**
   * Return the current browser URL.
   */
  async getCurrentURL(): Promise<string> {
    return this.page.url();
  }

  /**
   * Pause execution for `ms` milliseconds.
   */
  async waitForTimeout(ms: number): Promise<void> {
    await this.page.waitForTimeout(ms);
  }
}
