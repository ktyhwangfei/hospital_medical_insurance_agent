import { expect, type Page } from '@playwright/test';

import { BasePage } from '../base.page';
import { E2E_FRONTEND_URL } from '../../utils/workspace-ports';

export class DataGovernancePage extends BasePage {
  constructor(page: Page) {
    super(page, E2E_FRONTEND_URL);
  }

  async gotoDataSources(): Promise<void> {
    await super.goto('/data-governance/data-sources');
  }

  async gotoSyncJobs(): Promise<void> {
    await super.goto('/data-governance/sync-jobs');
  }

  async createSource(password: string): Promise<void> {
    await this.page.getByRole('button', { name: '新增数据源' }).click();
    await this.page.getByLabel('数据源 ID').fill('hospital-e2e');
    await this.page.getByLabel('医院编码').fill('H-E2E');
    await this.page.getByLabel('医院名称').fill('E2E 示例医院');
    await this.page.getByLabel('数据源名称').fill('门诊医保库');
    await this.page.getByLabel('主机').fill('10.20.30.40');
    await this.page.getByLabel('数据库').fill('bjybdb');
    await this.page.getByLabel('用户名').fill('readonly');
    await this.page.getByLabel('凭据 ID').fill('credential.hospital-e2e');
    await this.page.getByLabel('密码').fill(password);
    await this.page.getByRole('button', { name: '保存数据源' }).click();
    await expect(this.page.getByText('数据源已保存')).toBeVisible();
  }

  async configureScheduledSql(): Promise<void> {
    await this.page.getByLabel('同步方式').selectOption('scheduled_sql');
    await this.page.getByText('确认切换同步模式。下次运行将重新建立基线。').click();
    await this.page.getByRole('button', { name: '保存配置' }).click();
    await expect(this.page.getByText('同步配置已保存')).toBeVisible();
  }

  async startRunAndPause(): Promise<void> {
    await this.page.getByRole('button', { name: '启动任务' }).click();
    await expect(this.page.getByText('任务已启动')).toBeVisible();
    await this.page.getByRole('button', { name: '立即执行' }).click();
    await expect(this.page.getByText('已请求，worker 将按队列执行')).toBeVisible();
    await expect(this.page.getByText('batch-e2e')).toBeVisible();
    await this.page.getByRole('button', { name: '暂停任务' }).click();
    await expect(this.page.getByText('任务已暂停')).toBeVisible();
  }

  async expectSecretAbsent(secret: string): Promise<void> {
    await expect(this.page.locator('body')).not.toContainText(secret);
    const storage = await this.page.evaluate(() => JSON.stringify({
      local: Object.fromEntries(Object.entries(localStorage)),
      session: Object.fromEntries(Object.entries(sessionStorage)),
    }));
    expect(storage).not.toContain(secret);
  }

  async expectReadOnly(): Promise<void> {
    await expect(this.page.getByText('凭据已配置')).toBeVisible();
    await expect(this.page.getByRole('button', { name: '新增数据源' })).toHaveCount(0);
    await expect(this.page.getByRole('button', { name: '测试连接' })).toHaveCount(0);
  }
}
