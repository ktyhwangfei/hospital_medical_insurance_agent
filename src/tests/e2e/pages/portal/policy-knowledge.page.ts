import { Locator, Page } from '@playwright/test';
import { BasePage } from '../base.page';

/** 政策知识构建、审核、发布与统一测试页 Page Object。 */
export class PolicyKnowledgePage extends BasePage {
  readonly navigation: Locator;
  readonly buildTitle: Locator;
  readonly newBuildTaskButton: Locator;
  readonly reviewTitle: Locator;
  readonly releaseTitle: Locator;
  readonly knowledgeWorkspaceNavigation: Locator;
  readonly testTitle: Locator;
  readonly qualityGate: Locator;
  readonly publishButton: Locator;
  readonly scopedPublishButtons: Locator;
  readonly runButton: Locator;
  readonly activeReleaseCard: Locator;

  constructor(page: Page) {
    super(page, 'http://127.0.0.1:3000');
    this.navigation = page.getByRole('navigation').filter({
      has: page.getByRole('button', { name: '概览', exact: true }),
    });
    this.buildTitle = page.getByRole('heading', { name: '知识构建', exact: true });
    this.newBuildTaskButton = page.getByRole('button', { name: '新建构建任务', exact: true });
    this.reviewTitle = page.getByRole('heading', { name: '知识审核', exact: true });
    this.releaseTitle = page.getByRole('heading', { name: '发布管理', exact: true });
    this.knowledgeWorkspaceNavigation = page.getByRole('navigation', { name: '知识治理工作区' });
    this.testTitle = page.getByRole('heading', { name: '政策知识测试' });
    this.qualityGate = page.getByRole('heading', { name: '候选版与活动版同集对跑' });
    this.publishButton = page.getByRole('button', { name: '人工发布候选版本' });
    this.scopedPublishButtons = page.getByRole('button', { name: /发布.*Unit|发布.*Knowledge/ });
    this.runButton = page.getByRole('button', { name: '批量统一测试' });
    this.activeReleaseCard = page.getByText('当前活动版本').locator('..');
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

  async workspaceLabels(): Promise<string[]> {
    return this.knowledgeWorkspaceNavigation.getByRole('link').allTextContents();
  }

  async runCandidate(): Promise<void> {
    await this.runButton.click();
  }

  async publishCandidate(): Promise<void> {
    await this.publishButton.click();
  }

  blockedReason(reason: string): Locator {
    return this.page.getByText(reason);
  }

  rollbackButton(releaseId: string): Locator {
    return this.page.getByRole('button', { name: `回滚到 ${releaseId}` });
  }
}
