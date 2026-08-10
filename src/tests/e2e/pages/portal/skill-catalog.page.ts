import { Locator, Page } from '@playwright/test';

import { BasePage } from '../base.page';


/** Portal Skill 治理工作台 Page Object。 */
export class SkillCatalogPage extends BasePage {
  readonly title: Locator;
  readonly workspace: Locator;
  readonly lifecycle: Locator;
  readonly routeDrawer: Locator;
  readonly evaluationSuite: Locator;
  readonly releasePanel: Locator;

  constructor(page: Page) {
    super(page, (process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:3000').replace(/\/$/, ''));
    this.title = page.getByRole('heading', { name: 'Skill 管理' });
    this.workspace = page.getByTestId('skill-governance-workbench');
    this.lifecycle = page.getByLabel('Skill 生命周期');
    this.routeDrawer = page.getByRole('dialog', { name: '路由调试' });
    this.evaluationSuite = page.getByTestId('skill-evaluation-suite');
    this.releasePanel = page.getByTestId('skill-release-panel');
  }

  async goto(): Promise<void> {
    await super.goto('/skills');
    await this.title.waitFor({ state: 'visible' });
  }

  async gotoAIAuthoring(): Promise<void> {
    await super.goto('/skills/new');
    await this.page.getByRole('button', { name: 'AI 创建' }).click();
    await this.page.getByRole('heading', { name: 'AI 创建 Skill 草稿' }).waitFor({ state: 'visible' });
  }

  async generateAndAcceptAIDraft(metricName: string, description: string): Promise<void> {
    await this.page.getByPlaceholder('描述你希望 Skill 完成的能力').fill(description);
    await this.page.getByLabel(metricName).check();
    await this.page.getByRole('button', { name: '生成候选' }).click();
    await this.page.getByText('尚未进入运行时').waitFor({ state: 'visible' });
    await this.page.getByRole('button', { name: '接受为草稿' }).click();
    await this.page.getByRole('heading', { name: /\u7f16\u8f91\u8349\u7a3f/ }).waitFor({ state: 'visible' });
  }

  async optimizeValidateAndEvaluateCandidate(): Promise<void> {
    await this.page.getByLabel('AI 优化要求').fill('简化解释并补充收费员提示');
    await this.page.getByRole('button', { name: '生成优化提案' }).click();
    await this.page.getByRole('region', { name: 'AI 优化差异' }).waitFor({ state: 'visible' });
    await this.page.getByRole('button', { name: '接受优化' }).click();
    await this.page.getByText('优化已接受并保存').waitFor({ state: 'visible' });
    await this.page.getByRole('button', { name: '校验' }).click();
    await this.page.getByRole('button', { name: '运行候选路由评测' }).click();
    await this.page.getByText('路由评测：已完成').waitFor({ state: 'visible' });
    await this.page.getByRole('button', { name: '运行候选行为评测' }).click();
    await this.page.getByText('行为评测：已完成').waitFor({ state: 'visible' });
  }

  catalogItem(skillId: string): Locator {
    return this.page.getByTestId(`skill-catalog-item-${skillId}`);
  }

  async selectSkill(skillId: string): Promise<void> {
    await this.catalogItem(skillId).click();
    await this.page.getByTestId(`skill-workspace-${skillId}`).waitFor({ state: 'visible' });
  }

  async openTab(name: '总览' | '版本' | '评测' | '发布' | '开发详情'): Promise<void> {
    await this.page.getByRole('tab', { name }).click();
  }

  async registerCurrentVersion(skillId: string): Promise<void> {
    await this.selectSkill(skillId);
    await this.openTab('版本');
    const registerButton = this.page.getByTestId('register-skill-version');
    if (await registerButton.isVisible()) {
      await registerButton.click();
      await registerButton.waitFor({ state: 'hidden' });
    }
  }

  async runFixedEvaluation(question: string): Promise<void> {
    await this.openTab('评测');
    await this.evaluationSuite.waitFor({ state: 'visible' });
    await this.page.getByLabel('脱敏评测问题').fill(question);
    await this.page.getByRole('button', { name: '新增必测用例' }).click();
    await this.evaluationSuite.getByText(question).first().waitFor({ state: 'visible' });
    await this.page.getByRole('button', { name: '运行候选评测' }).click();
    await this.evaluationSuite.getByText('门禁通过').waitFor({ state: 'visible' });
  }

  async approveAndActivateTestRelease(): Promise<void> {
    await this.openTab('发布');
    await this.releasePanel.waitFor({ state: 'visible' });
    for (const action of [
      '从通过评测创建候选',
      '申请审批',
      '人工审批通过',
      '激活 Test Shadow',
    ]) {
      const button = this.releasePanel.getByRole('button', { name: action });
      await button.waitFor({ state: 'visible' });
      await button.click();
    }
    await this.releasePanel.getByText('Test Shadow 已激活').waitFor({ state: 'visible' });
  }
}
