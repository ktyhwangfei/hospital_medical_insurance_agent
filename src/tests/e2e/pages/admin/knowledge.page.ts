import { Page, Locator } from '@playwright/test';
import { BasePage } from '../base.page';

/**
 * KnowledgePage encapsulates the Admin 知识管理 page ( /knowledge ).
 *
 * The page contains six tabs: 错误码 (error-codes), 规则 (rules), 资产
 * (assets), 切片 (chunks), 申诉模板 (appeal-templates), 提示模板
 * (prompt-templates).
 */
export class KnowledgePage extends BasePage {
  readonly tabErrorCodes: Locator;
  readonly tabRules: Locator;
  readonly tabAssets: Locator;
  readonly tabChunks: Locator;
  readonly tabAppealTemplates: Locator;
  readonly tabPromptTemplates: Locator;

  readonly itemList: Locator;
  readonly addButton: Locator;
  readonly nameInput: Locator;
  readonly contentInput: Locator;
  readonly submitButton: Locator;
  readonly deleteButton: Locator;

  constructor(page: Page) {
    super(page, 'http://127.0.0.1:3001');

    this.tabErrorCodes = page.getByRole('tab', { name: /错误码|error/i });
    this.tabRules = page.getByRole('tab', { name: /规则|rule/i });
    this.tabAssets = page.getByRole('tab', { name: /资产|asset/i });
    this.tabChunks = page.getByRole('tab', { name: /切片|chunk/i });
    this.tabAppealTemplates = page.getByRole('tab', { name: /申诉|appeal/i });
    this.tabPromptTemplates = page.getByRole('tab', { name: /提示|prompt/i });

    this.itemList = page.locator('table, [class*="list"]');
    this.addButton = page.getByRole('button', { name: /添加|新增|add|create/i });
    this.nameInput = page.getByPlaceholder(/名称|name|title/i).or(
      page.locator('input[id*="name"], input[name*="name"]'),
    );
    this.contentInput = page.getByPlaceholder(/内容|content/i).or(
      page.locator('textarea, [class*="editor"]'),
    );
    this.submitButton = page.getByRole('button', { name: /确定|提交|submit|save|保存/i });
    this.deleteButton = page.getByRole('button', { name: /删除|delete|移除/i });
  }

  /**
   * Navigate to /knowledge and wait for the page to load.
   */
  async goto(): Promise<void> {
    await super.goto('/knowledge');
  }

  /**
   * Activate a knowledge tab by its display name.
   *
   * Valid `tabName` values: 'error-codes', 'rules', 'assets', 'chunks',
   * 'appeal-templates', 'prompt-templates'.
   */
  async switchTab(tabName: string): Promise<void> {
    const tabMap: Record<string, Locator> = {
      'error-codes': this.tabErrorCodes,
      rules: this.tabRules,
      assets: this.tabAssets,
      chunks: this.tabChunks,
      'appeal-templates': this.tabAppealTemplates,
      'prompt-templates': this.tabPromptTemplates,
    };

    const tab = tabMap[tabName];
    if (!tab) {
      throw new Error(`Unknown tab: ${tabName}. Valid: ${Object.keys(tabMap).join(', ')}`);
    }

    await tab.click();
    await this.itemList.first().waitFor({ state: 'visible' });
  }

  /**
   * Return a Locator targeting the row containing the given item name.
   */
  getItemRow(name: string): Locator {
    return this.itemList.locator('tr, [class*="row"], li').filter({ hasText: name });
  }

  /**
   * Create a new knowledge item under the active tab.
   *
   * `data` should contain `name` and optionally `content`.
   */
  async createItem(data: { name: string; content?: string }): Promise<void> {
    await this.addButton.click();
    await this.nameInput.fill(data.name);

    if (data.content) {
      await this.contentInput.fill(data.content);
    }

    await this.submitButton.click();
    await this.waitForLoad();
  }

  /**
   * Assert that an item with the given name is visible in the current tab.
   */
  async verifyItemExists(name: string): Promise<void> {
    await this.getItemRow(name).waitFor({ state: 'visible' });
  }

  /**
   * Delete an item by name: locate its row and click the delete button.
   */
  async deleteItem(name: string): Promise<void> {
    const row = this.getItemRow(name);
    await row.locator(this.deleteButton).or(this.deleteButton).click();
    await this.waitForLoad();
  }

  /**
   * Edit an existing item: click its row, update fields, submit.
   */
  async editItem(
    name: string,
    data: { name?: string; content?: string },
  ): Promise<void> {
    await this.getItemRow(name).click();
    if (data.name) {
      await this.nameInput.fill(data.name);
    }
    if (data.content) {
      await this.contentInput.fill(data.content);
    }
    await this.submitButton.click();
    await this.waitForLoad();
  }

  /**
   * Return the number of rows / items visible in the current tab.
   */
  async getItemCount(): Promise<number> {
    return this.itemList.locator('tr, [class*="row"], li').count();
  }
}
