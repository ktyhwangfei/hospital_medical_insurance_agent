import { Locator, Page } from '@playwright/test';

import { BasePage } from '../base.page';


/** Portal Skill 版本化资产库 Page Object。 */
export class SkillCatalogPage extends BasePage {
  readonly title: Locator;
  readonly catalogTitle: Locator;
  readonly versionEvidence: Locator;
  readonly evaluationSuite: Locator;
  readonly releasePanel: Locator;

  constructor(page: Page) {
    super(page, 'http://127.0.0.1:3000');
    this.title = page.getByRole('heading', { name: '技能包管理' });
    this.catalogTitle = page.getByText('Skill 版本化资产库');
    this.versionEvidence = page.getByTestId('version-evidence');
    this.evaluationSuite = page.getByTestId('skill-evaluation-suite');
    this.releasePanel = page.getByTestId('skill-release-panel');
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

  async openEvaluation(skillId: string): Promise<void> {
    const row = this.row(skillId);
    await row.getByRole('button', { name: '详情' }).click();
    await this.page.getByRole('tab', { name: '批量评测' }).click();
    await this.evaluationSuite.waitFor({ state: 'visible' });
  }

  async runFixedEvaluation(skillId: string, question: string): Promise<void> {
    await this.openEvaluation(skillId);
    await this.page.getByPlaceholder('输入脱敏后的固定路由问题').fill(question);
    await this.page.getByRole('button', { name: '新增必测用例' }).click();
    await this.evaluationSuite.getByText(question).first().waitFor({ state: 'visible' });
    await this.page.getByRole('button', { name: '运行候选评测' }).click();
    await this.evaluationSuite.getByText('门禁通过').waitFor({ state: 'visible' });
  }

  async approveAndActivateTestRelease(): Promise<void> {
    await this.page.getByRole('tab', { name: '测试发布' }).click();
    await this.releasePanel.waitFor({ state: 'visible' });
    const createButton = this.releasePanel.getByRole('button', { name: '从通过评测创建候选' });
    await createButton.waitFor({ state: 'visible' });
    await createButton.click();
    const requestButton = this.releasePanel.getByRole('button', { name: '申请审批' }).first();
    await requestButton.waitFor({ state: 'visible' });
    await requestButton.click();
    const approveButton = this.releasePanel.getByRole('button', { name: '人工审批通过' }).first();
    await approveButton.waitFor({ state: 'visible' });
    await approveButton.click();
    const activateButton = this.releasePanel.getByRole('button', { name: '激活到 test' }).first();
    await activateButton.waitFor({ state: 'visible' });
    await activateButton.click();
    await this.releasePanel.getByText('test active').first().waitFor({ state: 'visible' });
  }
}
