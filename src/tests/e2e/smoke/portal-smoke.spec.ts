import { test, expect } from '@playwright/test';
import { ChatPage } from '../pages/portal/chat.page';
import { SettlementPage } from '../pages/portal/settlement.page';
import { QCPage } from '../pages/portal/qc.page';
import { DashboardPage } from '../pages/portal/dashboard.page';
import { waitForAPIReady } from '../utils/wait-strategies';

test.describe('Portal 冒烟测试', () => {
  test.beforeAll(async () => {
    await waitForAPIReady('http://127.0.0.1:8000', 30000);
  });

  test('Chat 导办页面加载', async ({ page }) => {
    const chatPage = new ChatPage(page);
    await chatPage.goto();
    await expect(page).not.toHaveTitle(/error/i);
  });

  test('结算异常页面加载', async ({ page }) => {
    const settlementPage = new SettlementPage(page);
    await settlementPage.goto();
    await expect(page).not.toHaveTitle(/error/i);
  });

  test('质控页面加载', async ({ page }) => {
    const qcPage = new QCPage(page);
    await qcPage.goto();
    await expect(page).not.toHaveTitle(/error/i);
  });

  test('运营看板页面加载', async ({ page }) => {
    const dashboardPage = new DashboardPage(page);
    await dashboardPage.goto();
    await expect(page).not.toHaveTitle(/error/i);
  });

  test('导航菜单切换', async ({ page }) => {
    const chatPage = new ChatPage(page);
    await chatPage.goto();

    await chatPage.navigateTo('/settlement');
    await expect(page).toHaveURL(/settlement/);

    await chatPage.navigateTo('/qc');
    await expect(page).toHaveURL(/qc/);

    await chatPage.navigateTo('/dashboard');
    await expect(page).toHaveURL(/dashboard/);
  });
});
