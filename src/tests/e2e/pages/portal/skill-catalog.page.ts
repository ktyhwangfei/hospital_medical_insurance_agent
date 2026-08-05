import { Locator, Page } from '@playwright/test';

import { BasePage } from '../base.page';


/** Portal Skill 版本化资产库 Page Object。 */
export class SkillCatalogPage extends BasePage {
  readonly title: Locator;
  readonly catalogTitle: Locator;
  readonly versionEvidence: Locator;

  constructor(page: Page) {
    super(page, 'http://127.0.0.1:3000');
    this.title = page.getByRole('heading', { name: '技能包管理' });
    this.catalogTitle = page.getByText('Skill 版本化资产库');
    this.versionEvidence = page.getByTestId('version-evidence');
  }

  async goto(): Promise<void> {
    await super.goto('/skills');
  }

  row(skillId: string): Locator {
    return this.page.getByTestId(`skill-row-${skillId}`);
  }

  async openVersionEvidence(skillId: string): Promise<void> {
    const row = this.row(skillId);
    await row.getByRole('button', { name: '详情' }).click();
    await this.page.getByRole('tab', { name: '版本证据' }).click();
    await this.versionEvidence.waitFor({ state: 'visible' });
  }

  async registerCurrentVersion(skillId: string): Promise<void> {
    await this.openVersionEvidence(skillId);
    const registerButton = this.page.getByTestId('register-skill-version');
    if (await registerButton.isVisible()) {
      await registerButton.click();
      await registerButton.waitFor({ state: 'hidden' });
    }
  }
}
