import { Page, Locator } from '@playwright/test';
import { BasePage } from '../base.page';

/**
 * SkillsPage encapsulates the Admin 技能管理 page ( /skills ).
 */
export class SkillsPage extends BasePage {
  readonly pageTitle: Locator;
  readonly skillList: Locator;
  readonly addSkillButton: Locator;
  readonly skillNameInput: Locator;
  readonly skillDescriptionInput: Locator;
  readonly roleFilter: Locator;
  readonly submitButton: Locator;
  readonly deleteButton: Locator;
  readonly enableToggle: Locator;

  constructor(page: Page) {
    super(page, 'http://127.0.0.1:3001');

    this.pageTitle = page.getByRole('heading').or(page.getByText(/技能|Skill/));
    this.skillList = page.locator('table, [class*="skill-list"]');
    this.addSkillButton = page.getByRole('button', { name: /添加|新增|add|create/i });
    this.skillNameInput = page.getByPlaceholder(/名称|name/i).or(
      page.locator('input[id*="name"], input[name*="name"]'),
    );
    this.skillDescriptionInput = page.getByPlaceholder(/描述|description/i).or(
      page.locator('textarea'),
    );
    this.roleFilter = page.getByRole('combobox').or(
      page.locator('select, [class*="filter"]'),
    );
    this.submitButton = page.getByRole('button', { name: /确定|提交|submit|save|保存/i });
    this.deleteButton = page.getByRole('button', { name: /删除|delete|移除/i });
    this.enableToggle = page.locator('[class*="toggle"], [class*="switch"], input[type="checkbox"]');
  }

  /**
   * Navigate to /skills and wait for the page to load.
   */
  async goto(): Promise<void> {
    await super.goto('/skills');
  }

  /**
   * Create a new skill by filling the form and submitting.
   */
  async createSkill(data: {
    name: string;
    description?: string;
    owner?: string;
    steps?: string;
    keywords?: string;
  }): Promise<void> {
    await this.addSkillButton.click();
    await this.skillNameInput.fill(data.name);

    if (data.description) {
      await this.skillDescriptionInput.fill(data.description);
    }

    await this.submitButton.click();
    await this.waitForLoad();
  }

  /**
   * Return a Locator targeting the row containing the given skill name.
   */
  getSkillRow(name: string): Locator {
    return this.skillList.locator('tr, [class*="row"], li').filter({ hasText: name });
  }

  /**
   * Filter the skills list by role.
   */
  async filterByRole(role: string): Promise<void> {
    await this.roleFilter.selectOption(role);
    await this.waitForLoad();
  }

  /**
   * Assert that a skill with the given name is visible.
   */
  async verifySkillExists(name: string): Promise<void> {
    await this.getSkillRow(name).waitFor({ state: 'visible' });
  }

  /**
   * Delete a skill by name: locate its row and click the delete button.
   */
  async deleteSkill(name: string): Promise<void> {
    const row = this.getSkillRow(name);
    await row.locator(this.deleteButton).or(this.deleteButton).click();
    await this.waitForLoad();
  }

  /**
   * Edit an existing skill: click its row, update fields, submit.
   */
  async editSkill(
    name: string,
    data: { name?: string; description?: string },
  ): Promise<void> {
    await this.getSkillRow(name).click();
    if (data.name) {
      await this.skillNameInput.fill(data.name);
    }
    if (data.description) {
      await this.skillDescriptionInput.fill(data.description);
    }
    await this.submitButton.click();
    await this.waitForLoad();
  }

  /**
   * Toggle the enabled/disabled state of a skill.
   */
  async toggleSkill(name: string): Promise<void> {
    const row = this.getSkillRow(name);
    await row.locator(this.enableToggle).click();
    await this.waitForLoad();
  }

  /**
   * Return the number of skills visible in the list.
   */
  async getSkillCount(): Promise<number> {
    return this.skillList.locator('tr, [class*="row"], li').count();
  }
}
