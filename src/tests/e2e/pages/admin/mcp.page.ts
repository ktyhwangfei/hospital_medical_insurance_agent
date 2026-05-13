import { Page, Locator } from '@playwright/test';
import { BasePage } from '../base.page';

/**
 * MCPPage encapsulates the Admin MCP管理 page ( /mcp ).
 */
export class MCPPage extends BasePage {
  readonly pageTitle: Locator;
  readonly serverList: Locator;
  readonly addServerButton: Locator;
  readonly serverNameInput: Locator;
  readonly serverEndpointInput: Locator;
  readonly transportSelect: Locator;
  readonly submitButton: Locator;
  readonly capabilityList: Locator;
  readonly deleteButton: Locator;
  readonly healthIndicator: Locator;

  constructor(page: Page) {
    super(page, 'http://127.0.0.1:3001');

    this.pageTitle = page.getByRole('heading').or(page.getByText(/MCP/));
    this.serverList = page.locator('table, [class*="server-list"]');
    this.addServerButton = page.getByRole('button', { name: /添加|新增|add|register|注册/i });
    this.serverNameInput = page.getByPlaceholder(/名称|name/i).or(
      page.locator('input[id*="name"], input[name*="name"]'),
    );
    this.serverEndpointInput = page.getByPlaceholder(/endpoint|地址|url/i).or(
      page.locator('input[id*="endpoint"], input[name*="endpoint"]'),
    );
    this.transportSelect = page.getByRole('combobox').or(page.locator('select'));
    this.submitButton = page.getByRole('button', { name: /确定|提交|submit|save|保存/i });
    this.capabilityList = page.locator('[class*="capability"]');
    this.deleteButton = page.getByRole('button', { name: /删除|delete|移除/i });
    this.healthIndicator = page.locator('[class*="health"], [class*="status"]');
  }

  /**
   * Navigate to /mcp and wait for the page to load.
   */
  async goto(): Promise<void> {
    await super.goto('/mcp');
  }

  /**
   * Register a new MCP server by filling the form and submitting.
   */
  async registerServer(data: { name: string; endpoint?: string; transport?: string }): Promise<void> {
    await this.addServerButton.click();
    await this.serverNameInput.fill(data.name);

    if (data.endpoint) {
      await this.serverEndpointInput.fill(data.endpoint);
    }

    if (data.transport) {
      await this.transportSelect.selectOption(data.transport);
    }

    await this.submitButton.click();
    await this.waitForLoad();
  }

  /**
   * Return a Locator targeting the row containing the given server name.
   */
  getServerRow(name: string): Locator {
    return this.serverList.locator('tr, [class*="row"], li').filter({ hasText: name });
  }

  /**
   * Click a server row to view its capabilities.
   */
  async viewServerCapabilities(name: string): Promise<void> {
    await this.getServerRow(name).click();
    await this.capabilityList.first().waitFor({ state: 'visible' });
  }

  /**
   * Delete a server by name: locate its row, click delete, confirm if
   * necessary.
   */
  async deleteServer(name: string): Promise<void> {
    const row = this.getServerRow(name);
    await row.locator(this.deleteButton).or(this.deleteButton).click();
    await this.waitForLoad();
  }

  /**
   * Assert that a server with the given name is visible.
   */
  async verifyServerExists(name: string): Promise<void> {
    await this.getServerRow(name).waitFor({ state: 'visible' });
  }

  /**
   * Assert that no server with the given name is visible.
   */
  async verifyServerNotExists(name: string): Promise<void> {
    await this.getServerRow(name).waitFor({ state: 'hidden', timeout: 10_000 });
  }

  /**
   * Check the health status element for the given server name.
   */
  async checkHealth(name: string): Promise<void> {
    const row = this.getServerRow(name);
    await row.locator(this.healthIndicator).first().waitFor({ state: 'visible' });
  }
}
