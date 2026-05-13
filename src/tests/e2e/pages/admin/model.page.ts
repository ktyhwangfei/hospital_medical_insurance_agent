import { Page, Locator } from '@playwright/test';
import { BasePage } from '../base.page';

/**
 * ModelPage encapsulates the Admin 模型管理 page ( /model ).
 */
export class ModelPage extends BasePage {
  readonly pageTitle: Locator;
  readonly configSection: Locator;
  readonly routesList: Locator;
  readonly providersList: Locator;
  readonly addProviderButton: Locator;
  readonly providerNameInput: Locator;
  readonly providerEndpointInput: Locator;
  readonly apiKeyInput: Locator;
  readonly testButton: Locator;
  readonly testResult: Locator;
  readonly testStreamButton: Locator;

  constructor(page: Page) {
    super(page, 'http://127.0.0.1:3001');

    this.pageTitle = page.getByRole('heading').or(page.getByText(/模型|Model/));
    this.configSection = page.locator('[class*="config"], [class*="settings"]');
    this.routesList = page.locator('table, [class*="route"]').first();
    this.providersList = page.locator('[class*="provider-list"], table').last();
    this.addProviderButton = page.getByRole('button', { name: /添加.*Provider|add.*provider|注册.*provider/i });
    this.providerNameInput = page.getByPlaceholder(/名称|name/i).or(
      page.locator('input[id*="provider"], input[name*="provider"]'),
    );
    this.providerEndpointInput = page.getByPlaceholder(/endpoint|地址|url/i).or(
      page.locator('input[id*="endpoint"], input[name*="endpoint"]'),
    );
    this.apiKeyInput = page.getByPlaceholder(/api.*key|密钥|key/i).or(
      page.locator('input[type="password"], input[id*="key"]'),
    );
    this.testButton = page.getByRole('button', { name: /测试|test/i });
    this.testResult = page.locator('[class*="test-result"], [class*="response"]');
    this.testStreamButton = page.getByRole('button', { name: /流式|stream/i });
  }

  /**
   * Navigate to /model and wait for the page to load.
   */
  async goto(): Promise<void> {
    await super.goto('/model');
  }

  /**
   * Register a new model provider by filling the form and submitting.
   */
  async registerProvider(data: {
    name: string;
    endpoint: string;
    apiKey?: string;
  }): Promise<void> {
    await this.addProviderButton.click();
    await this.providerNameInput.fill(data.name);
    await this.providerEndpointInput.fill(data.endpoint);

    if (data.apiKey) {
      await this.apiKeyInput.fill(data.apiKey);
    }

    await this.page.getByRole('button', { name: /确定|提交|submit|save|保存/i }).click();
    await this.waitForLoad();
  }

  /**
   * Click the test/连通性 button for the given provider name.
   */
  async testProvider(name: string): Promise<void> {
    const row = this.providersList.locator('tr, [class*="row"]').filter({ hasText: name });
    await row.locator(this.testButton).click();
  }

  /**
   * Assert that a test result element is visible.
   */
  async verifyTestResult(): Promise<void> {
    await this.testResult.first().waitFor({ state: 'visible', timeout: 30_000 });
  }

  /**
   * Click the stream-test button for the given provider name.
   */
  async testProviderStream(name: string): Promise<void> {
    const row = this.providersList.locator('tr, [class*="row"]').filter({ hasText: name });
    await row.locator(this.testStreamButton).click();
  }

  /**
   * Return the number of registered providers.
   */
  async getProviderCount(): Promise<number> {
    return this.providersList.locator('tr, [class*="row"]').count();
  }
}
