import { Locator, Page } from '@playwright/test';
import { BasePage } from '../base.page';

/** 政策知识三栏工作台与统一测试页 Page Object。 */
export class PolicyKnowledgePage extends BasePage {
  readonly navigation: Locator;
  readonly workbenchTitle: Locator;
  readonly unitColumn: Locator;
  readonly knowledgeColumn: Locator;
  readonly standardizationColumn: Locator;
  readonly testTitle: Locator;
  readonly qualityGate: Locator;
  readonly publishButton: Locator;
  readonly scopedPublishButtons: Locator;

  constructor(page: Page) {
    super(page, 'http://127.0.0.1:3000');
    this.navigation = page.getByRole('navigation');
    this.workbenchTitle = page.getByRole('heading', { name: '政策知识对齐工作台' });
    this.unitColumn = page.getByRole('heading', { name: '审核通过的单元' });
    this.knowledgeColumn = page.getByRole('heading', { name: '结构化知识' });
    this.standardizationColumn = page.getByRole('heading', { name: '指标与值域标化' });
    this.testTitle = page.getByRole('heading', { name: '政策知识测试' });
    this.qualityGate = page.getByRole('heading', { name: '候选版与活动版同集对跑' });
    this.publishButton = page.getByRole('button', { name: '人工发布候选版本' });
    this.scopedPublishButtons = page.getByRole('button', { name: /发布.*Unit|发布.*Knowledge/ });
  }

  async gotoKnowledge(): Promise<void> {
    await super.goto('/policy-knowledge/knowledge');
  }

  async gotoTest(): Promise<void> {
    await super.goto('/policy-knowledge/test');
  }

  async navLabels(): Promise<string[]> {
    return this.navigation.getByRole('button').allTextContents();
  }

  unit(unitId: string): Locator {
    return this.page.locator(`#policy-unit-${unitId}`);
  }

  knowledge(knowledgeId: string): Locator {
    return this.page.locator(`#policy-knowledge-${knowledgeId}`);
  }

  async selectUnit(unitId: string): Promise<void> {
    await this.unit(unitId).click();
  }

  async selectKnowledge(knowledgeId: string): Promise<void> {
    await this.knowledge(knowledgeId).click();
  }

  async runCandidate(): Promise<void> {
    await this.page.getByRole('button', { name: '批量统一测试' }).click();
  }
}
